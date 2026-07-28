"""
Enkripsi/dekripsi kredensial khusus fitur netmgmt (Mikrotik, Active
Directory, Zentyal LDAP -- masing2 key TERPISAH) -- pakai fondasi
generik di `config/crypto_utils.py`.
"""
from config.crypto_utils import CryptoError, decrypt_password as _decrypt, encrypt_password as _encrypt

MIKROTIK_KEY_NAME = 'MIKROTIK_ENCRYPTION_KEY'
AD_KEY_NAME = 'AD_ENCRYPTION_KEY'
ZENTYAL_KEY_NAME = 'ZENTYAL_ENCRYPTION_KEY'

NetmgmtCryptoError = CryptoError


def encrypt_mikrotik_password(plain_password: str) -> str:
    return _encrypt(plain_password, MIKROTIK_KEY_NAME)


def decrypt_mikrotik_password(encrypted_password: str) -> str:
    return _decrypt(encrypted_password, MIKROTIK_KEY_NAME)


def encrypt_ad_password(plain_password: str) -> str:
    return _encrypt(plain_password, AD_KEY_NAME)


def decrypt_ad_password(encrypted_password: str) -> str:
    return _decrypt(encrypted_password, AD_KEY_NAME)


def encrypt_zentyal_password(plain_password: str) -> str:
    return _encrypt(plain_password, ZENTYAL_KEY_NAME)


def decrypt_zentyal_password(encrypted_password: str) -> str:
    return _decrypt(encrypted_password, ZENTYAL_KEY_NAME)
