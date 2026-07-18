"""
Tool diagnostik untuk troubleshoot login Mobile Attendance (PIN Employee).

Pakai ini kalau login mobile gagal terus -- akan menunjukkan persis di step
mana masalahnya: PIN tidak ketemu, password salah, backend belum
terdaftar, dsb. Jalankan LANGSUNG di server yang bermasalah (bukan di
sandbox pengembangan) supaya hasilnya mencerminkan kondisi database &
settings yang SUNGGUHAN.

⚠️ CATATAN PALING PENTING (penyebab paling umum "user belum ada" tetap
muncul meski PIN & password benar): pesan itu SEBENARNYA berasal dari
alur login STAFF REGULER (accounts/exceptions.py::UserNotFoundInLDAPError,
dipicu accounts/services.py::authenticate_user), BUKAN dari backend mobile
sama sekali. Kalau Anda mengetik PIN di halaman login STAFF
(/accounts/login/) alih-alih halaman login MOBILE
(/mattendance/login/), sistem akan mengira PIN itu sebagai USERNAME akun
staff biasa, lalu (kalau LDAP dikonfigurasi) coba cari di LDAP -- gagal,
lalu keluar pesan "User belum ada". PASTIKAN Anda mengakses
/mattendance/login/, BUKAN /accounts/login/.

Contoh pakai:
    python manage.py mobile_login_debug 8113009
    python manage.py mobile_login_debug 8113009 --password 123456
"""
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.hashers import check_password
from django.core.management.base import BaseCommand

from accounts.mobile_backend import mobile_password_needs_change
from iclock.models import employee
from iclock.services import normalize_pin


class Command(BaseCommand):
    help = 'Debug login Mobile Attendance (PIN Employee) untuk troubleshooting.'

    def add_arguments(self, parser):
        parser.add_argument('pin', help='PIN yang diketik user (boleh dengan atau tanpa nol di depan)')
        parser.add_argument(
            '--password', default=None,
            help='Kalau diisi, akan dites juga autentikasi lengkap pakai PIN+password ini',
        )

    def handle(self, *args, **options):
        raw_pin = options['pin']
        password = options.get('password')
        User = get_user_model()

        self.stdout.write(self.style.WARNING(
            '\n⚠️  INGAT: login mobile HARUS lewat /mattendance/login/, BUKAN /accounts/login/ '
            '(halaman staff biasa). Kalau Anda mengetik PIN di halaman staff, pesan "User belum '
            'ada" itu berasal dari alur LDAP/local reguler, bukan dari backend mobile ini sama '
            'sekali -- itu penyebab paling umum gejala ini.\n'
        ))

        self.stdout.write('=== 1. Cek field mpassword ada di database ===')
        try:
            employee.objects.filter(mpassword__isnull=False).exists()
            self.stdout.write(self.style.SUCCESS('  OK -- kolom mpassword bisa diakses.'))
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f'  GAGAL: {exc}'))
            self.stdout.write(self.style.ERROR(
                '  --> Kemungkinan migrasi belum jalan di database ini. Jalankan:\n'
                '      python manage.py makemigrations accounts iclock\n'
                '      python manage.py migrate'
            ))
            return

        self.stdout.write('\n=== 2. Normalisasi PIN ===')
        normalized_pin = normalize_pin(raw_pin.strip())
        self.stdout.write(f"  PIN yang diketik : '{raw_pin}'")
        self.stdout.write(f"  PIN dinormalisasi: '{normalized_pin}'")
        if raw_pin.strip() != normalized_pin:
            self.stdout.write(f"  (leading zero ditambahkan otomatis -- ini normal & benar)")

        self.stdout.write('\n=== 3. Cari Employee dengan PIN ini ===')
        matches = list(employee.objects.filter(PIN=normalized_pin))
        if not matches:
            self.stdout.write(self.style.ERROR(f"  TIDAK KETEMU Employee dengan PIN '{normalized_pin}'."))
            self.stdout.write(self.style.ERROR(
                '  --> Cek lagi PIN-nya benar, atau cek langsung ke database: \n'
                f"      SELECT userid, badgenumber, name FROM userinfo WHERE badgenumber LIKE '%{raw_pin.strip()}%';"
            ))
            return
        self.stdout.write(self.style.SUCCESS(f'  Ketemu {len(matches)} record:'))
        for emp in matches:
            self.stdout.write(f'    id={emp.id}, PIN={emp.PIN!r}, nama={emp.EName!r}, SN={emp.SN_id!r}')
        emp = matches[0]
        if len(matches) > 1:
            self.stdout.write(self.style.WARNING(
                f'  PIN ini terdaftar di {len(matches)} device berbeda -- yang dipakai login adalah '
                f'record PERTAMA (id={emp.id}), sesuai konvensi yang sama dgn fitur lain di aplikasi ini.'
            ))

        self.stdout.write('\n=== 4. Status password mobile (mpassword) Employee ini ===')
        default_password = getattr(settings, 'MOBILE_DEFAULT_PASSWORD', '123456')
        if not emp.mpassword:
            self.stdout.write(f"  mpassword KOSONG -- berarti belum pernah ganti password, HARUS login pakai password default ('{default_password}').")
        else:
            self.stdout.write(f'  mpassword SUDAH diisi (hash tersimpan, panjang {len(emp.mpassword)} karakter).')
            still_default = mobile_password_needs_change(emp)
            self.stdout.write(f"  Apakah masih representasi password default? {'YA' if still_default else 'TIDAK (sudah diganti custom)'}")

        self.stdout.write('\n=== 5. Cek AUTHENTICATION_BACKENDS ===')
        backends = getattr(settings, 'AUTHENTICATION_BACKENDS', [])
        if 'accounts.mobile_backend.EmployeeMobileBackend' in backends:
            self.stdout.write(self.style.SUCCESS('  OK -- EmployeeMobileBackend terdaftar di AUTHENTICATION_BACKENDS.'))
        else:
            self.stdout.write(self.style.ERROR('  GAGAL -- EmployeeMobileBackend TIDAK ada di AUTHENTICATION_BACKENDS!'))
            self.stdout.write(self.style.ERROR(f'  Isi saat ini: {backends}'))
            self.stdout.write(self.style.ERROR('  --> Tambahkan ke config/settings.py, lalu restart server.'))
            return

        if password is None:
            self.stdout.write(self.style.WARNING(
                "\n(Tidak ada --password diisi, jadi tes autentikasi END-TO-END dilewati. "
                "Jalankan lagi dengan --password '<password_yang_dicoba>' utk tes penuh.)"
            ))
            return

        self.stdout.write('\n=== 6. Cek password SECARA MANUAL (meniru logic backend persis) ===')
        if emp.mpassword:
            manual_check = check_password(password, emp.mpassword)
            self.stdout.write(f'  check_password(password_diinput, mpassword_tersimpan) = {manual_check}')
        else:
            manual_check = (password == default_password)
            self.stdout.write(f"  mpassword kosong -> dibandingkan langsung ke default '{default_password}': {manual_check}")

        self.stdout.write('\n=== 7. Tes autentikasi END-TO-END (persis seperti saat login sungguhan) ===')
        user = authenticate(pin=raw_pin, mobile_password=password)
        if user is not None:
            self.stdout.write(self.style.SUCCESS(f'  BERHASIL -- login akan sukses. User: {user.username} (is_mobile_only={user.is_mobile_only})'))
            if mobile_password_needs_change(emp):
                self.stdout.write(self.style.WARNING('  Setelah login, akan diarahkan WAJIB ganti password dulu (password masih default).'))
        else:
            self.stdout.write(self.style.ERROR('  GAGAL -- authenticate() mengembalikan None, login akan ditolak.'))
            if manual_check:
                self.stdout.write(self.style.ERROR(
                    '  ANEH: pengecekan manual di atas bilang password COCOK, tapi authenticate() '
                    'tetap gagal -- kemungkinan ada masalah lain (mis. user.is_active=False, atau '
                    'exception tersembunyi). Cek log Django server utk detail error lebih lanjut.'
                ))
            else:
                self.stdout.write('  Sesuai dugaan -- password yang diinput memang tidak cocok.')
