from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def staff_required(view_func):
    """Halaman khusus admin (is_staff atau is_superuser)."""

    @wraps(view_func)
    @login_required(login_url='accounts:login')
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, 'Anda tidak memiliki akses ke halaman ini.')
            return redirect('dashboard:profile')
        return view_func(request, *args, **kwargs)

    return wrapper


def superuser_required(view_func):
    """Aksi sensitif (hapus user, ubah role) khusus super admin."""

    @wraps(view_func)
    @login_required(login_url='accounts:login')
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Aksi ini hanya untuk super admin.')
            return redirect('dashboard:user_list')
        return view_func(request, *args, **kwargs)

    return wrapper


def permission_or_staff_required(*perm_codenames):
    """
    Halaman/aksi yang boleh diakses staff/superuser SEPERTI BIASA, TAPI juga
    dibuka untuk user non-staff yang SUDAH DIBERI IZIN eksplisit oleh admin
    (lewat halaman "Kelola Izin User") untuk salah satu permission di
    `perm_codenames` (mis. 'iclock.can_transfer_finger').

    Dipakai utk fitur terbatas yang sengaja dibuka ke user non-staff
    tertentu (Transfer Data Finger, Attendance Recap) -- BEDA dengan
    `staff_required` yang menutup total akses non-staff.

    Contoh: @permission_or_staff_required('iclock.can_transfer_finger')
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url='accounts:login')
        def wrapper(request, *args, **kwargs):
            user = request.user
            if user.is_staff or user.is_superuser or any(user.has_perm(p) for p in perm_codenames):
                return view_func(request, *args, **kwargs)
            messages.error(request, 'Anda tidak memiliki akses ke halaman ini.')
            return redirect('dashboard:index')
        return wrapper
    return decorator
