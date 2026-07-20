"""
Endpoint HTTP yang mengimplementasikan PUSH SDK Communication Protocol V2.0.1
(lihat test/pushsdk_protocol_resume.md) -- INI YANG DIHUBUNGI LANGSUNG oleh
device fisik (bukan browser/API client Nuxt), jadi:

- URL path TETAP `/iclock/cdata`, `/iclock/getrequest`, `/iclock/devicecmd`
  (device firmware HARDCODED ke path ini, tidak bisa dikustomisasi -- lihat
  config/urls.py, di-mount di ROOT, BUKAN di bawah /admin/iclock/ atau
  /api/v1/iclock/ yang sudah ada).
- TIDAK pakai autentikasi Django biasa (device bukan user login) --
  "otentikasi" device cuma berdasar apakah SN-nya terdaftar sbg Active
  Device (lihat `resolve_device()`, Rule 2a).
- Response HARUS plain text sesuai protokol, BUKAN JSON.
- csrf_exempt WAJIB (device tidak kirim CSRF token, bukan browser).
"""
import logging
from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import RegisteredDevice, devcmds, get_default_department, get_pending_commands, iclock
from .pushsdk_writer import append_attlog_line, append_fplog_line, append_oplog_line
from .tasks import write_attlog_to_db, write_fplog_to_db, write_operlog_admin_to_db, write_operlog_user_to_db
from .ws_utils import wsinfo

logger = logging.getLogger('iclock.pushsdk')

MAX_COMMANDS_PER_RESPONSE = 200
MAX_RESPONSE_SIZE_BYTES = 40 * 1024


def _text_response(body: str) -> HttpResponse:
    return HttpResponse(body, content_type='text/plain')


def _resolve_request_ip(request) -> str:
    """
    IP address SUNGGUHAN device -- ADA mekanisme mirroring di sistem ADMS
    production Anda (tiap request production di-mirror ke sistem dev ini),
    jadi `REMOTE_ADDR` yang diterima DI SINI adalah IP SERVER MIRRORING-nya,
    BUKAN IP device aslinya. Production mengirim IP asli lewat query param
    `ORIGINIP` -- kalau ada, PAKAI itu; kalau tidak ada (request LANGSUNG
    dari device, bukan hasil mirroring), baru fallback ke `REMOTE_ADDR`
    seperti biasa.
    """
    mirror_ip = request.GET.get('ORIGINIP')
    if mirror_ip:
        return mirror_ip
    return request.META.get('REMOTE_ADDR', '') or ''


def resolve_device(request):
    """
    Rule 2a: cek SN device ada di Active Device (iclock) atau belum.

    Return (device, error_response):
    - SN ada di Active Device -> (device, None), lanjut proses normal.
    - SN BELUM ada -> (None, response_text) -- SUDAH auto-create/update
      RegisteredDevice (DeptID=0) di sini, TAPI caller HARUS langsung
      return `error_response` tanpa lanjut proses apa pun lagi (Rule 2a:
      "tidak dilanjutkan ke proses berikutnya"). Promosi RegisteredDevice
      -> Active Device TETAP lewat mekanisme admin yang SUDAH ADA
      (iclock/services.py::maybe_activate_after_pool_change, dipicu saat
      admin set Pool-nya lewat dashboard) -- BUKAN otomatis di sini.
    - SN kosong sama sekali (request cacat) -> (None, response_text).
    """
    sn = request.GET.get('SN', '').strip()
    if not sn:
        logger.warning("Request push protocol tanpa parameter SN dari IP %s", _resolve_request_ip(request))
        return None, _text_response('UNKNOWN Device')

    device = iclock.get_cached(sn)
    if device is not None:
        return device, None

    ip_address = _resolve_request_ip(request)
    now = timezone.now()
    regdevice = RegisteredDevice.objects.filter(SN=sn).first()
    if regdevice is None:
        regdevice = RegisteredDevice.objects.create(
            SN=sn, Alias=ip_address, IPAddress=ip_address,
            DeptID=get_default_department(), LastActivity=now,
        )
        logger.info("Device baru auto-registrasi: SN=%s IP=%s", sn, ip_address)
        wsinfo('iclock', 'device_register', {'SN': sn, 'ip': ip_address, 'time': now.strftime('%Y-%m-%d %H:%M:%S')})
    else:
        regdevice.IPAddress = ip_address
        regdevice.LastActivity = now
        regdevice.save()

    return None, _text_response(f'UNKNOWN Device: {sn}')


@csrf_exempt
def cdata(request):
    device, error_response = resolve_device(request)
    if error_response is not None:
        return error_response

    if request.method == 'POST':
        return _cdata_post(request, device)
    return _cdata_get(request, device)


def _cdata_get(request, device):
    """
    Baca konfigurasi server (resume protokol §3) -- field diambil LANGSUNG
    dari kolom per-device di `iclock` (test/myrule.md Rule 2), bukan
    hardcode/settings global.
    """
    pushver = request.GET.get('pushver', '').strip()
    if pushver and pushver != (device.PushVersion or ''):
        device.PushVersion = pushver

    lines = [f'GET OPTION FROM: {device.SN}']
    if pushver:
        lines.append(f'ATTLOGStamp={device.LogStamp or 0}')
        lines.append(f'OPERLOGStamp={device.OpLogStamp or 0}')
        lines.append(f'ATTPHOTOStamp={device.PhotoStamp or 0}')
    else:
        lines.append(f'Stamp={device.LogStamp or 0}')
        lines.append(f'OpStamp={device.OpLogStamp or 0}')
        lines.append(f'PhotoStamp={device.PhotoStamp or 0}')
    lines.append(f'ErrorDelay={device.ErrorDelay}')
    lines.append(f'Delay={device.Delay}')
    lines.append(f'TransTimes={device.TransTimes}')
    lines.append(f'TransInterval={device.TransInterval}')
    lines.append(f'TransFlag={device.UpdateDB}')
    if device.TZAdj is not None:
        lines.append(f'TimeZone={0 if device.TZAdj == 14 else device.TZAdj}')
    lines.append(f'Realtime={1 if device.Realtime else 0}')
    lines.append(f'Encrypt={1 if device.Encrypt else 0}')
    if pushver:
        lines.append('ServerVer=1.0.0')
        lines.append('TableNameStamp')

    device.save()
    return _text_response('\n'.join(lines) + '\n\n')


def _cdata_post(request, device):
    """Upload data (ATTLOG/OPERLOG/ATTPHOTO) dari device -- resume protokol §4."""
    table = request.GET.get('table', '')
    raw_data = request.body.decode('utf-8', errors='replace')

    if table == 'ATTLOG':
        return _handle_attlog_upload(request, device, raw_data)
    elif table == 'OPERLOG':
        return _handle_operlog_upload(request, device, raw_data)
    elif table == 'ATTPHOTO':
        device.save_heartbeat()
        return _text_response('OK\n')

    device.save_heartbeat()
    return _text_response('UNKNOWN DATA\n')


def _handle_attlog_upload(request, device, raw_data):
    """
    Rule 3 + Rule 4: tiap baris ATTLOG ('PIN\\tTIME\\tSTATUS\\tVERIFY\\t...')
    ditulis ke text file harian DULU (append_attlog_line), baru kalau
    PIN-nya valid (7/8 digit tanpa leading zero) di-lempar ke Celery task
    tulis-DB juga. PIN tidak valid TETAP dicatat ke text file (folder
    '_other'), TAPI TIDAK PERNAH masuk database.

    Field ke-4 (VERIFY) OPSIONAL sesuai protokol asli ("beberapa mesin
    attendance tidak kirim field ini" -- resume protokol §4.1) -- default
    0 kalau tidak ada. Verify diteruskan APA ADANYA ke text file & task DB
    -- konsolidasi device absen mobile (verify=PoolID 3 digit) BUKAN
    ditangani di sini, itu proses import terpisah di masa depan.
    """
    ok_count = 0
    for line in raw_data.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) < 3:
            logger.warning("Baris ATTLOG tidak lengkap dari SN=%s, dilewati: %r", device.SN, line)
            continue
        pin, time_str, check_type = parts[0], parts[1], parts[2]
        verify = parts[3] if len(parts) > 3 else '0'
        try:
            timestamp = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning("Waktu ATTLOG tidak valid dari SN=%s: %r", device.SN, time_str)
            continue

        _path, pin_valid = append_attlog_line(device.SN, pin, timestamp, check_type, verify)
        if pin_valid:
            write_attlog_to_db.delay(device.SN, pin, timestamp.isoformat(), check_type, verify)
        ok_count += 1

        wsinfo('iclock', 'device_attlog', {
            'sn': device.SN, 'la': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'pin': pin, 'time': time_str, 'type': check_type,
        })

    stamp = request.GET.get('Stamp', '')
    if stamp:
        device.LogStamp = stamp
    device.save()
    return _text_response(f'OK:{ok_count}\n')


def _handle_operlog_upload(request, device, raw_data):
    """
    Rule 3 + Rule 4: tiap baris OPERLOG diawali tag 'USER '/'FP '/'OPLOG '
    (resume protokol §4.2). USER & FP divalidasi PIN-nya (Rule 3); OPLOG
    (log aksi admin) SELALU dianggap valid (lihat catatan di
    pushsdk_writer.py::append_oplog_line kenapa).
    """
    ok_count = 0
    now = timezone.now()
    for line in raw_data.splitlines():
        line = line.strip()
        if not line or ' ' not in line:
            continue
        tag, rest = line.split(' ', 1)

        if tag == 'USER':
            _path, pin_valid = append_oplog_line(device.SN, 'USER', rest, now)
            if pin_valid:
                write_operlog_user_to_db.delay(device.SN, rest)
        elif tag == 'FP':
            _path, pin_valid = append_fplog_line(device.SN, rest, now)
            if pin_valid:
                write_fplog_to_db.delay(device.SN, rest)
        elif tag == 'OPLOG':
            append_oplog_line(device.SN, 'OPLOG', rest, now)
            write_operlog_admin_to_db.delay(device.SN, rest)
        else:
            logger.warning("Tag OPERLOG tidak dikenal dari SN=%s: %r", device.SN, tag)
            continue
        ok_count += 1

    stamp = request.GET.get('Stamp', '') or request.GET.get('OpStamp', '')
    if stamp:
        device.OpLogStamp = stamp
    device.save()
    return _text_response(f'OK:{ok_count}\n')


@csrf_exempt
def getrequest(request):
    device, error_response = resolve_device(request)
    if error_response is not None:
        return error_response

    info = request.GET.get('INFO', '')
    if info:
        wsinfo('iclock', 'device_request', {
            'sn': device.SN, 'la': timezone.now().strftime('%Y-%m-%d %H:%M:%S'), 'devinfo': info,
        })

    commands = get_pending_commands(device)
    lines = []
    for cmd in commands:
        line = f'C:{cmd.id}:{cmd.CmdContent}'
        candidate = lines + [line]
        if len(candidate) > MAX_COMMANDS_PER_RESPONSE or sum(len(l) + 1 for l in candidate) > MAX_RESPONSE_SIZE_BYTES:
            break
        lines.append(line)
        cmd.CmdTransTime = timezone.now()
        cmd.save(update_fields=['CmdTransTime'])
        if cmd.CmdContent.strip() in ('REBOOT', 'RESTART'):
            break

    device.save_heartbeat()

    if not lines:
        return _text_response('OK')
    return _text_response('\n'.join(lines) + '\n')


@csrf_exempt
@require_POST
def devicecmd(request):
    device, error_response = resolve_device(request)
    if error_response is not None:
        return error_response

    body = request.body.decode('utf-8', errors='replace')
    params = {}
    for pair in body.split('&'):
        if '=' in pair:
            key, _, value = pair.partition('=')
            params[key] = value

    cmd_id = params.get('ID')
    ret = params.get('Return')
    if cmd_id:
        devcmds.objects.filter(id=cmd_id).update(CmdOverTime=timezone.now(), CmdReturn=ret)
    else:
        logger.warning("POST devicecmd dari SN=%s tanpa ID: %r", device.SN, body)

    device.save_heartbeat()
    return _text_response(f'OK\nPOST from: {device.SN}\n')