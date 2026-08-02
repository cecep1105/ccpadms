"""
Endpoint manajemen Zentyal LDAP (mail server Zentyal 3.4, backend
Courier) -- lihat users & groups, tambah/hapus user dari group, reset
password.

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
`ZENTYAL_USE_SSL=False` (plain LDAP, port 389 biasa). BEDA dari AD, reset
password OpenLDAP (lihat ZentyalResetPasswordView di bawah) TIDAK
MEWAJIBKAN SSL scr protokol (walau tetap disarankan demi keamanan) --
LDAP Password Modify Extended Operation bisa jalan di koneksi plain.
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission, IsStaffRole
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
    # Zentyal/POSIX TIDAK PUNYA bit "account disabled" spt AD
    # (userAccountControl) -- konvensi Unix/LDAP standar (SAMA dgn
    # `passwd -l`) yg dipakai di sini: prefix '!' di depan hash
    # `userPassword` bikin autentikasi (LDAP bind/IMAP/SMTP auth) GAGAL
    # tanpa mengubah hash aslinya -- REVERSIBLE (lepas prefix utk
    # enable lagi), lihat ZentyalUserToggleStatusView. userPassword
    # KADANG tidak terbaca (tergantung ACL server) -- kalau begitu,
    # ASUMSIKAN aktif (fail-open utk TAMPILAN saja, BUKAN keamanan --
    # data sesungguhnya tetap di server, ini cuma soal apa yg
    # ditampilkan kalau atributnya memang tidak bisa dibaca).
    user_password = _attr(entry, 'userPassword', '')
    is_enabled = not str(user_password).startswith('!')
    return {
        'dn': entry.get('dn', ''),
        'username': _attr(entry, 'uid'),
        'display_name': _attr(entry, 'cn') or _attr(entry, 'displayName'),
        'email': _attr(entry, 'mail'),
        'uid_number': _attr(entry, 'uidNumber'),
        'gid_number': _attr(entry, 'gidNumber'),
        'home_directory': _attr(entry, 'homeDirectory'),
        'is_enabled': is_enabled,
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
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_zentyal_users')]

    def get(self, request):
        try:
            with _get_zentyal_client() as client:
                rows = client.search(
                    settings.ZENTYAL_USER_BASE_DN,
                    '(objectClass=posixAccount)',
                    attributes=['uid', 'cn', 'displayName', 'mail', 'uidNumber', 'gidNumber', 'homeDirectory', 'userPassword'],
                )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        users = [_user_to_dict(row) for row in rows]
        params = parse_list_params(request)
        payload = paginate_sort_filter(users, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalGroupListView(APIView):
    """GET /api/v1/netmgmt/zentyal/groups/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields= -- daftar group (posixGroup + zentyalDistributionGroup digabung)."""
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_zentyal_groups')]

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
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_zentyal_groups')]

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
                    for member_dn in (group_entry.get('member') or []):
                        user_rows = client.search(member_dn, '(objectClass=posixAccount)', attributes=['uid', 'cn', 'mail'])
                        if user_rows:
                            members.append(_user_to_dict(user_rows[0]))
                else:
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


class ZentyalResetPasswordView(APIView):
    """
    POST /api/v1/netmgmt/zentyal/reset-password/
    Body: {"user_dn": "...", "new_password": "..."}

    Pakai LDAP Password Modify Extended Operation (RFC 3062) -- server
    OpenLDAP yang urus hashing (mis. jadi SSHA), TIDAK MEWAJIBKAN SSL scr
    protokol (beda dari AD yang wajib LDAPS/StartTLS utk unicodePwd) --
    tapi TETAP disarankan pakai koneksi terenkripsi demi keamanan kalau
    servernya mendukung (lihat rencana migrasi LDAP Anda).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_zentyal_users')]

    def post(self, request):
        user_dn = request.data.get('user_dn')
        new_password = request.data.get('new_password')

        if not user_dn or not new_password:
            return Response({'error': "Wajib isi 'user_dn' dan 'new_password'."}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 8:
            return Response({'error': 'Password baru minimal 8 karakter.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_zentyal_client() as client:
                client.set_password(user_dn, new_password, use_ad_method=False)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'Password berhasil direset.'}, status=status.HTTP_200_OK)


def _next_available_number(client: LDAPManagementClient, base_dn: str, object_class: str, attribute: str, start_from: int) -> int:
    """
    Cari nilai INTEGER berikutnya yang belum dipakai utk atribut numerik
    (uidNumber/gidNumber) -- LDAP TIDAK PUNYA auto-increment bawaan spt
    SQL, jadi query SEMUA nilai yang ADA, ambil MAX + 1. CATATAN: ada
    risiko RACE CONDITION kalau 2 user dibuat BERSAMAAN persis (dapat
    nomor sama) -- cukup kecil kemungkinannya utk pemakaian admin manual
    spt fitur ini, TAPI BUKAN jaminan atomicity penuh (LDAP tidak
    ⚠️ BUG DITEMUKAN & DIPERBAIKI saat testing: versi SEBELUMNYA susun
    filter LDAP jadi `(objectClass=posixAccount=uidNumber=*)` (SALAH,
    3 tanda '=' ditumpuk jadi satu klausa, filter TIDAK VALID) -- akibatnya
    search SELALU kosong, fungsi INI selalu jatuh ke `start_from` (uid/gid
    number jadi angka awal yg SAMA terus, BUKAN increment dari data yang
    sungguh ada) -- ketahuan LANGSUNG dari testing (harusnya 2011,
    ternyata selalu 2000), BUKAN asumsi. Filter sekarang benar:
    `(&(objectClass=posixAccount)(uidNumber=*))`.
    """
    rows = client.search(base_dn, f'(&({object_class})({attribute}=*))', attributes=[attribute])
    numbers = []
    for row in rows:
        value = row.get(attribute)
        if isinstance(value, list):
            value = value[0] if value else None
        try:
            numbers.append(int(value))
        except (TypeError, ValueError):
            continue
    return (max(numbers) + 1) if numbers else start_from


class ZentyalUserCreateView(APIView):
    """
    POST /api/v1/netmgmt/zentyal/users/create/
    Body: {"username": "budi", "display_name": "Budi Santoso", "last_name": "Santoso", "email": "budi@contoh.com", "password": "..."}

    uidNumber dihitung OTOMATIS (MAX+1 dari user yang ada, lihat
    _next_available_number()) -- gidNumber pakai ZENTYAL_DEFAULT_GID_NUMBER
    (config, BUKAN dihitung -- grup Unix dipakai BERSAMA banyak user,
    lihat catatan di config/settings.py).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        display_name = (request.data.get('display_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        email = (request.data.get('email') or '').strip()
        password = request.data.get('password') or ''

        if not username:
            return Response({'error': "'username' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not display_name:
            return Response({'error': "'display_name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'error': "'password' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 8:
            return Response({'error': 'Password minimal 8 karakter.'}, status=status.HTTP_400_BAD_REQUEST)

        user_dn = f'uid={LDAPManagementClient.escape(username)},{settings.ZENTYAL_USER_BASE_DN}'

        try:
            with _get_zentyal_client() as client:
                uid_number = _next_available_number(client, settings.ZENTYAL_USER_BASE_DN, 'objectClass=posixAccount', 'uidNumber', 2000)

                attributes = {
                    'uid': username,
                    'cn': display_name,
                    'sn': last_name or display_name,
                    'uidNumber': str(uid_number),
                    'gidNumber': str(settings.ZENTYAL_DEFAULT_GID_NUMBER),
                    'homeDirectory': f'/home/{username}',
                    'loginShell': '/bin/bash',
                    'mailHomeDirectory': f'/home/{username}/Maildir',
                }
                if email:
                    attributes['mail'] = email

                client.add_entry(user_dn, ['top', 'inetOrgPerson', 'posixAccount', 'usereboxmail'], attributes)
                try:
                    client.set_password(user_dn, password, use_ad_method=False)
                except LDAPManagementError as exc:
                    return Response(
                        {'error': f'User dibuat TAPI gagal set password: {exc}. Reset password manual atau hapus user ini.'},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'User berhasil dibuat.', 'dn': user_dn, 'uid_number': uid_number}, status=status.HTTP_201_CREATED)


class ZentyalGroupCreateView(APIView):
    """
    POST /api/v1/netmgmt/zentyal/groups/create/
    Body: {"name": "tim-support", "description": "..."}
    Bikin posixGroup biasa (BUKAN zentyalDistributionGroup/mailing list --
    di luar scope saat ini, gampang ditambah nanti kalau perlu bikin jenis itu jg).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        description = (request.data.get('description') or '').strip()

        if not name:
            return Response({'error': "'name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        group_dn = f'cn={LDAPManagementClient.escape(name)},{settings.ZENTYAL_GROUP_BASE_DN}'

        try:
            with _get_zentyal_client() as client:
                gid_number = _next_available_number(client, settings.ZENTYAL_GROUP_BASE_DN, 'objectClass=posixGroup', 'gidNumber', 2000)

                attributes = {
                    'cn': name,
                    'gidNumber': str(gid_number),
                }
                if description:
                    attributes['description'] = description

                client.add_entry(group_dn, ['zentyalDistributionGroup', 'posixGroup'], attributes)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'Group berhasil dibuat.', 'dn': group_dn, 'gid_number': gid_number}, status=status.HTTP_201_CREATED)


class ZentyalUserToggleStatusView(APIView):
    """
    POST /api/v1/netmgmt/zentyal/users/toggle-status/
    Body: {"user_dn": "...", "action": "enable"|"disable"}

    Zentyal/POSIX TIDAK PUNYA bit "disabled" spt AD -- pakai konvensi
    Unix standar (SAMA dgn `passwd -l`): prefix '!' di depan hash
    `userPassword` bikin autentikasi GAGAL tanpa mengubah hash asli
    (REVERSIBLE, lihat _user_to_dict() utk detail lengkap).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_zentyal_users')]

    def post(self, request):
        user_dn = request.data.get('user_dn')
        action = request.data.get('action')
        if not user_dn or action not in ('enable', 'disable'):
            return Response({'error': "Wajib isi 'user_dn' dan 'action' ('enable' atau 'disable')."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_zentyal_client() as client:
                current_password = client.get_attribute(user_dn, 'userPassword')
                current_password = str(current_password or '')
                if action == 'disable':
                    new_password = current_password if current_password.startswith('!') else f'!{current_password}'
                else:
                    new_password = current_password[1:] if current_password.startswith('!') else current_password
                client.replace_attribute(user_dn, 'userPassword', new_password)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        message = 'User berhasil dinonaktifkan.' if action == 'disable' else 'User berhasil diaktifkan.'
        return Response({'success': True, 'message': message}, status=status.HTTP_200_OK)


class ZentyalUserDeleteView(APIView):
    """POST /api/v1/netmgmt/zentyal/users/delete/ -- Body: {"user_dn": "..."}. Hapus entry LDAP PERMANEN, tidak ada undo."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        user_dn = request.data.get('user_dn')
        if not user_dn:
            return Response({'error': "'user_dn' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_zentyal_client() as client:
                client.delete_entry(user_dn)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'User berhasil dihapus.'}, status=status.HTTP_200_OK)