"""
Endpoint manajemen Zentyal LDAP (mail server Zentyal 3.4, backend
Courier) -- lihat users & groups, tambah/hapus user dari group.

SKEMA (dikonfirmasi dari export schema `/etc/ldap/slapd.d` milik user,
BUKAN tebakan) -- lihat detail lengkap di config/settings.py bagian
ZENTYAL_*:
  - User: kombinasi `posixAccount` (uid, uidNumber, gidNumber,
    homeDirectory) + `inetOrgPerson` (mail, cn, sn, displayName) +
    `usereboxmail` (mailHomeDirectory) SEMUA di 1 entry LDAP yang sama.
  - Group BIASA: `posixGroup` (gidNumber, memberUid -- member disimpan
    sbg STRING `uid`, BUKAN full DN).
  - Group DISTRIBUSI (mailing list, custom Zentyal): `zentyalDistributionGroup`
    (member disimpan sbg FULL DN, gaya groupOfNames).
  - TIDAK ADA objectClass "zentyalGroup" custom di schema yang dicek --
    jadi group keamanan biasa kemungkinan besar HANYA posixGroup.

KARENA GAYA KEANGGOTAAN GRUP BEDA (memberUid=string uid vs
member=full DN), kode di sini ADAPTIF: baca objectClass grup dulu,
baru tentukan atribut mana yang dipakai -- BUKAN asumsi 1 gaya tetap.
Kalau ternyata ada kombinasi lain di data live Anda yang tidak terduga,
kabari -- gampang disesuaikan.

CATATAN: SSL ke server ini SAAT INI tidak bisa konek (belum diketahui
penyebabnya, ada rencana migrasi LDAP + SSL nanti) -- default konfigurasi
`ZENTYAL_USE_SSL=False` (plain LDAP, port 389 biasa).
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_zentyal_password
from netmgmt.ldap_utils import LDAPManagementClient, LDAPManagementError
from netmgmt.list_utils import paginate_sort_filter, parse_list_params


def _get_zentyal_client() -> LDAPManagementClient:
    if not settings.ZENTYAL_BIND_PASSWORD_ENCRYPTED:
        raise LDAPManagementError(
            'Password bind Zentyal belum diisi (ZENTYAL_BIND_PASSWORD_ENCRYPTED di .env) -- lihat '
            'netmgmt/crypto_utils.py & management command generate_zentyal_key/encrypt_zentyal_password.'
        )
    try:
        password = decrypt_zentyal_password(settings.ZENTYAL_BIND_PASSWORD_ENCRYPTED)
    except NetmgmtCryptoError as exc:
        raise LDAPManagementError(str(exc)) from exc
    return LDAPManagementClient(
        server_uri=settings.ZENTYAL_SERVER_URI,
        bind_dn=settings.ZENTYAL_BIND_DN,
        bind_password=password,
        use_ssl=settings.ZENTYAL_USE_SSL,
        timeout=settings.ZENTYAL_CONNECT_TIMEOUT,
    )


def _attr(entry: dict, name: str, default=''):
    """Sama seperti netmgmt/active_directory_view.py::_attr -- ldap3 selalu bungkus nilai atribut jadi list."""
    value = entry.get(name)
    if not value:
        return default
    if isinstance(value, list):
        return value[0] if value else default
    return value


def _user_to_dict(entry: dict) -> dict:
    return {
        'dn': entry.get('dn', ''),
        'username': _attr(entry, 'uid'),
        'display_name': _attr(entry, 'cn') or _attr(entry, 'displayName'),
        'email': _attr(entry, 'mail'),
        'uid_number': _attr(entry, 'uidNumber'),
        'gid_number': _attr(entry, 'gidNumber'),
        'home_directory': _attr(entry, 'homeDirectory'),
    }


def _group_kind(object_classes: list) -> str:
    """'posix' (memberUid, string uid) atau 'distribution' (member, full DN) -- lihat docstring modul."""
    classes_lower = [str(c).lower() for c in (object_classes or [])]
    if 'zentyaldistributiongroup' in classes_lower:
        return 'distribution'
    return 'posix'  # default -- posixGroup, kasus paling umum di skema yang dicek


def _group_to_dict(entry: dict) -> dict:
    kind = _group_kind(entry.get('objectClass'))
    if kind == 'distribution':
        members = entry.get('member') or []
    else:
        members = entry.get('memberUid') or []
    return {
        'dn': entry.get('dn', ''),
        'name': _attr(entry, 'cn'),
        'description': _attr(entry, 'description'),
        'kind': kind,  # frontend TIDAK PERLU tahu detail ini utk tampil, tapi berguna utk debug
        'member_count': len(members) if isinstance(members, list) else 0,
    }


class ZentyalUserListView(APIView):
    """GET /api/v1/netmgmt/zentyal/users/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields= -- daftar user Zentyal."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            with _get_zentyal_client() as client:
                rows = client.search(
                    settings.ZENTYAL_USER_BASE_DN,
                    '(objectClass=posixAccount)',
                    attributes=['uid', 'cn', 'displayName', 'mail', 'uidNumber', 'gidNumber', 'homeDirectory'],
                )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        users = [_user_to_dict(row) for row in rows]
        params = parse_list_params(request)
        payload = paginate_sort_filter(users, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalGroupListView(APIView):
    """GET /api/v1/netmgmt/zentyal/groups/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields= -- daftar group (posixGroup + zentyalDistributionGroup digabung)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            with _get_zentyal_client() as client:
                rows = client.search(
                    settings.ZENTYAL_GROUP_BASE_DN,
                    '(|(objectClass=posixGroup)(objectClass=zentyalDistributionGroup))',
                    attributes=['cn', 'description', 'memberUid', 'member', 'objectClass'],
                )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        groups = [_group_to_dict(row) for row in rows]
        params = parse_list_params(request)
        payload = paginate_sort_filter(groups, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalGroupMembersView(APIView):
    """GET /api/v1/netmgmt/zentyal/groups/<path:group_dn>/members/ -- daftar user di dalam 1 group."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request, group_dn=None):
        try:
            with _get_zentyal_client() as client:
                group_rows = client.search(
                    group_dn, '(|(objectClass=posixGroup)(objectClass=zentyalDistributionGroup))',
                    attributes=['cn', 'memberUid', 'member', 'objectClass'],
                )
                if not group_rows:
                    return Response({'error': f"Group '{group_dn}' tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

                group_entry = group_rows[0]
                kind = _group_kind(group_entry.get('objectClass'))

                members = []
                if kind == 'distribution':
                    # member = FULL DN -- langsung search per-DN (sama pola dgn Active Directory).
                    for member_dn in (group_entry.get('member') or []):
                        user_rows = client.search(member_dn, '(objectClass=posixAccount)', attributes=['uid', 'cn', 'mail'])
                        if user_rows:
                            members.append(_user_to_dict(user_rows[0]))
                else:
                    # memberUid = STRING uid -- cari user by uid, BUKAN by DN.
                    for uid in (group_entry.get('memberUid') or []):
                        user_rows = client.search(
                            settings.ZENTYAL_USER_BASE_DN,
                            f'(&(objectClass=posixAccount)(uid={LDAPManagementClient.escape(uid)}))',
                            attributes=['uid', 'cn', 'mail'],
                        )
                        if user_rows:
                            members.append(_user_to_dict(user_rows[0]))
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'count': len(members), 'results': members}, status=status.HTTP_200_OK)


class ZentyalGroupMembershipView(APIView):
    """
    POST /api/v1/netmgmt/zentyal/group-membership/
    Body: {"group_dn": "...", "user_uid": "...", "user_dn": "...", "action": "add"|"remove"}

    PENTING: kirim KEDUANYA (`user_uid` DAN `user_dn`) -- endpoint ini
    otomatis pilih salah satu tergantung jenis group (posixGroup pakai
    user_uid, zentyalDistributionGroup pakai user_dn), frontend tidak
    perlu tahu/pilih sendiri jenis groupnya.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        group_dn = request.data.get('group_dn')
        user_uid = request.data.get('user_uid')
        user_dn = request.data.get('user_dn')
        action = request.data.get('action')

        if not group_dn or action not in ('add', 'remove'):
            return Response({'error': "Wajib isi 'group_dn' dan 'action' ('add' atau 'remove')."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_zentyal_client() as client:
                group_rows = client.search(
                    group_dn, '(|(objectClass=posixGroup)(objectClass=zentyalDistributionGroup))',
                    attributes=['objectClass'],
                )
                if not group_rows:
                    return Response({'error': f"Group '{group_dn}' tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
                kind = _group_kind(group_rows[0].get('objectClass'))

                if kind == 'distribution':
                    if not user_dn:
                        return Response({'error': "Group ini gaya 'distribution' -- wajib isi 'user_dn'."}, status=status.HTTP_400_BAD_REQUEST)
                    if action == 'add':
                        client.add_member(group_dn, user_dn)
                    else:
                        client.remove_member(group_dn, user_dn)
                else:
                    if not user_uid:
                        return Response({'error': "Group ini gaya 'posix' -- wajib isi 'user_uid'."}, status=status.HTTP_400_BAD_REQUEST)
                    client.modify_member_uid(group_dn, user_uid, add=(action == 'add'))
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        message = 'User berhasil ditambahkan ke group.' if action == 'add' else 'User berhasil dihapus dari group.'
        return Response({'success': True, 'message': message}, status=status.HTTP_200_OK)
