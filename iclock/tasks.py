"""
Celery tasks -- proses tulis-ke-DATABASE untuk data push protocol
(attendance/operation log/fingerprint template), dipanggil endpoint
`/iclock/cdata` (dibangun tahap berikutnya) SETELAH data ditulis ke text
file (iclock/pushsdk_writer.py) DAN PIN-nya valid (Rule 3) -- lihat
test/myrule.md Rule 4.

PENTING: task-task ini menerima DATA LANGSUNG (bukan path file) -- text
file (pushsdk_writer.py) berfungsi sbg log durability/audit terpisah, BUKAN
sumber data task ini (menghindari kerumitan "baca ulang baris tertentu dari
file harian yang dipakai bersama banyak device").
"""
import logging

from celery import shared_task
from django.utils.dateparse import parse_datetime

from .models import RegisteredDevice, devlog, employee, fptemp, iclock, oplog, transaction
from .services import normalize_pin

logger = logging.getLogger('iclock.pushsdk')


def _get_device_or_none(sn: str):
    """Employee/oplog/fptemp/transaction butuh FK ke `iclock` (Active Device) -- pakai cache-aware lookup."""
    device = iclock.get_cached(sn)
    if device is None:
        logger.warning("Task DB-write: device SN='%s' tidak ditemukan di Active Device -- data dilewati.", sn)
    return device


def _parse_operlog_fields(fields: str) -> dict:
    """Parse payload 'Key=Value' dipisah tab (format asli protokol, lihat resume §4.2) jadi dict."""
    result = {}
    for item in fields.split('\t'):
        if '=' in item:
            key, _, value = item.partition('=')
            result[key] = value
    return result


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def write_attlog_to_db(self, sn: str, pin: str, timestamp_iso: str, check_type: str):
    """
    Tulis 1 baris ATTLOG ke tabel `transaction` -- HANYA dipanggil endpoint
    utk PIN yang SUDAH lolos validasi Rule 3 (is_valid_device_pin).
    `get_or_create` dipakai supaya panggilan ganda (mis. Celery retry)
    TIDAK membuat baris transaksi duplikat.
    """
    device = _get_device_or_none(sn)
    if device is None:
        return {'success': False, 'error': f"Device SN='{sn}' tidak ditemukan"}

    normalized_pin = normalize_pin(pin)
    emp = employee.objects.filter(PIN=normalized_pin).first()
    if emp is None:
        logger.warning("Task DB-write ATTLOG: PIN '%s' (device %s) tidak ditemukan di Employee -- dilewati.", normalized_pin, sn)
        return {'success': False, 'error': f"Employee PIN='{normalized_pin}' tidak ditemukan"}

    timestamp = parse_datetime(timestamp_iso)
    if timestamp is None:
        logger.warning("Task DB-write ATTLOG: timestamp '%s' tidak valid -- dilewati.", timestamp_iso)
        return {'success': False, 'error': 'Timestamp tidak valid'}

    _trx, created = transaction.objects.get_or_create(
        UserID=emp, TTime=timestamp, SN=device,
        defaults={'State': check_type, 'Verify': 0},
    )
    return {'success': True, 'created': created}


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def write_operlog_user_to_db(self, sn: str, fields: str):
    """
    Tulis/update data Employee dari 1 baris OPERLOG bertag 'USER' -- format
    field 'PIN=...\\tName=...\\tPasswd=...\\tCard=...\\tGrp=...\\tTZ=...'
    (lihat resume protokol §4.2). Employee BARU dibuat kalau PIN belum ada.
    """
    device = _get_device_or_none(sn)
    parsed = _parse_operlog_fields(fields)
    pin = parsed.get('PIN', '')
    if not pin:
        logger.warning("Task DB-write USER: baris tanpa PIN, dilewati: %s", fields)
        return {'success': False, 'error': 'PIN tidak ada di payload'}

    normalized_pin = normalize_pin(pin)
    defaults = {}
    if parsed.get('Name'):
        defaults['EName'] = parsed['Name']
    if 'Passwd' in parsed:
        defaults['Password'] = parsed['Passwd'] or None
    if 'Card' in parsed:
        defaults['Card'] = parsed['Card'].strip('[]') or None
    if 'Grp' in parsed and parsed['Grp'].isdigit():
        defaults['AccGroup'] = int(parsed['Grp'])
    if device is not None:
        defaults['SN'] = device

    emp, created = employee.objects.update_or_create(PIN=normalized_pin, defaults=defaults)
    return {'success': True, 'created': created, 'pin': normalized_pin}


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def write_operlog_admin_to_db(self, sn: str, fields: str):
    """
    Tulis 1 baris OPERLOG bertag 'OPLOG' (log aksi admin -- power on/off,
    alarm, ubah config, dst) ke tabel `oplog`. Format field POSISIONAL
    (bukan Key=Value): 'opcode\\tadmin\\ttime\\tobj1\\tobj2\\tobj3\\tobj4'
    (lihat resume protokol §4.2.1 utk arti tiap kode operasi).
    """
    device = _get_device_or_none(sn)
    parts = fields.split('\t')
    if len(parts) < 3:
        logger.warning("Task DB-write OPLOG: field kurang (%d, minimal 3), dilewati: %s", len(parts), fields)
        return {'success': False, 'error': 'Field tidak lengkap'}

    op_code, admin_id, time_str = parts[0], parts[1], parts[2]
    objects = parts[3:7] + ['', '', '', ''][:max(0, 4 - len(parts[3:7]))]

    op_time = parse_datetime(time_str)
    if op_time is None:
        # Format asli protokol 'YYYY-MM-DD HH:MM:SS' (bukan ISO 8601) -- coba parse manual.
        import datetime as dt
        try:
            op_time = dt.datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning("Task DB-write OPLOG: waktu '%s' tidak valid, dilewati.", time_str)
            return {'success': False, 'error': 'Waktu tidak valid'}

    def _to_int_or_none(v):
        return int(v) if v and v.lstrip('-').isdigit() else None

    log = oplog.objects.create(
        SN=device,
        admin=_to_int_or_none(admin_id) or 0,
        OP=_to_int_or_none(op_code) or 0,
        OPTime=op_time,
        Object=_to_int_or_none(objects[0]),
        Param1=_to_int_or_none(objects[1]),
        Param2=_to_int_or_none(objects[2]),
        Param3=_to_int_or_none(objects[3]),
    )
    return {'success': True, 'id': log.id}


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def write_fplog_to_db(self, sn: str, fields: str):
    """
    Tulis/update template fingerprint dari 1 baris OPERLOG bertag 'FP' --
    format 'PIN=...\\tFID=...\\tValid=...\\tTMP=...' (base64 template).
    """
    device = _get_device_or_none(sn)
    parsed = _parse_operlog_fields(fields)
    pin = parsed.get('PIN', '')
    if not pin:
        logger.warning("Task DB-write FP: baris tanpa PIN, dilewati: %s", fields[:80])
        return {'success': False, 'error': 'PIN tidak ada di payload'}

    normalized_pin = normalize_pin(pin)
    emp = employee.objects.filter(PIN=normalized_pin).first()
    if emp is None:
        logger.warning("Task DB-write FP: PIN '%s' tidak ditemukan di Employee -- dilewati.", normalized_pin)
        return {'success': False, 'error': f"Employee PIN='{normalized_pin}' tidak ditemukan"}

    try:
        fid = int(parsed.get('FID', 0))
    except ValueError:
        fid = 0
    try:
        valid = int(parsed.get('Valid', 1))
    except ValueError:
        valid = 1
    template = parsed.get('TMP', '')

    fp, created = fptemp.objects.update_or_create(
        UserID=emp, FingerID=fid,
        defaults={'Template': template, 'Valid': valid, 'SN': device},
    )
    return {'success': True, 'created': created}