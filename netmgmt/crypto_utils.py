"""
Enkripsi/dekripsi kredensial khusus fitur netmgmt (Mikrotik sekarang,
kemungkinan Active Directory/Zentyal LDAP nanti bisa dapat modul serupa
dgn nama key masing-masing) -- pakai fondasi generik di
`config/crypto_utils.py`.

BUG YANG DIPERBAIKI (sesi ini): SEBELUMNYA
`netmgmt/management/commands/encrypt_mikrotik_password.py` &
`netmgmt/routeros_api_view.py` import LANGSUNG dari
`mclock.crypto_utils`, yang HARDCODE baca MCLOCK_ENCRYPTION_KEY --
padahal `generate_mikrotik_key` menginstruksikan simpan key sbg
MIKROTIK_ENCRYPTION_KEY (nama BEDA). Key yang baru dibuat itu jadi TIDAK
PERNAH terpakai -- password Mikrotik diam-diam terenkripsi pakai key
MSSQL (kalau MCLOCK_ENCRYPTION_KEY kebetulan sudah terisi) atau gagal
total dgn pesan error yang membingungkan (menyebut MCLOCK padahal user
ikut instruksi MIKROTIK). Sekarang modul INI yang dipakai, dgn nama key
yang BENAR-BENAR sesuai apa yang diinstruksikan `generate_mikrotik_key`.
"""
from config.crypto_utils import CryptoError, decrypt_password as _decrypt, encrypt_password as _encrypt

MIKROTIK_KEY_NAME = 'MIKROTIK_ENCRYPTION_KEY'

NetmgmtCryptoError = CryptoError


def encrypt_mikrotik_password(plain_password: str) -> str:
    """Enkripsi password Mikrotik plaintext -> string base64 siap disimpan di .env sbg MIKROTIK_PASSWORD_ENCRYPTED."""
    return _encrypt(plain_password, MIKROTIK_KEY_NAME)


def decrypt_mikrotik_password(encrypted_password: str) -> str:
    """Dekripsi password Mikrotik (MIKROTIK_PASSWORD_ENCRYPTED) balik jadi plaintext."""
    return _decrypt(encrypted_password, MIKROTIK_KEY_NAME)
