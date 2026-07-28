"""
Wrapper generik di atas ldap3, KHUSUS operasi MANAJEMEN (search users/
groups, ubah member group) -- BEDA dari `accounts/ldap_client.py` (itu
KHUSUS autentikasi login staff, pola "bind sbg service account -> cari
user -> coba bind SEBAGAI user itu utk verifikasi password").

Client di sini BIND SEKALI sbg service account (butuh privilege BACA +
TULIS di direktori -- utk AD biasanya account khusus, BUKAN account
pribadi admin), dipakai utk operasi ADMIN: lihat semua user/group, ubah
keanggotaan group. Dipakai BERSAMA oleh netmgmt/active_directory_view.py
& (nanti) netmgmt/zentyal_view.py -- constructor terima SEMUA parameter
koneksi eksplisit (server_uri, bind_dn, dst), TIDAK baca `settings`
langsung di sini, supaya modul ini tetap independen dari SIAPA
pemanggilnya (AD atau Zentyal, connection settings beda sumbernya).
"""
import logging

from ldap3 import ALL_ATTRIBUTES, MODIFY_ADD, MODIFY_DELETE, MODIFY_REPLACE, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

logger = logging.getLogger('netmgmt')


class LDAPManagementError(Exception):
    """Gagal terhubung/search/modify ke direktori LDAP (AD atau Zentyal)."""


class LDAPManagementClient:
    def __init__(self, *, server_uri: str, bind_dn: str, bind_password: str, use_ssl: bool = False, timeout: int = 5):
        if not server_uri or not bind_dn or not bind_password:
            raise LDAPManagementError(
                'Konfigurasi LDAP belum lengkap (server URI / bind DN / bind password service account).'
            )
        self.server_uri = server_uri
        self.bind_dn = bind_dn
        self.bind_password = bind_password
        self.use_ssl = use_ssl
        self.timeout = timeout
        self._connection: Connection | None = None

    def __enter__(self) -> 'LDAPManagementClient':
        try:
            server = Server(self.server_uri, use_ssl=self.use_ssl, get_info=None, connect_timeout=self.timeout)
            self._connection = Connection(
                server, user=self.bind_dn, password=self.bind_password,
                auto_bind=True, receive_timeout=self.timeout,
            )
        except LDAPException as exc:
            raise LDAPManagementError(f'Gagal bind service account ke direktori LDAP: {exc}') from exc
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._connection:
            try:
                self._connection.unbind()
            except Exception:  # noqa: BLE001
                pass

    def search(self, base_dn: str, search_filter: str, attributes: list[str] | None = None) -> list[dict]:
        """
        Cari entri LDAP, kembalikan list of dict {dn, **attributes} --
        pakai paged_search (bukan search biasa) supaya direktori BESAR
        (AD ribuan+ user) tidak kena limit result server LDAP (biasanya
        1000-3000 entri per request, tergantung konfigurasi server).
        """
        if not self._connection:
            raise LDAPManagementError('Koneksi belum dibuka -- pakai dgn `with LDAPManagementClient(...) as client:`.')
        try:
            entries = []
            for entry in self._connection.extend.standard.paged_search(
                search_base=base_dn,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=attributes or ALL_ATTRIBUTES,
                paged_size=500,
                generator=True,
            ):
                if entry.get('type') != 'searchResEntry':
                    continue  # lewati referral/dst, cuma ambil entri sungguhan
                attrs = dict(entry.get('attributes', {}))
                attrs['dn'] = entry.get('dn')
                entries.append(attrs)
            return entries
        except LDAPException as exc:
            raise LDAPManagementError(f'Pencarian LDAP gagal: {exc}') from exc

    def add_member(self, group_dn: str, member_dn: str) -> None:
        """Tambah 1 DN (user) ke atribut `member` sebuah group (skema AD/groupOfNames -- lihat catatan Zentyal kalau skemanya beda)."""
        self._modify_member(group_dn, member_dn, MODIFY_ADD)

    def remove_member(self, group_dn: str, member_dn: str) -> None:
        """Hapus 1 DN (user) dari atribut `member` sebuah group."""
        self._modify_member(group_dn, member_dn, MODIFY_DELETE)

    def modify_member_uid(self, group_dn: str, uid: str, *, add: bool) -> None:
        """
        Tambah/hapus 1 UID (string, BUKAN DN) ke/dari atribut `memberUid`
        sebuah group -- skema POSIX klasik (rfc2307/posixGroup), dipakai
        Zentyal LDAP (lihat netmgmt/zentyal_view.py) -- BEDA dari
        add_member()/remove_member() di atas yang urus atribut `member`
        (isinya FULL DN, dipakai AD/groupOfNames).
        """
        if not self._connection:
            raise LDAPManagementError('Koneksi belum dibuka -- pakai dgn `with LDAPManagementClient(...) as client:`.')
        operation = MODIFY_ADD if add else MODIFY_DELETE
        try:
            ok = self._connection.modify(group_dn, {'memberUid': [(operation, [uid])]})
            if not ok:
                raise LDAPManagementError(f'Modify group (memberUid) gagal: {self._connection.result}')
        except LDAPException as exc:
            raise LDAPManagementError(f'Modify group (memberUid) gagal: {exc}') from exc

    def set_password(self, user_dn: str, new_password: str, *, use_ad_method: bool = False) -> None:
        """
        Reset password user -- 2 METODE BEDA tergantung server:

        - AD (`use_ad_method=True`): AD TIDAK PAKAI userPassword biasa --
          WAJIB set atribut `unicodePwd` dgn format KHUSUS (UTF-16-LE,
          nilai dibungkus tanda kutip: '"password"'.encode('utf-16-le')).
          Microsoft AD JUGA MEWAJIBKAN koneksi terenkripsi (LDAPS/StartTLS)
          utk operasi ini -- AD akan MENOLAK modify ini di koneksi plain
          LDAP (bukan batasan kode ini, tapi batasan AD SENDIRI demi
          keamanan, tidak bisa di-workaround dari sisi client).
        - OpenLDAP/Zentyal (`use_ad_method=False`): pakai LDAP Password
          Modify Extended Operation (RFC 3062) -- server yang urus hashing
          (biasanya jadi SSHA), client cuma kirim plaintext lewat operasi
          KHUSUS ini (BEDA dari modify() atribut biasa).
        """
        if not self._connection:
            raise LDAPManagementError('Koneksi belum dibuka -- pakai dgn `with LDAPManagementClient(...) as client:`.')
        try:
            if use_ad_method:
                encoded_pwd = f'"{new_password}"'.encode('utf-16-le')
                ok = self._connection.modify(user_dn, {'unicodePwd': [(MODIFY_REPLACE, [encoded_pwd])]})
                if not ok:
                    raise LDAPManagementError(
                        f'Reset password AD gagal: {self._connection.result} -- PALING SERING krn koneksi '
                        'BUKAN LDAPS/StartTLS (AD mewajibkan enkripsi utk operasi ini, cek AD_USE_SSL di .env).'
                    )
            else:
                self._connection.extend.standard.modify_password(user_dn, new_password=new_password)
        except LDAPException as exc:
            raise LDAPManagementError(f'Reset password gagal: {exc}') from exc

    def _modify_member(self, group_dn: str, member_dn: str, operation) -> None:
        if not self._connection:
            raise LDAPManagementError('Koneksi belum dibuka -- pakai dgn `with LDAPManagementClient(...) as client:`.')
        try:
            ok = self._connection.modify(group_dn, {'member': [(operation, [member_dn])]})
            if not ok:
                raise LDAPManagementError(f'Modify group gagal: {self._connection.result}')
        except LDAPException as exc:
            raise LDAPManagementError(f'Modify group gagal: {exc}') from exc

    @staticmethod
    def escape(value: str) -> str:
        """Escape karakter spesial LDAP filter (mis. dari input pencarian user) -- WAJIB dipakai tiap kali nilai dari user masuk ke search_filter, cegah LDAP injection."""
        return escape_filter_chars(value)
