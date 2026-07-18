"""
Utility enkripsi/dekripsi password MSSQL untuk fitur Mobile Attendance,
pakai `cryptography.fernet.Fernet` (symmetric encryption, standar & aman
utk kebutuhan "simpan password terenkripsi, dekripsi cuma saat runtime").

Alur pemakaian:
1. Generate KEY sekali (simpan di .env sebagai MCLOCK_ENCRYPTION_KEY):
       python manage.py generate_mclock_key
2. Enkripsi password MSSQL Anda pakai key itu:
       python manage.py encrypt_mssql_password
   -> hasilnya (string base64) disimpan di .env sebagai
      MCLOCK_MSSQL_PASSWORD_ENCRYPTED.
3. Saat runtime, `decrypt_password()` dipanggil HANYA pas benar-benar mau
   konek ke MSSQL (lihat mclock/mssql_client.py) -- password plaintext
   TIDAK PERNAH disimpan di database/file/log mana pun, cuma ada sesaat di
   memori selama proses koneksi berlangsung.

PENTING: kalau MCLOCK_ENCRYPTION_KEY berubah/hilang, password yang sudah
terenkripsi dengan key LAMA tidak akan bisa didekripsi lagi -- perlu
enkripsi ulang passwordnya pakai key yang baru.
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class MclockCryptoError(Exception):
    """Gagal enkripsi/dekripsi -- biasanya karena MCLOCK_ENCRYPTION_KEY belum diisi atau salah."""


def _get_fernet() -> Fernet:
    key = getattr(settings, 'MCLOCK_ENCRYPTION_KEY', '') or ''
    if not key:
        raise MclockCryptoError(
            "MCLOCK_ENCRYPTION_KEY belum diisi di .env/settings.py. Generate dulu lewat: "
            "python manage.py generate_mclock_key"
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001
        raise MclockCryptoError(f'MCLOCK_ENCRYPTION_KEY tidak valid (harus key Fernet base64): {exc}') from exc


def encrypt_password(plain_password: str) -> str:
    """Enkripsi password plaintext -> string base64 siap disimpan di .env/settings."""
    fernet = _get_fernet()
    return fernet.encrypt(plain_password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    """Dekripsi password (string base64 hasil encrypt_password()) balik jadi plaintext."""
    if not encrypted_password:
        return ''
    fernet = _get_fernet()
    try:
        return fernet.decrypt(encrypted_password.encode()).decode()
    except InvalidToken as exc:
        raise MclockCryptoError(
            'Gagal dekripsi password MSSQL -- kemungkinan MCLOCK_ENCRYPTION_KEY tidak cocok dengan '
            'key yang dipakai saat enkripsi, atau MCLOCK_MSSQL_PASSWORD_ENCRYPTED korup/salah copy.'
        ) from exc
