"""
Backend autentikasi TERPISAH untuk login Mobile Attendance -- pakai PIN
Employee (iclock.employee.PIN) + password mobile (employee.mpassword,
di-hash), BUKAN username/password akun accounts.User biasa.

Dipanggil dengan kwargs BERBEDA dari login reguler (`pin`/`mobile_password`,
bukan `username`/`password`) -- ini SENGAJA, supaya backend ini otomatis
`return None` (tidak ganggu apa pun) saat dipanggil dari alur login
REGULER, dan sebaliknya `LDAPOrLocalBackend` juga otomatis `return None`
saat dipanggil dari alur login MOBILE ini -- keduanya aman berdampingan
di `AUTHENTICATION_BACKENDS` tanpa saling bentrok (pola standar Django
untuk banyak backend sekaligus).

Employee BISA login TANPA harus sudah punya akun accounts.User -- begitu
autentikasi (PIN + password) berhasil, backend ini otomatis cari ATAU buat
1 User "mobile-only" (is_mobile_only=True) yang terkait Employee tsb.
Akses User semacam ini dibatasi HANYA ke check-in/out/meal & enrollment
wajah oleh accounts/middleware.py::MobileAccessMiddleware.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password

from iclock.models import employee
from iclock.services import normalize_pin


class EmployeeMobileBackend(BaseBackend):
    def authenticate(self, request, pin=None, mobile_password=None, **kwargs):
        if not pin or not mobile_password:
            return None

        # PIN yang diketik karyawan biasanya TANPA leading zero (mis. "8113009"),
        # sementara yang tersimpan di employee.PIN (kolom `badgenumber`) SELALU
        # zero-padded 9 digit (mis. "008113009") -- normalize_pin() (dipakai
        # jg di iclock/services.py utk backup fingerprint dsb) menyamakan
        # keduanya. Tanpa ini, login SELALU gagal "PIN atau password salah"
        # walau PIN & password-nya sebenarnya benar.
        pin = normalize_pin(pin.strip())
        # PIN di tabel employee TIDAK unique (1 PIN yang sama bisa
        # terdaftar di beberapa device berbeda) -- ambil match PERTAMA,
        # sama seperti pola di accounts/forms.py::clean_emp_id.
        emp = employee.objects.filter(PIN=pin).first()
        if emp is None:
            return None

        default_password = getattr(settings, 'MOBILE_DEFAULT_PASSWORD', '123456')
        if emp.mpassword:
            if not check_password(mobile_password, emp.mpassword):
                return None
        else:
            # Belum pernah set password custom -- HANYA boleh login pakai
            # password default (representasi "masih default", walau field
            # mpassword-nya sendiri kosong di database).
            if mobile_password != default_password:
                return None

        User = get_user_model()
        # Cari User "mobile-only" yang SUDAH ADA khusus utk employee ini --
        # SENGAJA filter JUGA is_mobile_only=True, supaya TIDAK ketemu/reuse
        # akun REGULER (staff dsb) yang KEBETULAN sudah di-link EmpID ke
        # employee yang sama oleh admin (link EmpID admin adalah konsep
        # TERPISAH dari shadow user mobile-only ini, walau sama-sama pakai
        # field EmpID -- 1 Employee bisa punya 2 User berbeda: 1 akun
        # reguler yang di-link admin, 1 shadow user mobile-only ini).
        user = User.objects.filter(EmpID=emp, is_mobile_only=True).first()
        if user is None:
            user = User.objects.create(
                username=self._generate_username(User, emp),
                EmpID=emp,
                is_mobile_only=True,
                is_staff=False,
                is_superuser=False,
                is_active=True,
                auth_source=User.AuthSource.MOBILE_PIN,
            )
            user.set_unusable_password()  # User.password TIDAK dipakai sama sekali utk backend ini
            user.save(update_fields=['password'])

        if not user.is_active:
            return None
        return user

    @staticmethod
    def _generate_username(User, emp):
        base = f'mobile-{emp.PIN}'
        username = base
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base}-{suffix}'
        return username

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None


def mobile_password_needs_change(emp) -> bool:
    """
    True kalau password mobile Employee ini MASIH default -- baik karena
    belum pernah diganti sama sekali (`mpassword` kosong), ATAU karena
    (walau sudah tersimpan sebagai hash) isinya tetap representasi dari
    password default ('123456' / settings.MOBILE_DEFAULT_PASSWORD) --
    dipakai accounts/middleware.py utk memaksa alur ganti password.
    """
    if not emp.mpassword:
        return True
    default_password = getattr(settings, 'MOBILE_DEFAULT_PASSWORD', '123456')
    return check_password(default_password, emp.mpassword)
