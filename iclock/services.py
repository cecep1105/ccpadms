"""
Service layer kecil untuk app 'iclock'.

Beda dengan accounts/services.py yang menaungi hampir semua logic auth &
manajemen user, di sini isinya cuma logic yang genuinely dipakai bersama oleh
dashboard (views.py) dan API (api_views.py) -- yaitu aturan auto-aktivasi
Registered Device -> Active Device, dan backup fingerprint device -> DB.
CRUD sederhana lainnya cukup lewat ModelForm (dashboard) / ModelSerializer
(API) langsung.
"""
import base64
import re

from django.db import transaction as db_transaction
from django.utils import timezone

from .models import RegisteredDevice, employee, fptemp, iclock
from .zk_client import DeviceConnectionError, fetch_device_users_and_templates

UNREGISTERED_POOL_ID = 0  # Pool ID default saat device baru pertama kali konek (belum diaktifkan)

# PIN yang didaftarkan LANGSUNG di device fisik biasanya cuma 7-8 digit
# (TANPA leading zero) -- tapi konvensi PIN di database/sistem kita adalah
# 9 digit zero-padded (mis. device: '8113009', sistem: '008113009'). Tanpa
# normalisasi ini, PIN mentah dari device tidak akan pernah cocok/match
# dengan Employee yang sudah ada di database (yang PIN-nya sudah 9 digit),
# menyebabkan Employee BARU (duplikat, keliru) ke-buat setiap kali alih-alih
# mencocokkan ke record yang sudah benar.
PIN_ZERO_PAD_LENGTH = 9


def normalize_pin(raw_pin) -> str:
    """
    Normalisasi PIN mentah dari device fisik (pyzk `user_id`, biasanya numerik
    tanpa leading zero) supaya cocok dengan konvensi PIN 9-digit zero-padded
    yang dipakai Employee di database kita. Dipakai di semua tempat yang
    mencocokkan PIN dari device fisik ke `employee.PIN` -- backup fingerprint,
    sinkronisasi privilege, dan hapus user (lihat pemakaiannya di
    `iclock/services.py::backup_device_fingerprints` & `iclock/views.py`).

    PIN yang bukan angka murni (ada huruf/karakter lain) TIDAK di-zero-pad --
    dikembalikan apa adanya, karena aturan zero-pad ini spesifik utk PIN
    numerik.
    """
    raw_pin = str(raw_pin).strip()
    if raw_pin.isdigit() and len(raw_pin) < PIN_ZERO_PAD_LENGTH:
        return raw_pin.zfill(PIN_ZERO_PAD_LENGTH)
    return raw_pin


def get_raw_device_pin(padded_pin: str) -> str:
    """
    Kebalikan dari `normalize_pin()` -- buang leading zero padding,
    kembalikan PIN "asli" sesuai yang device kirim (padanan `devicePIN()`
    di test/utils.py Anda). SENGAJA tidak pernah mengembalikan string
    kosong -- loop cuma sampai index -1 (bukan index terakhir), jadi kalau
    PIN semua nol (kasus ekstrem), minimal 1 karakter terakhir tetap
    dikembalikan -- perilaku ini DIPERTAHANKAN PERSIS dari implementasi
    legacy Anda (bukan kebetulan/bug).
    """
    if not padded_pin:
        return padded_pin
    i = 0
    for c in padded_pin[:-1]:
        if c == '0':
            i += 1
        else:
            break
    return padded_pin[i:]


def is_valid_device_pin(raw_or_padded_pin: str) -> bool:
    """
    Rule 3 (test/myrule.md): PIN dari device dianggap VALID kalau, setelah
    leading zero padding dibuang (`get_raw_device_pin`), panjangnya 7 ATAU
    8 digit (semua angka). Dipakai menentukan apakah data attendance/
    oplog/fplog device ini masuk 'masterattlog' (diproses normal + celery
    task tulis DB) atau 'masterattlog_other' (cuma dicatat text file,
    TIDAK ditulis ke DB) -- lihat Rule 4 (bagian tahap berikutnya).
    """
    stripped = get_raw_device_pin(raw_or_padded_pin or '')
    return stripped.isdigit() and len(stripped) in (7, 8)


def activate_device_to_iclock(registered_device: RegisteredDevice) -> bool:
    """
    Copy record dari RegisteredDevice ke iclock (Active Device), kalau SN-nya
    belum ada di sana. Dipanggil saat Pool ID sebuah Registered Device berubah
    dari 0 (belum aktif) ke pool lain (dianggap sebagai aksi aktivasi).

    Return True kalau device baru dibuat di Active Device, False kalau SN
    tersebut sudah ada di sana sebelumnya (tidak melakukan apa-apa).
    """
    if iclock.objects.filter(pk=registered_device.SN).exists():
        return False
    iclock.objects.create(
        SN=registered_device.SN,
        Alias=registered_device.DeviceName or registered_device.SN,
        DeptID=registered_device.DeptID,
        IPAddress=registered_device.IPAddress,
        MAC=registered_device.MAC,
        # BUG FIX: Function SEBELUMNYA tidak ikut disalin -- kalau admin
        # ubah Function (mis. TESTING -> KANTIN) BERSAMAAN dgn ubah Pool
        # dari guest ke non-guest di form yang SAMA, hasil salinan ke
        # Active Device diam-diam tetap Function default ('0'), harus
        # diedit ULANG manual di Active Device -- sekarang ikut tersalin.
        Function=registered_device.Function or '0',
    )
    return True


def maybe_activate_after_pool_change(registered_device: RegisteredDevice, old_dept_id) -> bool:
    """
    Bandingkan Pool ID lama vs Pool ID saat ini pada `registered_device`, dan
    panggil activate_device_to_iclock() kalau transisinya persis 0 -> non-0.

    `old_dept_id` harus diambil SEBELUM perubahan disimpan (mis. dari
    `instance.DeptID_id` sebelum form/serializer memproses data baru).
    """
    new_dept_id = registered_device.DeptID_id
    if old_dept_id == UNREGISTERED_POOL_ID and new_dept_id not in (None, UNREGISTERED_POOL_ID):
        return activate_device_to_iclock(registered_device)
    return False


def backup_device_fingerprints(device: iclock, pin_pattern: str = '') -> list:
    """
    "Backup Data Finger": ambil semua user + template fingerprint LANGSUNG
    dari device fisik (via pyzk), lalu ADD/MODIFY (upsert) ke tabel fptemp
    di database kita. Kalau ada user di device yang belum ada di tabel
    Employee (dicocokkan via PIN=user_id SETELAH dinormalisasi -- lihat
    `normalize_pin()`), otomatis dibuatkan record Employee dasar dulu
    supaya fptemp punya FK yang valid.

    PENTING soal PIN: device fisik biasanya mendaftarkan PIN 7-8 digit
    TANPA leading zero (mis. '8113009'), sedangkan konvensi PIN di sistem
    kita 9 digit zero-padded (mis. '008113009'). Tanpa normalisasi, PIN
    mentah dari device TIDAK akan cocok dengan Employee yang sudah ada di
    database, menyebabkan Employee BARU (duplikat, keliru) selalu ke-buat
    setiap kali backup dijalankan. Setiap PIN dari device dinormalisasi
    lewat `normalize_pin()` SEBELUM dipakai untuk mencocokkan/membuat
    Employee.

    `pin_pattern`: regex opsional -- kalau diisi, cuma PIN yang match
    (`re.match`, dicek dari AWAL string PIN, terhadap PIN yang SUDAH
    dinormalisasi) yang diproses. Dipakai supaya tidak perlu backup SEMUA
    user tiap kali (device dengan ribuan user bisa lama sekali kalau full
    backup) -- mis. isi `^008` untuk cuma PIN yang diawali '008'.

    Template disimpan sebagai base64 text (field Template = TextField, tapi
    data asli dari device berupa bytes biner).

    Return: list of log strings (siapa dibuat/diperbarui/dilewati).
    """
    log = [f'Menghubungkan ke device {device.SN} ({device.IPAddress})...']
    try:
        users, templates_by_uid = fetch_device_users_and_templates(device.IPAddress)
    except DeviceConnectionError as exc:
        log.append(f'GAGAL: {exc}')
        return log

    total_fingers_all = sum(len(v) for v in templates_by_uid.values())
    log.append(f'Terhubung. Total user di device: {len(users)}, total entri fingerprint: {total_fingers_all}.')

    compiled_pattern = None
    if pin_pattern:
        compiled_pattern = re.compile(pin_pattern)
        log.append(f"Filter PIN aktif: '{pin_pattern}' -- user yang tidak cocok akan dilewati.")

    created_employees = 0
    created_templates = 0
    updated_templates = 0
    skipped_no_finger = 0
    skipped_filter = 0
    normalized_count = 0

    with db_transaction.atomic():
        for u in users:
            raw_pin = u['user_id']
            pin = normalize_pin(raw_pin)
            if pin != raw_pin:
                normalized_count += 1

            # Filter dicocokkan ke PIN yang SUDAH dinormalisasi (9 digit
            # zero-padded) -- konsisten dengan konvensi PIN Employee di
            # database, supaya pola regex yang diisi admin (mis. '^008')
            # match dengan PIN sistem, bukan PIN mentah device.
            if compiled_pattern and not compiled_pattern.match(pin):
                skipped_filter += 1
                continue

            fingers = templates_by_uid.get(u['uid'], [])
            if not fingers:
                skipped_no_finger += 1
                continue

            emp, emp_created = employee.objects.get_or_create(
                PIN=pin,
                defaults={
                    'EName': u['name'] or pin,
                    'Privilege': u['privilege'],
                    'Card': u['card'],
                    'SN': device,
                },
            )
            if emp_created:
                created_employees += 1
                pin_note = f" (PIN device '{raw_pin}' dinormalisasi jadi '{pin}')" if pin != raw_pin else ""
                log.append(f"  [{pin}] Employee baru dibuat ({emp.EName}){pin_note}.")

            for finger in fingers:
                raw_template = finger['template'] or b''
                encoded_template = base64.b64encode(raw_template).decode('ascii')
                _tpl, tpl_created = fptemp.objects.update_or_create(
                    UserID=emp,
                    FingerID=finger['fid'],
                    defaults={
                        'Template': encoded_template,
                        'Valid': 1 if finger['valid'] else 0,
                        'SN': device,
                        'UTime': timezone.now(),
                    },
                )
                if tpl_created:
                    created_templates += 1
                else:
                    updated_templates += 1

    log.append(
        f'Selesai. Employee baru: {created_employees}. Template baru: {created_templates}. '
        f'Template diperbarui: {updated_templates}. User tanpa fingerprint dilewati: {skipped_no_finger}. '
        f'User dilewati krn tidak cocok filter PIN: {skipped_filter}. '
        f'PIN dinormalisasi (zero-pad {PIN_ZERO_PAD_LENGTH} digit): {normalized_count}.'
    )
    return log

def lookup_employee_name(raw_pin: str) -> str | None:
    """
    Cari nama employee dari SQL Server eksternal (iclock/sources.py)
    berdasar PIN prefix -- dipakai saat auto-create Employee dari push
    protocol (iclock/tasks.py), karena ATTLOG/FP device TIDAK pernah
    kirim nama sama sekali.

    Best-effort: return None kalau prefix PIN tidak match sumber manapun,
    ATAU koneksi/query MSSQL gagal, ATAU tidak ketemu barisnya -- JANGAN
    sampai kegagalan lookup ini bikin proses auto-create Employee-nya ikut
    gagal (nama boleh kosong dulu, dilengkapi manual admin belakangan).
    """
    import logging

    # Import lokal (bukan di top-level file) -- iclock/sources.py &
    # mclock/mssql_client.py TIDAK butuh dimuat di startup Django biasa,
    # cuma saat lookup ini benar-benar dipanggil (auto-create Employee).
    from mclock.mssql_client import MSSQLConnectionError, run_query

    from .sources import get_name_lookup_source

    logger = logging.getLogger('iclock.pushsdk')

    raw = get_raw_device_pin(raw_pin)
    found = get_name_lookup_source(raw)
    if found is None:
        return None
    key, source = found

    try:
        rows = run_query(
            source['base_sql'], params=source['param'](raw),
            server=source['server'], database=source['database'],
        )
    except MSSQLConnectionError as exc:
        logger.warning("Lookup nama employee (sumber '%s') gagal utk PIN '%s': %s", key, raw, exc)
        return None
    except Exception as exc:  # noqa: BLE001 -- param() bisa IndexError dsb kalau PIN terlalu pendek utk transform driver-hrc
        logger.warning("Lookup nama employee (sumber '%s') error tak terduga utk PIN '%s': %s", key, raw, exc)
        return None

    if not rows:
        return None
    return rows[0].get(source['name_column']) or None


def determine_transaction_function(raw_pin: str, device) -> str | None:
    """
    Tentukan kode `Function` utk 1 baris ATTLOG (tabel `transaction`),
    sesuai `settings.DEVICEFUNCTION`.

    1. Kalau device INI SENDIRI sudah dikonfigurasi `Function='X'` (KANTIN
       -- field yang SAMA dipilih admin dari dropdown "Function" saat
       setup Active Device, lihat iclock/forms.py::_device_function_choices)
       -> transaction ini JUGA 'X', APAPUN PIN-nya (device kantin berarti
       SEMUA check-in lewat situ dianggap aktivitas kantin).
    2. Selain itu -> cocokkan KARAKTER PERTAMA PIN MENTAH (leading zero
       dibuang, lihat get_raw_device_pin) ke tiap KEY di
       settings.DEVICEFUNCTION -- tiap KARAKTER dalam 1 key adalah prefix
       valid (mis. key '89' berarti prefix '8' ATAU '9' -> function code
       '89' -- lihat contoh myrule.md: PIN '8113009' prefix '8' -> '89').

    Return None kalau device bukan KANTIN dan prefix PIN tidak cocok
    manapun (Function transaction dibiarkan kosong).
    """
    from django.conf import settings

    if device is not None and device.Function == 'X':
        return 'X'

    device_function = getattr(settings, 'DEVICEFUNCTION', {})
    raw = get_raw_device_pin(raw_pin)
    if not raw:
        return None
    first_char = raw[0]
    for key in device_function:
        if key != 'X' and first_char in key:
            return key
    return None

def consolidate_mobile_attendance_to_iclock(pin: str, timestamp, checktype: str, function_code: str, pool_id) -> None:
    """
    Konsolidasi 1 event check-in/out/meal MOBILE (app mattendance) ke text
    file ATTLOG + tabel `transaction` iclock, dengan SN='ABSENDIGITAL01'
    (device virtual gabungan yang mewakili SEMUA device absen mobile) --
    HANYA kalau device itu SUDAH ada di Active Device (admin yang setup
    manual dari dashboard, TIDAK dibuat otomatis di sini). Kalau belum
    ada, TIDAK melakukan apa pun (silent no-op).

    Args:
        pin: PIN mentah Employee (Employee.PIN, BUKAN username akun).
        timestamp: datetime saat check-in/out/meal ini terjadi.
        checktype: 'IN'/'OUT'/'MEAL' (mattendance.AttendanceLog.CheckType)
            -- di sini di-mapping ke checktype iclock (0=in, 1=out); MEAL
            SENGAJA di-mapping jadi checkout ('1'), sesuai instruksi.
        function_code: kode fungsi BARE (mis. '89'), BUKAN format gabungan
            'kode-poolid' yang dipakai AttendanceLog.Function -- caller
            wajib split dulu (lihat mattendance/services.py).
        pool_id: PoolID (mclock.MobilePool) tempat check-in/out/meal ini
            terjadi -- disimpan ke field `Verify` (BUKAN kode verifikasi
            device biasa 0/1/2 -- field ini di-reuse utk device gabungan
            mobile) & ke `employee.LastVerify`.
    """
    if not iclock.objects.filter(SN='ABSENDIGITAL01').exists():
        return

    ic_checktype = '0' if checktype == 'IN' else '1'  # OUT & MEAL keduanya jadi '1' (checkout)

    from .pushsdk_writer import append_attlog_line
    append_attlog_line('ABSENDIGITAL01', pin, timestamp, ic_checktype, pool_id or '')

    from .tasks import write_mobile_attlog_to_iclock
    write_mobile_attlog_to_iclock.delay(pin, timestamp.isoformat(), ic_checktype, function_code or '', str(pool_id or ''))