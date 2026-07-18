"""
Utility pemetaan isi QR code -> PoolCode, dipakai fitur Check/Meal.

Mapping-nya di `settings.QRDEVICE`: {'<poolcode>': '<isi qr code>'} --
CATATAN: format dict-nya poolcode->qr (key=poolcode), tapi yang kita PUNYA
saat verifikasi adalah ISI QR (hasil scan), jadi perlu dicari VALUE yang
cocok lalu ambil KEY-nya (reverse lookup).
"""
from django.conf import settings


def get_poolcode_from_qr(qr_content: str):
    """
    Cari PoolCode yang cocok dengan isi QR code yang di-scan, dari
    `settings.QRDEVICE`. Return PoolCode (str) kalau ketemu, None kalau QR
    ini tidak dikenali/tidak terdaftar.
    """
    qr_content = (qr_content or '').strip()
    if not qr_content:
        return None
    qr_map = getattr(settings, 'QRDEVICE', {}) or {}
    for poolcode, registered_qr in qr_map.items():
        if registered_qr == qr_content:
            return poolcode
    return None
