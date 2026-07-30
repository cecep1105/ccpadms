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
from datetime import datetime, timezone, timedelta

from django.conf import settings
from ldap3.utils.dn import escape_rdn
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_ad_password
from netmgmt.ldap_utils import LDAPManagementClient, LDAPManagementError
from netmgmt.list_utils import paginate_sort_filter, parse_list_params

UAC_ACCOUNTDISABLE = 2  # bit userAccountControl -- akun dinonaktifkan
UAC_NORMAL_ACCOUNT = 512  # bit dasar "akun user biasa" (BUKAN computer/trust account) -- WAJIB ada di userAccountControl user baru


def _dn_to_domain_fqdn(base_dn: str) -> str:
    """'DC=contoso,DC=com' -> 'contoso.com' -- dipakai susun userPrincipalName (username@domain) saat bikin user baru."""
    parts = [part.split('=', 1)[1] for part in base_dn.split(',') if part.strip().upper().startswith('DC=')]
    return '.'.join(parts)


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

def convert_back(timestamp_string):
    """Convert a timestamp in Y=M=D H:M:S.f format into a windows filetime."""

    WINDOWS_TICKS = int(1/10**-7)  # 10,000,000 (100 nanoseconds or .1 microseconds)
    WINDOWS_EPOCH = datetime.strptime('1601-01-01 00:00:00','%Y-%m-%d %H:%M:%S')
    POSIX_EPOCH = datetime.strptime('1970-01-01 00:00:00','%Y-%m-%d %H:%M:%S')
    EPOCH_DIFF = (POSIX_EPOCH - WINDOWS_EPOCH).total_seconds()  # 11644473600.0
    # WINDOWS_TICKS_TO_POSIX_EPOCH = EPOCH_DIFF * WINDOWS_TICKS  # 116444736000000000.0

    import time

    dt = datetime.strptime(timestamp_string, '%Y-%m-%d %H:%M:%S.%f')
    posix_secs = int(time.mktime(dt.timetuple()))
    winticks = (posix_secs + int(EPOCH_DIFF)) * WINDOWS_TICKS
    return winticks

def _filetime_to_iso(filetime_str) -> str | None:
    """
    Konversi Windows FILETIME (interval 100-nanosecond sejak 1601-01-01,
    format yang dipakai AD utk lockoutTime/pwdLastSet/dst) -> string ISO
    datetime (UTC) -- None kalau nilai 0/kosong (artinya "tidak berlaku").
    """
    try:
        value = int(filetime_str)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    EPOCH_AS_FILETIME = 116444736000000000  # 1970-01-01 dlm satuan FILETIME
    HUNDREDS_OF_NANOSECONDS = 10000000
    unix_timestamp = (value - EPOCH_AS_FILETIME) / HUNDREDS_OF_NANOSECONDS
    try:
        return datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


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
        # ISO datetime (UTC) KAPAN akun terkunci -- None kalau tidak
        # terkunci. Frontend format jadi relatif ("2 menit lalu", dst).
        'locked_at': _filetime_to_iso(lockout_time) if is_locked else None,
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


def get_recently_locked_users(minutes: int = 2) -> list:
    """
    Query AD utk user yang TERKUNCI dalam N menit terakhir (default 2) --
    DIEKSTRAK jadi fungsi TERPISAH (SEBELUMNYA logic ini ada LANGSUNG di
    ADLockedUsersListView.get()) supaya bisa dipakai ULANG oleh
    netmgmt/tasks.py::check_ad_locked_users (Celery Beat, cek berkala &
    broadcast lewat WebSocket ke indikator global Topbar).

    KENAPA DIFILTER cuma N menit terakhir (BUKAN semua user yg PERNAH
    terkunci): AD py GPO auto-unlock (lockoutDuration) yang SEHARUSNYA
    otomatis buka kunci setelah beberapa menit -- TAPI atribut
    `lockoutTime` di AD TETAP menyimpan waktu SAAT TERKUNCI (bukan status
    "masih terkunci beneran SEKARANG"), jadi kalau TIDAK difilter, user
    yang terkunci BERTAHUN-TAHUN lalu (skr sudah otomatis lepas kuncinya
    scr efektif oleh AD, cuma atribut lockoutTime-nya tidak ikut ke-reset
    ke 0) akan TETAP muncul di daftar, padahal SUDAH TIDAK relevan lagi.
    Filter LDAP `(lockoutTime>=N)` dikerjakan SERVER-SIDE (bukan fetch
    semua lalu filter Python) -- lebih efisien.
    """
    threshold = datetime.now() - timedelta(minutes=minutes)
    filetime_threshold = convert_back(threshold.strftime('%Y-%m-%d %H:%M:%S.%f'))
    with _get_ad_client() as client:
        rows = client.search(
            settings.AD_USER_BASE_DN,
            '(&(objectClass=user)(objectCategory=person)(lockoutTime>=%d))' % filetime_threshold,
            attributes=['sAMAccountName', 'displayName', 'mail', 'userPrincipalName', 'userAccountControl', 'memberOf', 'lockoutTime'],
        )
    all_users = [_user_to_dict(row) for row in rows]
    return [u for u in all_users if u['is_locked']]


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
            users = get_recently_locked_users()
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

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


class ADUserCreateView(APIView):
    """
    POST /api/v1/netmgmt/ad/users/create/
    Body: {"username": "budi.santoso", "display_name": "Budi Santoso", "first_name": "Budi", "last_name": "Santoso", "email": "budi@contoso.com", "password": "..."}

    Alur bikin user AD (LDAP tidak bisa 1 langkah spt SQL INSERT biasa):
      1. `add()` entry BARU dgn userAccountControl=514 (512 NORMAL_ACCOUNT +
         2 ACCOUNTDISABLE, dijumlah via bitwise OR -- BUKAN "546", itu
         salah ketik di versi draft awal, sudah diperbaiki) -- AD MENOLAK bikin akun langsung AKTIF tanpa
         password, jadi HARUS mulai dari status nonaktif dulu.
      2. Set password (`unicodePwd`, format UTF-16-LE -- lihat
         set_password() di ldap_utils.py) -- method ini KHUSUS AD, WAJIB
         koneksi SSL/TLS (AD_USE_SSL=True), SAMA persis constraint yang
         sudah berlaku di ADResetPasswordView.
      3. `replace_attribute()` userAccountControl jadi 512 (NORMAL_ACCOUNT
         SAJA, tanpa ACCOUNTDISABLE) -- akun jadi AKTIF, cuma bisa
         dilakukan SETELAH password valid ter-set (kalau langkah 2 gagal/
         password tidak memenuhi policy, langkah ini TIDAK dijalankan --
         akun tertinggal nonaktif, BUKAN aktif tanpa password yg valid).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        display_name = (request.data.get('display_name') or '').strip()
        first_name = (request.data.get('first_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        email = (request.data.get('email') or '').strip()
        password = request.data.get('password') or ''

        if not username:
            return Response({'error': "'username' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not display_name:
            return Response({'error': "'display_name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'error': "'password' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        domain_fqdn = _dn_to_domain_fqdn(settings.AD_USER_BASE_DN)
        user_dn = f'CN={escape_rdn(display_name)},{settings.AD_USER_BASE_DN}'

        attributes = {
            'sAMAccountName': username,
            'userPrincipalName': f'{username}@{domain_fqdn}' if domain_fqdn else username,
            'displayName': display_name,
            'givenName': first_name or display_name,
            'sn': last_name or display_name,
            'userAccountControl': str(UAC_NORMAL_ACCOUNT | UAC_ACCOUNTDISABLE),
        }
        if email:
            attributes['mail'] = email

        try:
            with _get_ad_client() as client:
                client.add_entry(user_dn, ['top', 'person', 'organizationalPerson', 'user'], attributes)
                try:
                    client.set_password(user_dn, password, use_ad_method=True)
                except LDAPManagementError as exc:
                    # User TERLANJUR dibuat (nonaktif), tapi password gagal
                    # ter-set (mis. tidak memenuhi password policy AD) --
                    # JANGAN aktifkan, kembalikan pesan JELAS supaya admin
                    # tahu perlu reset password manual atau hapus user ini.
                    return Response(
                        {'error': f"User dibuat TAPI gagal set password (kemungkinan tidak memenuhi kebijakan password AD): {exc}. Akun masih NONAKTIF, reset password manual atau hapus user ini."},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                client.replace_attribute(user_dn, 'userAccountControl', str(UAC_NORMAL_ACCOUNT))
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'User berhasil dibuat & diaktifkan.', 'dn': user_dn}, status=status.HTTP_201_CREATED)


class ADGroupCreateView(APIView):
    """
    POST /api/v1/netmgmt/ad/groups/create/
    Body: {"name": "IT Support", "description": "..."}
    Bikin security group GLOBAL biasa (groupType=-2147483646) -- jenis
    paling umum dipakai (BEDA dari distribution group/universal/domain
    local, di luar scope saat ini, gampang ditambah nanti kalau perlu).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    GROUP_TYPE_GLOBAL_SECURITY = '-2147483646'

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        description = (request.data.get('description') or '').strip()

        if not name:
            return Response({'error': "'name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        group_dn = f'CN={escape_rdn(name)},{settings.AD_GROUP_BASE_DN}'
        attributes = {
            'sAMAccountName': name,
            'groupType': self.GROUP_TYPE_GLOBAL_SECURITY,
        }
        if description:
            attributes['description'] = description

        try:
            with _get_ad_client() as client:
                client.add_entry(group_dn, ['top', 'group'], attributes)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'success': True, 'message': 'Group berhasil dibuat.', 'dn': group_dn}, status=status.HTTP_201_CREATED)
