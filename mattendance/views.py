from celery.exceptions import TimeoutError as CeleryTimeoutError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.core.paginator import Paginator
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.mobile_backend import mobile_password_needs_change
from accounts.permissions import staff_required

from .function_utils import determine_function_code
from .geofence import find_all_matching_pools_by_polygon, find_matching_pool_by_polygon
from .models import AttendanceLog, FaceProfile
from .qr_utils import get_poolcode_from_qr
from .tasks import extract_face_encoding_task, verify_face_task

PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100]
DEFAULT_PAGE_SIZE = 10

# Batas tunggu hasil task Celery (detik) -- proses face recognition
# NORMALNYA cuma perlu waktu singkat (di bawah 2-3 detik pd hardware wajar),
# tapi kalau worker Celery TIDAK JALAN sama sekali, request akan menunggu
# sampai batas ini baru gagal dgn pesan jelas (bukan hang selamanya).
FACE_TASK_TIMEOUT_SECONDS = 15


def _get_display_name(user) -> str:
    """
    Nama yang ditampilkan di header app mobile -- pakai nama Employee kalau
    user ini terkait 1 (mis. login via PIN, atau staff yang di-link admin),
    fallback ke first_name/username kalau tidak ada.
    """
    if user.EmpID_id and user.EmpID.EName:
        return user.EmpID.EName.strip()
    return user.get_full_name() or user.username


def _get_employee_or_none(user):
    """
    Employee terkait `user` (via User.EmpID), atau None kalau user ini
    tidak terkait Employee manapun -- dipakai SEMUA lookup FaceProfile
    (sekarang diikat ke employee, bukan ke User langsung, lihat catatan
    di FaceProfile model) supaya konsisten & tidak duplikat logic.
    """
    return user.EmpID if user.EmpID_id else None


@login_required
def checkin_test_page(request):
    """
    Halaman check-in/out geofence + face verification -- browser minta
    izin akses GPS & kamera, kirim koordinat + foto wajah ke
    `checkin_submit`. Terbuka utk SEMUA user login (bukan cuma staff),
    karena "mobile attendance" pada dasarnya dipakai karyawan biasa.
    """
    emp = _get_employee_or_none(request.user)
    has_face_profile = FaceProfile.objects.filter(employee=emp).exists() if emp else False
    return render(request, 'mattendance/checkin_test.html', {
        'has_face_profile': has_face_profile,
        'display_name': _get_display_name(request.user),
    })


@login_required
def face_enroll_page(request):
    """
    Halaman enrollment wajah -- mirip proses daftar wajah pertama kali di
    mesin fingerprint ZKTeco yang punya face recognition: user foto
    wajahnya sendiri lewat webcam, sistem simpan "face encoding"-nya
    sebagai referensi. "Pengambilan wajah hanya dilakukan sekali" -- begitu
    berhasil, FaceProfile TERKUNCI (`is_locked`), enrollment ulang mandiri
    TIDAK bisa dilakukan lagi (harus hubungi admin).

    FaceProfile diikat ke EMPLOYEE (bukan User) -- kalau user ini tidak
    terkait Employee manapun (User.EmpID kosong), enrollment TIDAK berlaku
    utk akun ini sama sekali.
    """
    emp = _get_employee_or_none(request.user)
    existing = FaceProfile.objects.filter(employee=emp).first() if emp else None
    return render(request, 'mattendance/face_enroll.html', {
        'no_employee_linked': emp is None,
        'already_enrolled': existing is not None,
        'enrolled_at': existing.enrolled_at if existing else None,
        'is_locked': existing.is_locked if existing else False,
        'display_name': _get_display_name(request.user),
    })


@login_required
@require_POST
def face_enroll_submit(request):
    """
    Terima foto wajah (base64 dari <canvas> browser) hasil capture webcam,
    lempar ekstraksi face encoding-nya ke CELERY WORKER (proses CPU-intensive
    dlib, tidak dikerjakan langsung di proses Django ini -- lihat
    mattendance/tasks.py), simpan sebagai FaceProfile milik EMPLOYEE
    terkait user yang login (BUKAN milik User itu sendiri -- lihat catatan
    di FaceProfile model, supaya 1 kali enrollment berlaku bersama utk
    SEMUA akun User yang ter-link ke employee yang sama) -- MENGGANTI
    encoding lama kalau sebelumnya sudah pernah enroll.

    "Pengambilan wajah hanya dilakukan sekali" -- begitu 1 kali enrollment
    berhasil, FaceProfile otomatis TERKUNCI (`is_locked=True`). Selama
    terkunci, user TIDAK BISA enroll ulang sendiri -- harus hubungi admin
    (buka kunci lewat halaman Face Profile, atau hapus profilnya).

    Kalau `settings.PREVENT_DUPLICATE_FACE` True, wajah baru ini JUGA
    dibandingkan terhadap wajah SEMUA employee LAIN yang sudah terdaftar
    (enrollment ulang wajah SENDIRI tetap selalu diizinkan selama belum
    terkunci, tidak terkena pengecekan ini) -- kalau ketemu yang mirip,
    enrollment DITOLAK.
    """
    emp = _get_employee_or_none(request.user)
    if emp is None:
        return JsonResponse({
            'success': False,
            'message': 'Akun ini tidak terkait data Employee manapun -- enrollment wajah tidak berlaku, hubungi admin.',
        })

    existing_profile = FaceProfile.objects.filter(employee=emp).first()
    if existing_profile and existing_profile.is_locked:
        return JsonResponse({
            'success': False,
            'message': 'Wajah Anda sudah terdaftar & terkunci -- hubungi admin untuk mendaftar ulang.',
        })

    face_image_data = request.POST.get('face_image', '').strip()
    if not face_image_data:
        return JsonResponse({'success': False, 'message': 'Foto wajah tidak dikirim -- pastikan kamera aktif.'}, status=400)

    existing_encodings = None
    if settings.PREVENT_DUPLICATE_FACE:
        existing_encodings = list(
            FaceProfile.objects.exclude(employee=emp).values('employee_id', 'encoding')
        )
        # Samakan nama key sesuai yang diharapkan task (lihat mattendance/tasks.py).
        existing_encodings = [{'employee_id': e['employee_id'], 'encoding': e['encoding']} for e in existing_encodings]

    try:
        result = extract_face_encoding_task.delay(
            face_image_data, existing_encodings=existing_encodings,
        ).get(timeout=FACE_TASK_TIMEOUT_SECONDS)
    except CeleryTimeoutError:
        return JsonResponse({
            'success': False,
            'message': 'Proses pendaftaran wajah memakan waktu terlalu lama -- coba lagi, atau hubungi admin (kemungkinan worker Celery belum jalan).',
        })
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({
            'success': False,
            'message': f'Gagal memproses wajah (kemungkinan worker Celery belum jalan): {exc}',
        })

    if not result['success']:
        return JsonResponse({'success': False, 'message': result['error']})

    if result.get('duplicate_employee_id'):
        # SENGAJA tidak menyebutkan siapa pemilik wajah yang duplikat --
        # menghindari kebocoran informasi soal identitas employee lain.
        return JsonResponse({
            'success': False,
            'message': 'Wajah ini sudah terdaftar untuk employee lain -- pendaftaran ditolak.',
        })

    encoding = result['encoding']

    _profile, created = FaceProfile.objects.update_or_create(
        employee=emp,
        defaults={'encoding': encoding, 'is_locked': True},
    )

    action = 'didaftarkan' if created else 'diperbarui'
    return JsonResponse({'success': True, 'message': f'Wajah berhasil {action} & terkunci. Sekarang Anda bisa check-in/out dengan verifikasi wajah.'})


@login_required
@require_POST
def checkin_submit(request):
    """
    Terima koordinat GPS + foto wajah dari browser, verifikasi DUA-DUANYA:
    1. Geofence POLYGON (MobilePoolLoc, lihat mattendance/geofence.py::
       find_matching_pool_by_polygon).
    2. Wajah (dibandingkan terhadap FaceProfile yang sudah di-enroll user
       ini, lihat mattendance/face_utils.py::verify_face).

    Sesuai prinsip yang sudah dipakai sejak geofence-only sebelumnya: HANYA
    dicatat ke AttendanceLog kalau SEMUA verifikasi berhasil -- percobaan
    yang gagal (lokasi ATAU wajah tidak cocok) TIDAK dicatat, cuma
    dikembalikan pesan gagal yang jelas soal mana yang gagal.

    Kalau user belum pernah enroll wajah sama sekali, diminta enroll dulu
    (`needs_enrollment: true` di response, ditangani JS utk redirect).
    """
    try:
        latitude = float(request.POST.get('latitude'))
        longitude = float(request.POST.get('longitude'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Koordinat GPS tidak valid atau tidak dikirim.'}, status=400)

    face_image_data = request.POST.get('face_image', '').strip()
    if not face_image_data:
        return JsonResponse({'success': False, 'message': 'Foto wajah tidak dikirim -- pastikan kamera aktif & ambil foto dulu.'}, status=400)

    check_type = request.POST.get('check_type', 'IN')
    if check_type not in (AttendanceLog.CheckType.IN, AttendanceLog.CheckType.OUT):
        check_type = AttendanceLog.CheckType.IN

    emp = _get_employee_or_none(request.user)
    face_profile = FaceProfile.objects.filter(employee=emp).first() if emp else None
    if face_profile is None:
        return JsonResponse({
            'success': False,
            'needs_enrollment': True,
            'message': 'Anda belum mendaftarkan wajah. Silakan lakukan pendaftaran wajah (enrollment) terlebih dahulu.',
        })

    pool = find_matching_pool_by_polygon(latitude, longitude)
    if pool is None:
        return JsonResponse({
            'success': False,
            'message': 'Lokasi Anda tidak berada di dalam area (polygon) pool manapun -- check-in/out TIDAK dicatat.',
        })

    try:
        result = verify_face_task.delay(face_image_data, face_profile.encoding).get(timeout=FACE_TASK_TIMEOUT_SECONDS)
    except CeleryTimeoutError:
        return JsonResponse({
            'success': False,
            'message': 'Proses verifikasi wajah memakan waktu terlalu lama -- coba lagi, atau hubungi admin (kemungkinan worker Celery belum jalan).',
        })
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({
            'success': False,
            'message': f'Gagal memproses wajah (kemungkinan worker Celery belum jalan): {exc}',
        })

    if not result['success']:
        return JsonResponse({'success': False, 'message': f"Verifikasi wajah gagal: {result['error']}"})

    face_matched, face_dist = result['matched'], result['distance']

    if not face_matched:
        return JsonResponse({
            'success': False,
            'message': f'Wajah tidak cocok dengan yang terdaftar (jarak {face_dist:.3f}) -- check-in/out TIDAK dicatat.',
        })

    # Kode fungsi: cek KANTIN dulu (prioritas tertinggi), fallback ke
    # prefix digit pertama PIN employee yang terkait user ini (lihat
    # mattendance/function_utils.py::determine_function_code) -- PIN
    # diambil dari User.EmpID (kalau user ini tidak ada Employee terkait,
    # fallback prefix PIN otomatis dilewati, tapi cek KANTIN tetap jalan).
    emp_pin = request.user.EmpID.PIN if request.user.EmpID_id else None
    function_code = determine_function_code(emp_pin, pool)

    log = AttendanceLog.objects.create(
        user=request.user,
        PoolID=pool,
        check_type=check_type,
        latitude=latitude,
        longitude=longitude,
        distance_meters=None,  # tidak relevan lagi utk geofence polygon
        location_verified=True,
        face_verified=True,
        face_distance=face_dist,
        Function=f'{function_code}-{pool.PoolID}' if function_code else None,
    )

    label = 'Check-in' if check_type == AttendanceLog.CheckType.IN else 'Check-out'
    return JsonResponse({
        'success': True,
        'message': f'{label} berhasil di {pool.PoolName or pool.PoolID} (lokasi & wajah terverifikasi).',
        'pool_name': pool.PoolName,
        'pool_id': pool.PoolID,
        'log_id': log.id,
    })


@login_required
def checkin_meal_page(request):
    """
    Halaman Check/Meal (absen makan siang) -- verifikasi GPS + QR CODE
    (BUKAN wajah, beda dgn check-in/out reguler). Browser minta izin akses
    GPS & kamera (utk scan QR code, pakai library jsQR dari CDN).
    """
    return render(request, 'mattendance/checkin_meal.html', {
        'display_name': _get_display_name(request.user),
    })


@login_required
@require_POST
def checkin_meal_submit(request):
    """
    Terima koordinat GPS + ISI QR CODE hasil scan dari browser. Verifikasi:
    1. Isi QR dikenali (ada di settings.QRDEVICE) -> dapat PoolCode.
    2. Lokasi GPS user cocok dgn geofence SALAH SATU MobilePool (bisa lebih
       dari 1 kalau ada overlap geofence yg berdekatan, lihat
       mattendance/geofence.py::find_all_matching_pools_by_polygon) -- di
       antara yang cocok, cari yang PoolCode-nya PERSIS SAMA dengan hasil
       dari QR. Inilah cara QR "disambiguasi" geofence yang overlap.

    Sesuai prinsip yang sama dgn check-in/out reguler: HANYA dicatat ke
    AttendanceLog kalau SEMUA verifikasi berhasil. `face_verified` selalu
    False (Check/Meal tidak pakai verifikasi wajah).
    """
    try:
        latitude = float(request.POST.get('latitude'))
        longitude = float(request.POST.get('longitude'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Koordinat GPS tidak valid atau tidak dikirim.'}, status=400)

    qr_content = request.POST.get('qr_content', '').strip()
    if not qr_content:
        return JsonResponse({'success': False, 'message': 'Isi QR code tidak dikirim -- pastikan QR berhasil ter-scan.'}, status=400)

    poolcode = get_poolcode_from_qr(qr_content)
    if poolcode is None:
        return JsonResponse({
            'success': False,
            'message': f"QR code '{qr_content}' tidak dikenali/tidak terdaftar -- Check/Meal TIDAK dicatat.",
        })

    candidates = find_all_matching_pools_by_polygon(latitude, longitude)

    # Batasi kandidat HANYA ke pool yang PoolCode-nya TERDAFTAR di
    # settings.QRDEVICE (yakni benar-benar dikonfigurasi sbg lokasi
    # kantin) -- SEBELUM dicocokkan ke QR spesifik yang di-scan. Tanpa
    # filter ini, secara teknis titik user bisa "kebetulan" match geofence
    # yang TIDAK PERNAH dimaksudkan utk Check/Meal sama sekali (mis. area
    # kantor biasa) -- filter ini menegaskan geofence-nya HARUS memang
    # geofence kantin yang terdaftar, bukan geofence apa pun.
    registered_poolcodes = set(getattr(settings, 'QRDEVICE', {}).keys())
    candidates = [p for p in candidates if p.PoolCode in registered_poolcodes]

    if not candidates:
        return JsonResponse({
            'success': False,
            'message': 'Lokasi Anda tidak berada di area kantin manapun yang terdaftar (settings.QRDEVICE) -- Check/Meal TIDAK dicatat.',
        })

    matched_pool = next((p for p in candidates if p.PoolCode == poolcode), None)
    if matched_pool is None:
        return JsonResponse({
            'success': False,
            'message': (
                f"Lokasi GPS Anda tidak cocok dengan QR yang di-scan (PoolCode '{poolcode}') -- "
                f"Check/Meal TIDAK dicatat. Pastikan Anda berada di area kantin yang sesuai dengan QR-nya."
            ),
        })

    # Kode fungsi: pola SAMA dgn check-in/out reguler (cek KANTIN dulu,
    # fallback prefix PIN) -- SECARA UMUM pool yang match QR Check/Meal
    # akan terdaftar KANTIN, jadi hasilnya 'X', TAPI kalau admin belum
    # sempat memetakan pool itu sbg KANTIN di PoolDeviceFunction, tetap
    # fallback ke prefix PIN (konsisten dgn urutan prioritas yang diminta,
    # bukan dipaksa 'X' begitu saja hanya karena ini alur Check/Meal).
    emp_pin = request.user.EmpID.PIN if request.user.EmpID_id else None
    function_code = determine_function_code(emp_pin, matched_pool)

    log = AttendanceLog.objects.create(
        user=request.user,
        PoolID=matched_pool,
        check_type=AttendanceLog.CheckType.MEAL,
        latitude=latitude,
        longitude=longitude,
        distance_meters=None,
        location_verified=True,
        face_verified=False,
        qr_content=qr_content,
        Function=f'{function_code}-{matched_pool.PoolID}' if function_code else None,
    )

    return JsonResponse({
        'success': True,
        'message': f'Check/Meal berhasil di {matched_pool.PoolName or matched_pool.PoolID}.',
        'pool_name': matched_pool.PoolName,
        'pool_id': matched_pool.PoolID,
        'log_id': log.id,
    })


@staff_required
def attendance_log_list(request):
    """
    Daftar AttendanceLog -- utk admin memantau/verifikasi hasil testing
    check-in/out geofence. Read-only, search + sort + pagination standar.
    """
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'timestamp')
    if sort_key not in ['timestamp', 'user__username', 'PoolID__PoolName', 'check_type']:
        sort_key = 'timestamp'
    direction = request.GET.get('dir', 'desc') if request.GET.get('dir') in ('asc', 'desc') else 'desc'
    page_size = _resolve_page_size(request)

    qs = AttendanceLog.objects.select_related('user', 'PoolID').all()
    if search:
        qs = (
            qs.filter(user__username__icontains=search)
            | qs.filter(user__first_name__icontains=search)
            | qs.filter(user__last_name__icontains=search)
            | qs.filter(PoolID__PoolName__icontains=search)
        )

    order_field = sort_key if direction == 'asc' else f'-{sort_key}'
    qs = qs.order_by(order_field, '-timestamp')

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page') or 1)
    sort_urls = {
        col: _build_sort_url(request, col, sort_key, direction)
        for col in ['timestamp', 'user__username', 'PoolID__PoolName', 'check_type']
    }

    return render(request, 'mattendance/attendance_log_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
@require_POST
def attendance_log_delete(request, pk):
    """
    Hapus 1 record AttendanceLog secara permanen -- staff-only. Berguna
    khusus utk log "yatim" (PoolID sudah NULL karena MobilePool sumbernya
    dihapus) yang mungkin ingin dibersihkan, tapi bisa dipakai utk log
    manapun (tidak dibatasi cuma yang PoolID-nya NULL).
    """
    log = get_object_or_404(AttendanceLog, pk=pk)
    log.delete()
    messages.success(request, 'Log attendance berhasil dihapus.')
    return redirect('mattendance:attendance_log_list')


def _resolve_page_size(request):
    try:
        page_size = int(request.GET.get('page_size', DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return page_size if page_size in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE


def _build_sort_url(request, field, current_sort, current_dir):
    """URL utk header kolom yang bisa diklik: toggle asc/desc, reset ke halaman 1, pertahankan filter lain."""
    new_dir = 'desc' if (current_sort == field and current_dir == 'asc') else 'asc'
    params = request.GET.copy()
    params['sort'] = field
    params['dir'] = new_dir
    params.pop('page', None)
    return f'?{params.urlencode()}'


def mobile_login_page(request):
    """
    Halaman login KHUSUS Mobile Attendance -- pakai PIN Employee + password
    mobile (BUKAN username/password akun accounts.User biasa, lihat
    accounts/mobile_backend.py). Employee BISA login TANPA harus sudah
    punya akun accounts.User -- akun "mobile-only" dibuat otomatis begitu
    autentikasi berhasil.
    """
    if request.user.is_authenticated:
        return redirect('mattendance:checkin_test_page')
    return render(request, 'mattendance/mobile_login.html')


@require_POST
def mobile_login_submit(request):
    pin = request.POST.get('pin', '').strip()
    mobile_password = request.POST.get('mobile_password', '')

    if not pin or not mobile_password:
        messages.error(request, 'PIN dan password wajib diisi.')
        return redirect('mattendance:mobile_login_page')

    user = authenticate(request, pin=pin, mobile_password=mobile_password)
    if user is None:
        messages.error(request, 'PIN atau password salah.')
        return redirect('mattendance:mobile_login_page')

    login(request, user)
    # MobileAccessMiddleware otomatis redirect ke halaman ganti password
    # kalau password mobile-nya masih default -- di sini cukup arahkan ke
    # check-in, middleware yang akan intercept kalau perlu.
    return redirect('mattendance:checkin_test_page')


@login_required
def mobile_profile_page(request):
    """
    Halaman "Profil" (tab bar mobile app) -- info ringkas Employee terkait
    user mobile-only yang login, plus link ganti password & logout.
    HANYA relevan utk user mobile-only (redirect ke dashboard staff kalau
    diakses user reguler, sama seperti mobile_change_password_page).
    """
    if not getattr(request.user, 'is_mobile_only', False):
        return redirect('dashboard:index')
    return render(request, 'mattendance/mobile_profile.html', {
        'display_name': _get_display_name(request.user),
        'emp': request.user.EmpID,
    })


@login_required
def mobile_change_password_page(request):
    """Halaman ganti password mobile -- HANYA relevan utk user mobile-only."""
    if not getattr(request.user, 'is_mobile_only', False):
        return redirect('dashboard:index')
    return render(request, 'mattendance/mobile_change_password.html', {
        'display_name': _get_display_name(request.user),
    })


@login_required
@require_POST
def mobile_change_password_submit(request):
    """
    Ganti password mobile Employee terkait user mobile-only yang login.
    WAJIB tidak kosong DAN tidak sama dengan password default
    (settings.MOBILE_DEFAULT_PASSWORD) -- disimpan sebagai HASH (Django
    password hasher standar), bukan plaintext.
    """
    if not getattr(request.user, 'is_mobile_only', False):
        return redirect('dashboard:index')

    new_password = request.POST.get('new_password', '')
    confirm_password = request.POST.get('confirm_password', '')
    default_password = getattr(settings, 'MOBILE_DEFAULT_PASSWORD', '123456')

    if not new_password:
        messages.error(request, 'Password baru wajib diisi.')
        return redirect('mattendance:mobile_change_password_page')
    if new_password == default_password:
        messages.error(request, f"Password baru tidak boleh sama dengan password default ('{default_password}').")
        return redirect('mattendance:mobile_change_password_page')
    if new_password != confirm_password:
        messages.error(request, 'Konfirmasi password tidak cocok.')
        return redirect('mattendance:mobile_change_password_page')

    emp = request.user.EmpID
    if emp is None:
        messages.error(request, 'Akun ini tidak terkait data Employee manapun -- hubungi admin.')
        return redirect('mattendance:mobile_login_page')

    emp.mpassword = make_password(new_password)
    emp.save(update_fields=['mpassword'])
    messages.success(request, 'Password berhasil diganti.')
    return redirect('mattendance:checkin_test_page')


@staff_required
def face_profile_admin_list(request):
    """
    "Face Profile" -- daftar SEMUA FaceProfile untuk admin, dengan aksi
    buka-kunci ("ReadOnly") & hapus. "Pengambilan wajah hanya dilakukan
    sekali" -- begitu 1 kali enrollment berhasil, otomatis TERKUNCI; kalau
    employee legitimately butuh enroll ulang, admin yang buka kunci atau
    hapus profilnya dari sini (bukan bisa dilakukan mandiri oleh user).

    Diikat ke EMPLOYEE (bukan User) -- kolom PIN/nama employee ditampilkan
    langsung di tabel.
    """
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'updated_at')
    if sort_key not in ['employee__PIN', 'is_locked', 'enrolled_at', 'updated_at']:
        sort_key = 'updated_at'
    direction = request.GET.get('dir', 'desc') if request.GET.get('dir') in ('asc', 'desc') else 'desc'
    page_size = _resolve_page_size(request)

    qs = FaceProfile.objects.select_related('employee').all()
    if search:
        qs = qs.filter(models.Q(employee__PIN__icontains=search) | models.Q(employee__EName__icontains=search))

    order_field = sort_key if direction == 'asc' else f'-{sort_key}'
    qs = qs.order_by(order_field)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page') or 1)
    sort_urls = {
        col: _build_sort_url(request, col, sort_key, direction)
        for col in ['employee__PIN', 'is_locked', 'enrolled_at', 'updated_at']
    }

    return render(request, 'mattendance/face_profile_admin_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
@require_POST
def face_profile_toggle_lock(request, pk):
    """Buka/kunci (toggle ReadOnly) 1 FaceProfile -- staff-only."""
    profile = get_object_or_404(FaceProfile, pk=pk)
    profile.is_locked = not profile.is_locked
    profile.save(update_fields=['is_locked'])
    status = 'dikunci' if profile.is_locked else 'dibuka kuncinya'
    messages.success(request, f"Face Profile milik PIN '{profile.employee.PIN}' berhasil {status}.")
    return redirect('mattendance:face_profile_admin_list')


@staff_required
@require_POST
def face_profile_admin_delete(request, pk):
    """Hapus 1 FaceProfile secara permanen -- staff-only, membuka jalan employee enroll ulang dari nol."""
    profile = get_object_or_404(FaceProfile, pk=pk)
    pin = profile.employee.PIN
    profile.delete()
    messages.success(request, f"Face Profile milik PIN '{pin}' berhasil dihapus. Employee bisa enroll ulang.")
    return redirect('mattendance:face_profile_admin_list')


@login_required
def attendance_history_page(request):
    """
    Tab "Log History" -- riwayat check-in/out/meal MILIK USER YANG LOGIN
    SENDIRI (BEDA dari attendance_log_list yang staff-only & tampilkan
    SEMUA user). Setelah check-in/out/meal berhasil, browser diarahkan ke
    sini supaya user langsung lihat riwayatnya ter-update.
    """
    qs = AttendanceLog.objects.filter(user=request.user).select_related('PoolID').order_by('-timestamp')
    page_size = _resolve_page_size(request)
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page') or 1)

    return render(request, 'mattendance/attendance_history.html', {
        'page_obj': page_obj,
        'display_name': _get_display_name(request.user),
    })
