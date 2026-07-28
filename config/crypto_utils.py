"""
Utility enkripsi/dekripsi password GENERIK, dipakai fitur MANAPUN yang
perlu simpan kredensial terenkripsi di .env/settings (MSSQL mclock,
Mikrotik netmgmt, Active Directory, Zentyal LDAP, dst) -- pakai
`cryptography.fernet.Fernet` (symmetric encryption).

Modul ini PARAMETERIZED (nama settings key dikirim sbg argumen), supaya
SETIAP fitur bisa punya key ENKRIPSI SENDIRI (praktik keamanan yang baik
-- kompromi 1 key tidak otomatis bongkar kredensial fitur lain). Fitur
existing (mclock) TETAP JALAN TANPA PERUBAHAN lewat wrapper tipis di
`mclock/crypto_utils.py` (backward-compatible, tidak perlu ubah call
site yang sudah ada) -- fitur BARU (netmgmt Mikrotik/AD/Zentyal) pakai
modul ini langsung dgn nama key masing-masing.

Alur pemakaian (generik, GANTI <NAMA> sesuai fitur):
1. Generate key sekali, simpan di .env sbg <NAMA>_ENCRYPTION_KEY.
2. Enkripsi password pakai key itu -> hasilnya (string base64) disimpan
   di .env sbg <NAMA>_PASSWORD_ENCRYPTED.
3. Saat runtime, decrypt_password() dipanggil HANYA pas benar-benar mau
   konek -- password plaintext TIDAK PERNAH disimpan di database/file/log
   mana pun, cuma ada sesaat di memori selama proses koneksi berlangsung.

PENTING: kalau <NAMA>_ENCRYPTION_KEY berubah/hilang, password yang sudah
terenkripsi dgn key LAMA tidak akan bisa didekripsi lagi -- perlu enkripsi
ulang passwordnya pakai key yang baru.
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class CryptoError(Exception):
    """Gagal enkripsi/dekripsi -- biasanya krn settings key encryption belum diisi/salah."""


def _get_fernet(settings_key_name: str) -> Fernet:
    key = getattr(settings, settings_key_name, '') or ''
    if not key:
        raise CryptoError(
            f"{settings_key_name} belum diisi di .env/settings.py. Generate dulu key barunya "
            "(lihat management command generate_<fitur>_key yang sesuai)."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001
        raise CryptoError(f'{settings_key_name} tidak valid (harus key Fernet base64): {exc}') from exc


def encrypt_password(plain_password: str, settings_key_name: str) -> str:
    """Enkripsi password plaintext -> string base64 siap disimpan di .env/settings."""
    fernet = _get_fernet(settings_key_name)
    return fernet.encrypt(plain_password.encode()).decode()


def decrypt_password(encrypted_password: str, settings_key_name: str) -> str:
    """Dekripsi password (string base64 hasil encrypt_password()) balik jadi plaintext."""
    if not encrypted_password:
        return ''
    fernet = _get_fernet(settings_key_name)
    try:
        return fernet.decrypt(encrypted_password.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError(
            f'Gagal dekripsi password -- kemungkinan {settings_key_name} tidak cocok dengan key '
            'yang dipakai saat enkripsi, atau nilai *_PASSWORD_ENCRYPTED korup/salah copy.'
        ) from exc
