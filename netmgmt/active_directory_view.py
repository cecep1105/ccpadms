"""
Endpoint manajemen Active Directory: lihat users & groups, tambah/hapus
user dari group -- lewat service account (bind DN) yang PUNYA HAK BACA +
TULIS di direktori AD (BEDA dari AUTH_LDAP_* yang KHUSUS login staff,
lihat config/settings.py bagian AD_*).

Skema AD (standar, BUKAN skema POSIX/Zentyal -- lihat netmgmt/zentyal_view.py
utk itu): user object class 'user' (dgn objectCategory 'person', supaya
tidak ikut kebawa computer account yg JUGA objectClass=user di AD),
keanggotaan group lewat atribut `member` di sisi GROUP (nilainya DN
user), BUKAN atribut di sisi user (`memberOf` ada tapi itu computed/
read-only oleh AD sendiri, tidak bisa diubah langsung).

userAccountControl: bitmask status akun AD -- bit ACCOUNTDISABLE (nilai
2) menandakan akun DINONAKTIFKAN. Field `is_enabled` di response API ini
hasil decode bit itu, supaya frontend tidak perlu tahu detail bitmask AD.
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_ad_password
from netmgmt.ldap_utils import LDAPManagementClient, LDAPManagementError
from netmgmt.list_utils import paginate_sort_filter, parse_list_params

UAC_ACCOUNTDISABLE = 2  # bit userAccountControl -- akun dinonaktifkan


def _get_ad_client() -> LDAPManagementClient:
    if not settings.AD_BIND_PASSWORD_ENCRYPTED:
        raise LDAPManagementError(
            'Password service account AD belum diisi (AD_BIND_PASSWORD_ENCRYPTED di .env) -- lihat '
            'netmgmt/crypto_utils.py & management command generate_ad_key/encrypt_ad_password.'
        )
    try:
        password = decrypt_ad_password(settings.AD_BIND_PASSWORD_ENCRYPTED)
    except NetmgmtCryptoError as exc:
        raise LDAPManagementError(str(exc)) from exc
    return LDAPManagementClient(
        server_uri=settings.AD_SERVER_URI,
        bind_dn=settings.AD_BIND_DN,
        bind_password=password,
        use_ssl=settings.AD_USE_SSL,
        timeout=settings.AD_CONNECT_TIMEOUT,
    )


def _attr(entry: dict, name: str, default=''):
    """
    ldap3 kembalikan NILAI ATRIBUT sbg LIST (walau atribut itu
    single-valued, mis. displayName cuma 1 nilai tapi tetap dibungkus
    list ['Budi Santoso']) -- helper ini AMBIL NILAI PERTAMA (atau
    default kalau kosong/tidak ada), supaya kode pemanggil tidak perlu
    urus indexing list di semua tempat.
    """
    value = entry.get(name)
    if not value:
        return default
    if isinstance(value, list):
        return value[0] if value else default
    return value


def _user_to_dict(entry: dict) -> dict:
    uac = _attr(entry, 'userAccountControl', 0)
    try:
        uac = int(uac)
    except (TypeError, ValueError):
        uac = 0
    member_of = entry.get('memberOf') or []
    # lockoutTime: nilai LargeInteger AD -- 0 (atau tidak ada) = TIDAK
    # terkunci, nilai APA PUN selain 0 = terkunci (menyimpan WAKTU
    # terkunci, bukan status boolean langsung, tapi cukup cek != 0 saja).
    # BEDA dari is_enabled (dinonaktifkan MANUAL oleh admin) -- lockout
    # terjadi OTOMATIS krn salah password berkali-kali, unlock via reset
    # lockoutTime ke 0 (lihat ADUserUnlockView).
    lockout_time = _attr(entry, 'lockoutTime', '0')
    is_locked = str(lockout_time) not in ('0', '', 'None')
    return {
        'dn': entry.get('dn', ''),
        'username': _attr(entry, 'sAMAccountName'),
        'display_name': _attr(entry, 'displayName'),
        'email': _attr(entry, 'mail'),
        'user_principal_name': _attr(entry, 'userPrincipalName'),
        'is_enabled': not bool(uac & UAC_ACCOUNTDISABLE),
        'is_locked': is_locked,
        'group_count': len(member_of) if isinstance(member_of, list) else 0,
        'member_of': member_of if isinstance(member_of, list) else [],
    }


def _group_to_dict(entry: dict) -> dict:
    members = entry.get('member') or []
    return {
        'dn': entry.get('dn', ''),
        'name': _attr(entry, 'cn'),
        'description': _attr(entry, 'description'),
        'member_count': len(members) if isinstance(members, list) else 0,
    }


class ADUserListView(APIView):
    """GET /api/v1/netmgmt/ad/users/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields= -- daftar user AD."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            with _get_ad_client() as client:
                rows = client.search(
                    settings.AD_USER_BASE_DN,
                    '(&(objectClass=user)(objectCategory=person))',
                    attributes=['sAMAccountName', 'displayName', 'mail', 'userPrincipalName', 'userAccountControl', 'memberOf', 'lockoutTime'],
                )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        users = [_user_to_dict(row) for row in rows]
        params = parse_list_params(request)
        payload = paginate_sort_filter(users, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ADGroupListView(APIView):
    """GET /api/v1/netmgmt/ad/groups/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields= -- daftar group AD."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            with _get_ad_client() as client:
                rows = client.search(
                    settings.AD_GROUP_BASE_DN,
                    '(objectClass=group)',
                    attributes=['cn', 'description', 'member'],
                )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        groups = [_group_to_dict(row) for row in rows]
        params = parse_list_params(request)
        payload = paginate_sort_filter(groups, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ADGroupMembersView(APIView):
    """GET /api/v1/netmgmt/ad/groups/<path:group_dn>/members/ -- daftar user di dalam 1 group (LENGKAP, tanpa pagination -- biasanya jumlah member per group jauh lebih sedikit drpd total user)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request, group_dn=None):
        try:
            with _get_ad_client() as client:
                group_rows = client.search(group_dn, '(objectClass=group)', attributes=['cn', 'member'])
                if not group_rows:
                    return Response({'error': f"Group '{group_dn}' tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
                member_dns = group_rows[0].get('member') or []

                members = []
                for member_dn in member_dns:
                    user_rows = client.search(
                        member_dn, '(objectClass=user)',
                        attributes=['sAMAccountName', 'displayName', 'mail', 'userAccountControl'],
                    )
                    if user_rows:
                        members.append(_user_to_dict(user_rows[0]))
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'count': len(members), 'results': members}, status=status.HTTP_200_OK)


class ADGroupMembershipView(APIView):
    """
    POST /api/v1/netmgmt/ad/group-membership/
    Body: {"group_dn": "...", "user_dn": "...", "action": "add"|"remove"}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        group_dn = request.data.get('group_dn')
        user_dn = request.data.get('user_dn')
        action = request.data.get('action')

        if not group_dn or not user_dn or action not in ('add', 'remove'):
            return Response(
                {'error': "Wajib isi 'group_dn', 'user_dn', dan 'action' ('add' atau 'remove')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with _get_ad_client() as client:
                if action == 'add':
                    client.add_member(group_dn, user_dn)
                    message = 'User berhasil ditambahkan ke group.'
                else:
                    client.remove_member(group_dn, user_dn)
                    message = 'User berhasil dihapus dari group.'
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': message}, status=status.HTTP_200_OK)


class ADResetPasswordView(APIView):
    """
    POST /api/v1/netmgmt/ad/reset-password/
    Body: {"user_dn": "...", "new_password": "..."}

    PENTING -- AD MEWAJIBKAN koneksi TERENKRIPSI (LDAPS/StartTLS) utk
    operasi ubah password (atribut `unicodePwd`, format UTF-16-LE khusus
    -- lihat netmgmt/ldap_utils.py::LDAPManagementClient.set_password).
    Ini BATASAN AD SENDIRI (keamanan bawaan Microsoft), BUKAN keterbatasan
    kode ini -- kalau AD_USE_SSL=False di .env, operasi ini AKAN GAGAL,
    pesan errornya menyebutkan ini secara eksplisit.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        user_dn = request.data.get('user_dn')
        new_password = request.data.get('new_password')

        if not user_dn or not new_password:
            return Response({'error': "Wajib isi 'user_dn' dan 'new_password'."}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 8:
            # AD SENDIRI biasanya punya password policy lebih ketat (kompleksitas dkk) --
            # ini cuma validasi MINIMAL di sisi kita, AD tetap bisa menolak dgn alasan lain.
            return Response({'error': 'Password baru minimal 8 karakter.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_ad_client() as client:
                client.set_password(user_dn, new_password, use_ad_method=True)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'Password berhasil direset.'}, status=status.HTTP_200_OK)


class ADUserToggleStatusView(APIView):
    """
    POST /api/v1/netmgmt/ad/users/toggle-status/
    Body: {"user_dn": "...", "action": "enable"|"disable"}

    Ubah bit ACCOUNTDISABLE (nilai 2) di userAccountControl -- READ dulu
    nilai SAAT INI (bitmask ini py BANYAK bit lain, mis. NORMAL_ACCOUNT,
    DONT_EXPIRE_PASSWORD, dst -- TIDAK BOLEH ditimpa asal, cuma bit
    ACCOUNTDISABLE-nya saja yang diubah, sisanya PERSIS dipertahankan).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        user_dn = request.data.get('user_dn')
        action = request.data.get('action')
        if not user_dn or action not in ('enable', 'disable'):
            return Response({'error': "Wajib isi 'user_dn' dan 'action' ('enable' atau 'disable')."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_ad_client() as client:
                current_uac = client.get_attribute(user_dn, 'userAccountControl')
                current_uac = int(current_uac) if current_uac is not None else 0
                new_uac = (current_uac | UAC_ACCOUNTDISABLE) if action == 'disable' else (current_uac & ~UAC_ACCOUNTDISABLE)
                client.replace_attribute(user_dn, 'userAccountControl', str(new_uac))
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        message = 'User berhasil dinonaktifkan.' if action == 'disable' else 'User berhasil diaktifkan.'
        return Response({'success': True, 'message': message}, status=status.HTTP_200_OK)


class ADLockedUsersListView(APIView):
    """
    GET /api/v1/netmgmt/ad/users/locked/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields=
    -- daftar user yang TERKUNCI OTOMATIS (lockoutTime != 0, krn salah
    password berkali-kali) -- BEDA dari user yang DINONAKTIFKAN MANUAL
    (is_enabled=False, lihat ADUserToggleStatusView) -- 2 status yang
    TIDAK SALING TERKAIT (bisa aktif tapi terkunci, atau nonaktif tapi
    tidak pernah terkunci).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            with _get_ad_client() as client:
                rows = client.search(
                    settings.AD_USER_BASE_DN,
                    '(&(objectClass=user)(objectCategory=person))',
                    attributes=['sAMAccountName', 'displayName', 'mail', 'userPrincipalName', 'userAccountControl', 'memberOf', 'lockoutTime'],
                )
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        all_users = [_user_to_dict(row) for row in rows]
        users = [u for u in all_users if u['is_locked']]
        params = parse_list_params(request)
        payload = paginate_sort_filter(users, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ADUserUnlockView(APIView):
    """
    POST /api/v1/netmgmt/ad/users/unlock/
    Body: {"user_dn": "..."}

    Reset lockoutTime ke 0 -- cara STANDAR "unlock" akun AD yang terkunci
    otomatis (BUKAN ubah userAccountControl -- itu utk disable/enable
    MANUAL, konsep berbeda, lihat catatan di ADLockedUsersListView).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        user_dn = request.data.get('user_dn')
        if not user_dn:
            return Response({'error': "'user_dn' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with _get_ad_client() as client:
                client.replace_attribute(user_dn, 'lockoutTime', '0')
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'User berhasil di-unlock.'}, status=status.HTTP_200_OK)
