"""
Wrapper TIPIS, backward-compatible -- logic enkripsi SEBENARNYA sekarang
ada di `config/crypto_utils.py` (generik, dipakai bersama netmgmt jg).
Modul ini TETAP ADA & signature-nya TIDAK BERUBAH supaya call site yang
sudah ada (mclock/mssql_client.py, mclock/management/commands/
encrypt_mssql_password.py) JALAN TANPA PERLU DIUBAH SAMA SEKALI.

Riwayat: dulu modul INI yang berisi logic-nya langsung (hardcode baca
MCLOCK_ENCRYPTION_KEY). Sekarang cuma manggil versi generik dgn nama key
'MCLOCK_ENCRYPTION_KEY' dikunci di sini -- perilaku observable-nya 100%
SAMA PERSIS spt sebelumnya utk kode yang sudah pakai modul ini.
"""
from config.crypto_utils import CryptoError, decrypt_password as _decrypt, encrypt_password as _encrypt

MCLOCK_KEY_NAME = 'MCLOCK_ENCRYPTION_KEY'

# Nama lama dipertahankan (alias) -- kode yang sudah ada import
# `MclockCryptoError`, JANGAN diubah namanya di sini.
MclockCryptoError = CryptoError


def encrypt_password(plain_password: str) -> str:
    """Enkripsi password plaintext -> string base64 siap disimpan di .env/settings."""
    return _encrypt(plain_password, MCLOCK_KEY_NAME)


def decrypt_password(encrypted_password: str) -> str:
    """Dekripsi password (string base64 hasil encrypt_password()) balik jadi plaintext."""
    return _decrypt(encrypted_password, MCLOCK_KEY_NAME)
