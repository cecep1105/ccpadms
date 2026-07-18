"""
Tool diagnostik untuk troubleshoot koneksi LDAP/Active Directory.

Pakai ini kalau login LDAP gagal terus ("user belum ada" padahal user-nya
ada) -- akan menunjukkan persis di step mana masalahnya: koneksi, bind
service account, atau search filter/base DN yang tidak match.

Contoh pakai:
    python manage.py ldap_debug budi.santoso
    python manage.py ldap_debug budi.santoso --password "passwordnya"
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from ldap3 import ALL, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPException


class Command(BaseCommand):
    help = 'Debug koneksi & pencarian LDAP/Active Directory untuk troubleshooting login.'

    def add_arguments(self, parser):
        parser.add_argument('username', help='Username yang mau dicari/dites di LDAP')
        parser.add_argument(
            '--password', default=None,
            help='Kalau diisi, akan dites juga bind pakai username+password ini (verifikasi password benar)',
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options.get('password')

        self.stdout.write(self.style.NOTICE('--- Konfigurasi LDAP yang dipakai (dari .env) ---'))
        self.stdout.write(f'SERVER_URI     : {settings.AUTH_LDAP_SERVER_URI}')
        self.stdout.write(f'USE_SSL        : {settings.AUTH_LDAP_USE_SSL}')
        self.stdout.write(f'BIND_DN        : {settings.AUTH_LDAP_BIND_DN or "(kosong / anonymous)"}')
        self.stdout.write(f'BASE_DN        : {settings.AUTH_LDAP_BASE_DN}')
        self.stdout.write(f'SEARCH_FILTER  : {settings.AUTH_LDAP_USER_SEARCH_FILTER}')
        self.stdout.write('')

        server = Server(
            settings.AUTH_LDAP_SERVER_URI,
            use_ssl=settings.AUTH_LDAP_USE_SSL,
            get_info=ALL,
            connect_timeout=settings.AUTH_LDAP_CONNECT_TIMEOUT,
        )

        # --- Step 1: bind pakai service account ---
        self.stdout.write(self.style.NOTICE('--- Step 1: Bind pakai service account (BIND_DN) ---'))
        try:
            conn = Connection(
                server,
                user=settings.AUTH_LDAP_BIND_DN or None,
                password=settings.AUTH_LDAP_BIND_PASSWORD or None,
                auto_bind=True,
                receive_timeout=settings.AUTH_LDAP_CONNECT_TIMEOUT,
            )
            self.stdout.write(self.style.SUCCESS('OK: berhasil bind service account.'))
        except LDAPException as exc:
            self.stdout.write(self.style.ERROR(f'GAGAL bind service account: {exc}'))
            self.stdout.write(self.style.WARNING(
                'Kemungkinan penyebab:\n'
                '  - BIND_DN / BIND_PASSWORD salah\n'
                '  - Server AD tidak reachable dari mesin ini (cek firewall/VPN/port 389 atau 636)\n'
                '  - AD menolak simple bind non-SSL -> coba AUTH_LDAP_USE_SSL=True + port 636\n'
                '  - Format BIND_DN untuk AD biasanya: "CN=Service Account,OU=...,DC=corp,DC=local" '
                'ATAU UPN "svc_ldap@corp.local" (bukan format DOMAIN\\\\user)'
            ))
            return

        # --- Step 2: search user ---
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(f'--- Step 2: Search "{username}" pakai filter yang dikonfigurasi ---'))
        search_filter = settings.AUTH_LDAP_USER_SEARCH_FILTER.format(username=username)
        self.stdout.write(f'Filter final   : {search_filter}')
        try:
            conn.search(settings.AUTH_LDAP_BASE_DN, search_filter, SUBTREE, attributes=['*'])
        except LDAPException as exc:
            self.stdout.write(self.style.ERROR(f'GAGAL search: {exc}'))
            conn.unbind()
            return

        if not conn.entries:
            self.stdout.write(self.style.ERROR('NOL entry ditemukan dengan filter & base DN ini.'))
            self.stdout.write(self.style.WARNING(
                'Kemungkinan penyebab (khusus Active Directory):\n'
                '  1. Filter pakai (uid={username}) -- AD TIDAK punya atribut "uid" secara default.\n'
                '     Ganti .env: AUTH_LDAP_USER_SEARCH_FILTER=(sAMAccountName={username})\n'
                '  2. AUTH_LDAP_BASE_DN tidak mencakup OU tempat user berada.\n'
                '     Coba base DN root domain dulu, mis. "DC=corp,DC=local".\n'
                '  3. Username yang dites pakai domain (DOMAIN\\\\user) atau beda huruf besar/kecil -- '
                'coba username short saja.'
            ))
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('--- Mencoba search lebih luas: contoh user yang ADA di base DN ini ---'))
            try:
                conn.search(
                    settings.AUTH_LDAP_BASE_DN, '(objectClass=user)', SUBTREE,
                    attributes=['sAMAccountName', 'userPrincipalName', 'cn'],
                )
                sample = conn.entries[:5]
                if sample:
                    self.stdout.write(f'Ketemu {len(conn.entries)} objectClass=user (contoh 5 pertama):')
                    for e in sample:
                        sam = getattr(e, 'sAMAccountName', None)
                        self.stdout.write(f'  - DN: {e.entry_dn}')
                        self.stdout.write(f'    sAMAccountName: {sam.value if sam else "?"}')
                    self.stdout.write(self.style.WARNING(
                        '\n=> Bandingkan sAMAccountName di atas dengan username yang Anda coba login. '
                        'Kalau filter Anda masih (uid=...), itu penyebabnya -- ganti ke (sAMAccountName=...).'
                    ))
                else:
                    self.stdout.write(self.style.ERROR(
                        'Base DN ini sama sekali tidak punya objectClass=user -- AUTH_LDAP_BASE_DN kemungkinan salah.'
                    ))
            except LDAPException as exc:
                self.stdout.write(self.style.ERROR(f'Search luas juga gagal: {exc}'))
            conn.unbind()
            return

        entry = conn.entries[0]
        self.stdout.write(self.style.SUCCESS(f'OK: ketemu {len(conn.entries)} entry.'))
        self.stdout.write(f'DN             : {entry.entry_dn}')
        sam = getattr(entry, 'sAMAccountName', None)
        mail = getattr(entry, 'mail', None)
        self.stdout.write(f'sAMAccountName : {sam.value if sam else "-"}')
        self.stdout.write(f'mail           : {mail.value if mail else "-"}')
        conn.unbind()

        # --- Step 3 (opsional): test bind pakai password user ---
        if password:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('--- Step 3: Test bind pakai username+password yang diberikan ---'))
            try:
                user_conn = Connection(
                    server, user=entry.entry_dn, password=password,
                    receive_timeout=settings.AUTH_LDAP_CONNECT_TIMEOUT,
                )
                if user_conn.bind():
                    self.stdout.write(self.style.SUCCESS('OK: password benar, bind sukses. Login seharusnya berhasil.'))
                    user_conn.unbind()
                else:
                    self.stdout.write(self.style.ERROR(f'GAGAL bind (password salah / ditolak): {user_conn.result}'))
            except LDAPException as exc:
                self.stdout.write(self.style.ERROR(f'GAGAL bind (exception koneksi): {exc}'))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                'Tip: tambahkan --password "passwordnya" untuk sekalian tes bind password user ini.'
            ))
