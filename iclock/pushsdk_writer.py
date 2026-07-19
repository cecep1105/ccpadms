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


def append_attlog_line(sn: str, pin: str, timestamp: datetime, check_type: str) -> tuple[Path, bool]:
    """
    Tulis 1 baris ATTLOG ke text file harian -- format PERSIS sama dgn
    test/062026.zip (sudah tervalidasi end-to-end lewat push_sdk.py
    emulator sebelumnya): 'SN,PIN,DD/MM/YYYY HH:MM,checktype'.

    Return (path_file_yg_ditulis, pin_valid) -- `pin_valid` dipakai caller
    (endpoint cdata) utk memutuskan apakah data ini boleh dilempar ke
    Celery task tulis-DB juga, atau CUKUP dicatat ke file '_other' saja
    (Rule 3 + Rule 4).
    """
    pin_valid = is_valid_device_pin(pin)
    path = _log_file_path('masterattlog', pin_valid, timestamp)
    line = f"{sn},{pin},{timestamp.strftime('%d/%m/%Y %H:%M')},{check_type}\n"
    _append_line_locked(path, line)
    return path, pin_valid