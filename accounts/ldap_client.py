"""
Wrapper tipis di atas ldap3.

Prinsip penting: kita HARUS bisa membedakan 3 kondisi berbeda supaya logic
di services.authenticate_user() bisa mengikuti spesifikasi:

1. Koneksi LDAP OK, user ADA, password BENAR      -> sukses
2. Koneksi LDAP OK, user TIDAK ADA                -> "user belum ada"
3. Koneksi LDAP OK, user ADA, password SALAH      -> invalid credentials
4. Koneksi LDAP ERROR (server down/timeout/dll)   -> fallback ke user lokal

Karena itu semua kegagalan koneksi/socket dilempar sebagai
LDAPConnectivityError, sedangkan "salah password" (invalidCredentials,
result code 49) dikembalikan sebagai False biasa, BUKAN exception.
"""
import logging

from django.conf import settings
from ldap3 import Connection, Server, SUBTREE
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSocketOpenError
from ldap3.utils.conv import escape_filter_chars

logger = logging.getLogger('accounts')

LDAP_INVALID_CREDENTIALS_RESULT_CODE = 49


class LDAPConnectivityError(Exception):
    """Server LDAP tidak bisa dihubungi / search-bind gagal karena masalah jaringan/konfigurasi."""


class LDAPClient:
    def __init__(self):
        self.server_uri = settings.AUTH_LDAP_SERVER_URI
        self.bind_dn = settings.AUTH_LDAP_BIND_DN
        self.bind_password = settings.AUTH_LDAP_BIND_PASSWORD
        self.base_dn = settings.AUTH_LDAP_BASE_DN
        self.search_filter_tpl = settings.AUTH_LDAP_USER_SEARCH_FILTER
        self.attr_map = settings.AUTH_LDAP_USER_ATTR_MAP
        self.timeout = settings.AUTH_LDAP_CONNECT_TIMEOUT
        self.use_ssl = settings.AUTH_LDAP_USE_SSL

    def _server(self) -> Server:
        return Server(self.server_uri, use_ssl=self.use_ssl, get_info=None, connect_timeout=self.timeout)

    def find_user(self, username: str):
        """
        Cari user di direktori LDAP memakai service/bind account.

        Return:
            (user_dn, entry) jika ketemu
            None             jika koneksi OK tapi user tidak ditemukan
        Raise:
            LDAPConnectivityError jika ada masalah koneksi/bind service account.
        """
        try:
            server = self._server()
            conn = Connection(
                server,
                user=self.bind_dn or None,
                password=self.bind_password or None,
                auto_bind=True,
                receive_timeout=self.timeout,
            )
        except LDAPException as exc:
            raise LDAPConnectivityError(f'Gagal bind service account ke LDAP: {exc}') from exc

        try:
            safe_username = escape_filter_chars(username)
            search_filter = self.search_filter_tpl.format(username=safe_username)
            attributes = list(set(self.attr_map.values())) or ['*']
            ok = conn.search(self.base_dn, search_filter, SUBTREE, attributes=attributes)
            if not ok or not conn.entries:
                return None
            entry = conn.entries[0]
            return entry.entry_dn, entry
        except LDAPException as exc:
            raise LDAPConnectivityError(f'LDAP search gagal: {exc}') from exc
        finally:
            try:
                conn.unbind()
            except Exception:  # noqa: BLE001
                pass

    def authenticate(self, user_dn: str, password: str) -> bool:
        """
        Coba bind sebagai user_dn dengan password yang diberikan.

        Return True/False untuk hasil bind (kredensial benar/salah).
        Raise LDAPConnectivityError kalau kegagalan disebabkan masalah koneksi,
        bukan kredensial salah.
        """
        if not password:
            return False
        try:
            server = self._server()
            conn = Connection(server, user=user_dn, password=password, receive_timeout=self.timeout)
        except LDAPException as exc:
            raise LDAPConnectivityError(f'Gagal menyiapkan koneksi bind user: {exc}') from exc

        try:
            bound = conn.bind()
        except LDAPBindError:
            return False
        except LDAPSocketOpenError as exc:
            raise LDAPConnectivityError(f'Socket LDAP error: {exc}') from exc
        except LDAPException as exc:
            raise LDAPConnectivityError(f'LDAP bind error: {exc}') from exc

        if not bound:
            result = conn.result or {}
            if result.get('result') == LDAP_INVALID_CREDENTIALS_RESULT_CODE:
                return False
            raise LDAPConnectivityError(f'LDAP bind ditolak: {result}')

        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass
        return True
