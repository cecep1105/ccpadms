"""
Middleware KHUSUS user "mobile-only" (login via PIN Employee, lihat
accounts/mobile_backend.py) -- SAMA SEKALI tidak memengaruhi user reguler
(staff/LDAP/local biasa), murni no-op utk mereka.

2 tanggung jawab, keduanya HANYA berlaku utk user mobile-only:
1. Batasi akses HANYA ke whitelist view Mobile Attendance (check-in/out/
   meal, enrollment wajah, ganti password mobile, logout) -- selain itu
   otomatis di-redirect ke halaman check-in dengan pesan.
2. Kalau password mobile-nya MASIH default (kosong atau '123456') --
   paksa redirect ke halaman ganti password TERLEBIH DAHULU, sebelum bisa
   akses fitur lain (kecuali ke halaman ganti password itu sendiri &
   logout).
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

from .mobile_backend import mobile_password_needs_change

# View yang boleh diakses user mobile-only TANPA syarat lain.
MOBILE_ONLY_ALLOWED_URL_NAMES = {
    'mattendance:checkin_test_page',
    'mattendance:checkin_submit',
    'mattendance:checkin_meal_page',
    'mattendance:checkin_meal_submit',
    'mattendance:face_enroll_page',
    'mattendance:face_enroll_submit',
    'mattendance:mobile_profile_page',
    'mattendance:mobile_change_password_page',
    'mattendance:mobile_change_password_submit',
    'mattendance:attendance_history_page',
    'accounts:logout',
}
# Subset di atas yang TETAP boleh diakses walau password masih wajib diganti.
MOBILE_ONLY_PASSWORD_CHANGE_EXEMPT = {
    'mattendance:mobile_change_password_page',
    'mattendance:mobile_change_password_submit',
    'accounts:logout',
}


class MobileAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False) and getattr(user, 'is_mobile_only', False):
            try:
                resolved = resolve(request.path_info)
                full_name = f'{resolved.namespace}:{resolved.url_name}' if resolved.namespace else resolved.url_name
            except Resolver404:
                full_name = None

            if full_name not in MOBILE_ONLY_ALLOWED_URL_NAMES:
                messages.error(request, 'Akses dibatasi -- akun Mobile Attendance hanya bisa check-in/out/meal & enrollment wajah.')
                return redirect('mattendance:checkin_test_page')

            if full_name not in MOBILE_ONLY_PASSWORD_CHANGE_EXEMPT:
                emp = user.EmpID
                if emp is not None and mobile_password_needs_change(emp):
                    messages.error(request, 'Password Anda masih default -- wajib diganti sebelum melanjutkan.')
                    return redirect('mattendance:mobile_change_password_page')

        return self.get_response(request)
