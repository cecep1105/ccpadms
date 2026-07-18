from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts import services
from accounts.exceptions import ServiceError
from accounts.forms import (
    AdminResetPasswordForm,
    ChangePasswordForm,
    LocalUserCreateForm,
    ProfileForm,
    UserEditForm,
)
from accounts.permissions import staff_required, superuser_required
from iclock.models import RegisteredDevice
from iclock.services import UNREGISTERED_POOL_ID

User = get_user_model()


def index(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    if request.user.is_staff or request.user.is_superuser:
        return redirect('dashboard:admin_home')
    return redirect('dashboard:user_home')


@login_required
def user_home(request):
    """
    Halaman utama untuk user NON-STAFF -- tampilkan card/icon button CUMA
    utk fitur yang user ini sudah diberi izin (permission) melakukannya
    oleh admin (lewat halaman "Kelola Izin User"). Staff/superuser TIDAK
    diarahkan ke sini, mereka tetap ke admin_home seperti biasa.
    """
    user = request.user
    available_actions = []
    if user.is_staff or user.is_superuser or user.has_perm('iclock.can_transfer_finger'):
        available_actions.append({
            'title': 'Transfer Data Finger',
            'icon': '👆',
            'url': reverse('iclock:device_user_list'),
            'description': 'Transfer data sidik jari karyawan ke device lain.',
        })
    if user.is_staff or user.is_superuser or user.has_perm('iclock.can_view_attendance_recap'):
        available_actions.append({
            'title': 'Rekap Absensi',
            'icon': '📅',
            'url': reverse('iclock:attendance_recap'),
            'description': 'Lihat rekap kehadiran/absensi karyawan.',
        })
    # Check-in/out GPS TIDAK digerbangi permission (beda dgn 2 fitur di
    # atas) -- selalu tersedia utk semua user login, karena check-in/out
    # absensi adalah kebutuhan universal siapa pun yang pakai sistem ini
    # sebagai karyawan, bukan fitur admin terbatas.
    available_actions.append({
        'title': 'Enrollment Wajah',
        'icon': '🙂',
        'url': reverse('mattendance:face_enroll_page'),
        'description': 'Daftarkan wajah untuk verifikasi check-in/out (wajib sebelum bisa check-in/out).',
    })
    available_actions.append({
        'title': 'Check-in/Out (GPS)',
        'icon': '📍',
        'url': reverse('mattendance:checkin_test_page'),
        'description': 'Absen masuk/pulang pakai lokasi GPS & verifikasi wajah.',
    })
    available_actions.append({
        'title': 'Check/Meal',
        'icon': '🍽️',
        'url': reverse('mattendance:checkin_meal_page'),
        'description': 'Absen makan siang pakai lokasi GPS & scan QR code kantin.',
    })
    return render(request, 'dashboard/user_home.html', {'available_actions': available_actions})


# ---------------------------------------------------------------------------
# ADMIN: ringkasan & manajemen user
# ---------------------------------------------------------------------------
@staff_required
def admin_home(request):
    stats = {
        'total_users': User.objects.count(),
        'active_users': User.objects.filter(is_active=True).count(),
        'ldap_users': User.objects.filter(auth_source=User.AuthSource.LDAP).count(),
        'local_users': User.objects.filter(auth_source=User.AuthSource.LOCAL).count(),
    }
    recent_users = User.objects.order_by('-created_at')[:5]

    # Registered Device yang Pool ID-nya masih 0 -> belum diaktifkan ke Active
    # Device. Ditampilkan di ringkasan supaya admin gampang lihat & follow-up.
    unactivated_qs = RegisteredDevice.objects.filter(
        DeptID_id=UNREGISTERED_POOL_ID,
    ).order_by('-id')
    unactivated_count = unactivated_qs.count()
    stats['unactivated_devices'] = unactivated_count

    return render(request, 'dashboard/admin_home.html', {
        'stats': stats,
        'recent_users': recent_users,
        'unactivated_devices': unactivated_qs[:5],
        'unactivated_count': unactivated_count,
    })


@staff_required
def user_list(request):
    search = request.GET.get('q', '').strip()
    page_obj = services.paginate_users(search=search, page=request.GET.get('page') or 1, page_size=10)
    return render(request, 'dashboard/user_list.html', {'page_obj': page_obj, 'search': search})


@staff_required
def user_create(request):
    form = LocalUserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.create_local_user(
                request.user,
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password'],
                email=form.cleaned_data['email'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                is_staff=form.cleaned_data['is_staff'],
                emp_id=form.cleaned_data['emp_id'],
            )
        except ServiceError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, 'User lokal berhasil dibuat.')
            return redirect('dashboard:user_list')
    return render(request, 'dashboard/user_form.html', {'form': form, 'mode': 'create'})


@staff_required
def user_edit(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = UserEditForm(request.POST)
        if form.is_valid():
            cleaned = dict(form.cleaned_data)
            cleaned['EmpID'] = cleaned.pop('emp_id')  # map nama field form -> nama field model
            try:
                services.update_user_by_admin(request.user, target.pk, **cleaned)
            except ServiceError as exc:
                messages.error(request, exc.message)
            else:
                messages.success(request, 'Data user berhasil diperbarui.')
                return redirect('dashboard:user_list')
    else:
        form = UserEditForm(initial={
            'email': target.email,
            'first_name': target.first_name,
            'last_name': target.last_name,
            'phone_number': target.phone_number,
            'department': target.department,
            'title': target.title,
            'emp_id': target.EmpID.PIN if target.EmpID_id else '',
        })
    return render(request, 'dashboard/user_form.html', {
        'form': form, 'mode': 'edit', 'target': target,
        'current_employee_label': f'{target.EmpID.PIN} - {target.EmpID.EName}' if target.EmpID_id else '',
    })


@staff_required
@require_POST
def user_delete(request, user_id):
    try:
        services.delete_user(request.user, user_id)
    except ServiceError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, 'User berhasil dihapus.')
    return redirect('dashboard:user_list')


@staff_required
@require_POST
def user_toggle_active(request, user_id):
    try:
        services.toggle_active(request.user, user_id)
    except ServiceError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, 'Status user berhasil diperbarui.')
    return redirect('dashboard:user_list')


@staff_required
def user_reset_password(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    form = AdminResetPasswordForm(request.POST or None)
    generated_password = None
    if request.method == 'POST' and form.is_valid():
        try:
            generated_password = services.reset_password(
                request.user, target.pk, form.cleaned_data.get('new_password') or None,
            )
        except ServiceError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, 'Password berhasil direset.')
    return render(request, 'dashboard/user_reset_password.html', {
        'form': form, 'target': target, 'generated_password': generated_password,
    })


@superuser_required
@require_POST
def user_set_staff(request, user_id):
    is_staff = request.POST.get('is_staff') == '1'
    try:
        services.set_staff_role(request.user, user_id, is_staff)
    except ServiceError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, 'Role user berhasil diperbarui.')
    return redirect('dashboard:user_list')


# Daftar permission fitur terbatas yang bisa diberikan ke user non-staff
# (lihat iclock/models.py::FeaturePermission). Format tuple:
# (full codename 'app_label.codename', codename saja, label buat ditampilkan)
FEATURE_PERMISSIONS = [
    ('iclock.can_transfer_finger', 'can_transfer_finger', 'Transfer Data Finger'),
    ('iclock.can_view_attendance_recap', 'can_view_attendance_recap', 'Rekap Absensi (Attendance Recap)'),
]


@staff_required
def user_manage_permissions(request, user_id):
    """
    "Kelola Izin User" -- admin kasih/cabut izin fitur terbatas (Transfer
    Data Finger, Rekap Absensi) ke user NON-STAFF tertentu, tanpa perlu
    jadikan mereka staff/admin penuh. Dipakai bareng dengan
    `accounts.permissions.permission_or_staff_required` yang mengecek
    permission ini di view-view iclock yang relevan.
    """
    target_user = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        from django.contrib.auth.models import Permission
        for _full_codename, codename, _label in FEATURE_PERMISSIONS:
            perm = Permission.objects.filter(codename=codename, content_type__app_label='iclock').first()
            if not perm:
                continue
            if request.POST.get(codename) == 'on':
                target_user.user_permissions.add(perm)
            else:
                target_user.user_permissions.remove(perm)
        messages.success(request, f"Izin fitur untuk '{target_user.username}' berhasil diperbarui.")
        return redirect('dashboard:user_list')

    # Cek permission EKSPLISIT yang sudah di-assign (bukan lewat has_perm(),
    # supaya tidak ke-'True' otomatis kalau target_user kebetulan staff/
    # superuser -- checkbox di form harus mencerminkan assignment eksplisit
    # sungguhan, bukan hak akses efektifnya).
    feature_perms = [
        (codename, label, target_user.user_permissions.filter(codename=codename, content_type__app_label='iclock').exists())
        for _full_codename, codename, label in FEATURE_PERMISSIONS
    ]
    return render(request, 'dashboard/user_manage_permissions.html', {
        'target_user': target_user,
        'feature_perms': feature_perms,
    })



# ---------------------------------------------------------------------------
# SEMUA USER: profil & ganti password
# ---------------------------------------------------------------------------
def profile(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')

    user = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            services.update_profile(user, **form.cleaned_data)
            messages.success(request, 'Profil berhasil diperbarui.')
            return redirect('dashboard:profile')
    else:
        form = ProfileForm(initial={
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone_number': user.phone_number,
            'department': user.department,
            'title': user.title,
        })
    return render(request, 'dashboard/profile.html', {'form': form})


def profile_change_password(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')

    form = ChangePasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.change_own_password(
                request.user, form.cleaned_data['old_password'], form.cleaned_data['new_password'],
            )
        except ServiceError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, 'Password berhasil diubah.')
            return redirect('dashboard:profile')
    return render(request, 'dashboard/change_password.html', {'form': form})
