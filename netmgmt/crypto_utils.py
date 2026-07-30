"""
Enkripsi/dekripsi kredensial khusus fitur netmgmt (Mikrotik, Active
Directory, Zentyal LDAP -- masing2 key TERPISAH) -- pakai fondasi
generik di `config/crypto_utils.py`.
"""
from config.crypto_utils import CryptoError, decrypt_password as _decrypt, encrypt_password as _encrypt

MIKROTIK_KEY_NAME = 'MIKROTIK_ENCRYPTION_KEY'
AD_KEY_NAME = 'AD_ENCRYPTION_KEY'
ZENTYAL_KEY_NAME = 'ZENTYAL_ENCRYPTION_KEY'
ZENTYAL_MAIL_KEY_NAME = 'ZENTYAL_MAIL_ENCRYPTION_KEY'
VMWARE_KEY_NAME = 'VMWARE_ENCRYPTION_KEY'

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


def encrypt_zentyal_mail_token(plain_token: str) -> str:
    """Token API Flask (test/zentyalmail_v2.py) -- BEDA dari password bind LDAP di atas, protokolnya HTTP+JSON biasa, bukan LDAP."""
    return _encrypt(plain_token, ZENTYAL_MAIL_KEY_NAME)


def decrypt_zentyal_mail_token(encrypted_token: str) -> str:
    return _decrypt(encrypted_token, ZENTYAL_MAIL_KEY_NAME)


def encrypt_vmware_password(plain_password: str) -> str:
    """Password vCenter (SOAP API via pyVmomi, lihat netmgmt/vmware_view.py) -- key TERPISAH dari kredensial netmgmt lain."""
    return _encrypt(plain_password, VMWARE_KEY_NAME)


def decrypt_vmware_password(encrypted_password: str) -> str:
    return _decrypt(encrypted_password, VMWARE_KEY_NAME)
