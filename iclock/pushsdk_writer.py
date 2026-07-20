"""
Penulisan text-file 'write-ahead' untuk data push protocol (attendance log
dulu -- operation log/fingerprint template menyusul), SEBELUM ditulis ke
database. Lihat test/myrule.md Rule 4 ('DB Write Policy').

Alur: device upload data -> tulis text file dulu (durability/source-of-
truth, format PERSIS sama dgn test/062026.zip yang sudah divalidasi lewat
push_sdk.py emulator) -> caller (endpoint /iclock/cdata, dibangun tahap
berikutnya) baru lempar Celery task utk proses tulis ke database, KECUALI
kalau PIN tidak valid (Rule 3) -- tetap dicatat ke text file (folder
'_other'), TAPI TIDAK pernah dilempar ke Celery / TIDAK ditulis ke database
sama sekali.

Referensi pola (test/iclockutils.py::addtostream, BUKAN ditiru mentah --
disederhanakan & dibuat OS-aware pakai pathlib + portalocker utk locking
lintas platform, krn banyak device bisa menulis ke file HARIAN yang SAMA
secara bersamaan).
"""
from datetime import datetime
from pathlib import Path

import portalocker
from django.conf import settings

from .services import is_valid_device_pin


def _log_file_path(log_type: str, pin_valid: bool, timestamp: datetime) -> Path:
    """
    Path file log harian: {PUSHSDK_BASE_DIR}/{log_type}[_other]/{MMYYYY}/{DD}.txt
    (Rule 4). `pathlib.Path` dipakai supaya path OTOMATIS OS-aware
    (backslash di Windows, forward-slash di Unix) tanpa logic terpisah.
    """
    folder_name = log_type if pin_valid else f'{log_type}_other'
    base_dir = Path(getattr(settings, 'PUSHSDK_BASE_DIR', settings.BASE_DIR / 'data'))
    mmyyyy = timestamp.strftime('%m%Y')
    dd = timestamp.strftime('%d')
    return base_dir / folder_name / mmyyyy / f'{dd}.txt'


def _append_line_locked(path: Path, line: str) -> None:
    """
    Tulis 1 baris ke `path`, dgn EXCLUSIVE LOCK selama penulisan -- banyak
    device (thread/proses berbeda) bisa menulis ke file HARIAN yang SAMA
    secara bersamaan (semua device dari pool yang sama, di hari yang sama),
    tanpa lock ini baris antar device bisa saling menimpa/ke-interleave
    (terutama di Windows, yang TIDAK punya jaminan atomic append POSIX).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(path), mode='a', encoding='utf-8', timeout=10) as f:
        f.write(line)


def append_attlog_line(sn: str, pin: str, timestamp: datetime, check_type: str, verify) -> tuple[Path, bool]:
    """
    Tulis 1 baris ATTLOG ke text file harian -- format:
    'SN,PIN,DD/MM/YYYY HH:MM,checktype,verify' (5 kolom -- SEBELUMNYA cuma
    4 kolom/tanpa verify, format LAMA sama persis dgn test/062026.zip).

    `verify` -- utk device mesin finger biasa, ini field VERIFY protokol
    asli (1 digit: 0=password/1=fingerprint/2=card/9=lainnya, lihat resume
    protokol §4.1). Field ini SEKARANG JUGA dipakai utk skema konsolidasi
    device absen mobile (SN gabungan tunggal, mis. 'ABSENDIGITAL01') --
    utk kasus itu `verify` diisi PoolID mobile (3 digit) alih-alih kode
    verifikasi biasa, supaya asal pool-nya tetap bisa dibedakan walau SN
    device-nya sama. Penulisan text file ini SENDIRI TIDAK membedakan
    kedua kasus (cuma nulis apa pun `verify` yang diberikan caller) --
    logic BEDA-nya ada di endpoint pemanggil (pushsdk_views.py) & proses
    import mobile->iclock (masih tahap rencana, belum diimplementasikan).

    Return (path_file_yg_ditulis, pin_valid) -- `pin_valid` dipakai caller
    (endpoint cdata) utk memutuskan apakah data ini boleh dilempar ke
    Celery task tulis-DB juga, atau CUKUP dicatat ke file '_other' saja
    (Rule 3 + Rule 4).
    """
    pin_valid = is_valid_device_pin(pin)
    path = _log_file_path('masterattlog', pin_valid, timestamp)
    line = f"{sn},{pin},{timestamp.strftime('%d/%m/%Y %H:%M')},{check_type},{verify}\n"
    _append_line_locked(path, line)
    return path, pin_valid


# ---------------------------------------------------------------------------
# OPLOG & FPLOG -- BELUM ada implementasi/sample konkret dari Anda (beda dgn
# ATTLOG yang sudah tervalidasi lewat test/062026.zip), jadi formatnya saya
# rancang MIRIP ATTLOG (CSV sederhana per baris) sesuai arahan Anda, TAPI
# TETAP menyimpan payload MENTAH (tab-separated, format asli protokol PUSH
# SDK -- lihat resume protokol §4.2) sbg kolom terakhir. Alasan: OPERLOG
# device punya 2 BENTUK berbeda ('USER ...' info karyawan, 'OPLOG ...' log
# aksi admin) yang field-nya beda total -- daripada memaksa 1 struktur CSV
# kaku yang berisiko kehilangan informasi, payload asli disimpan APA
# ADANYA supaya task Celery (tahap berikutnya) bisa parse persis sesuai
# kebutuhan msg-masing tipe, MIRIP `lineToUser()`/`lineToOpLog()` di
# test/devview.py Anda -- cuma parsing-nya dipindah ke tahap Celery, bukan
# di sini (di sini cuma soal PENYIMPANAN text file dulu).
# ---------------------------------------------------------------------------
def _extract_pin_from_operlog_fields(tag: str, fields: str) -> str:
    """
    Ambil nilai PIN dari payload 'USER PIN=982\\tName=...' atau
    'FP PIN=982\\tFID=...' (format `Key=Value` dipisah tab, lihat resume
    protokol §4.2). Return '' kalau tidak ketemu (mis. tag 'OPLOG' yang
    memang tidak selalu punya field PIN -- lihat catatan di
    `append_oplog_line`).
    """
    for item in fields.split('\t'):
        if item.startswith('PIN='):
            return item[len('PIN='):]
    return ''


def append_oplog_line(sn: str, tag: str, fields: str, timestamp: datetime) -> tuple[Path, bool]:
    """
    Tulis 1 baris OPERLOG (sub-tipe 'USER' info karyawan ATAU 'OPLOG' log
    aksi admin) ke text file harian -- format: 'SN,Tag,PIN,ReceivedAt,RawFields'.

    - `tag`: 'USER' atau 'OPLOG' (dari line device, lihat resume protokol §4.2).
    - `fields`: payload tab-separated APA ADANYA (bukan 'USER '/'OPLOG '
      lagi, tag-nya sudah dipisah) -- disimpan mentah, BUKAN diparsing
      penuh di sini.

    Validasi PIN (Rule 3) HANYA relevan utk tag 'USER' (punya field PIN=
    yang jelas). Tag 'OPLOG' (log aksi admin: power on/off, alarm, ubah
    config, dst) TIDAK selalu terkait 1 PIN karyawan spesifik -- SENGAJA
    selalu dianggap valid (tidak pernah masuk folder '_other'), karena
    Rule 3 secara semantik soal validasi PIN KARYAWAN, bukan data admin.
    """
    if tag == 'USER':
        pin = _extract_pin_from_operlog_fields(tag, fields)
        pin_valid = is_valid_device_pin(pin)
    else:  # 'OPLOG' (atau tag tak dikenal lainnya) -- tidak ada konsep PIN yang applicable
        pin = ''
        pin_valid = True

    path = _log_file_path('masteroplog', pin_valid, timestamp)
    line = f"{sn},{tag},{pin},{timestamp.strftime('%d/%m/%Y %H:%M:%S')},{fields}\n"
    _append_line_locked(path, line)
    return path, pin_valid


def append_fplog_line(sn: str, fields: str, timestamp: datetime) -> tuple[Path, bool]:
    """
    Tulis 1 baris FP (template fingerprint/face) ke text file harian --
    format: 'SN,PIN,FID,ReceivedAt,RawFields' (RawFields tetap menyimpan
    'Valid=...\\tTMP=...' mentah, termasuk template base64-nya, supaya
    task Celery nanti bisa langsung pakai tanpa perlu tulis ulang ke text
    file lain).

    `fields` adalah payload SETELAH tag 'FP ' dibuang, mis.
    'PIN=982\\tFID=1\\tValid=1\\tTMP=ocoRgZ...'.
    """
    pin = _extract_pin_from_operlog_fields('FP', fields)
    fid = ''
    for item in fields.split('\t'):
        if item.startswith('FID='):
            fid = item[len('FID='):]
            break

    pin_valid = is_valid_device_pin(pin)
    path = _log_file_path('masterfplog', pin_valid, timestamp)
    line = f"{sn},{pin},{fid},{timestamp.strftime('%d/%m/%Y %H:%M:%S')},{fields}\n"
    _append_line_locked(path, line)
    return path, pin_valid