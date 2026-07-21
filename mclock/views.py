import json

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import staff_required

from .forms import MobilePoolForm, MobilePoolLocForm, PoolDeviceFunctionForm
from .models import MobilePool, MobilePoolLoc, PoolDeviceFunction
from .mssql_client import MSSQLConnectionError, fetch_paginated_from_sql, get_mssql_connection
from .pagination import SimplePage
from .sources import (
    MOBILE_ATTENDANCE_COLUMNS,
    MOBILE_ATTENDANCE_SEARCH_COLUMN,
    MOBILE_ATTENDANCE_SOURCES,
    MOBILE_ATTENDANCE_UNIQUE_TARGETS,
)

PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100]
DEFAULT_PAGE_SIZE = 10


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


@staff_required
def mobile_attendance_home(request):
    """
    Halaman utama "Mobile Attendance" -- daftar semua submenu (sumber data)
    yang tersedia, plus tombol test koneksi ke tiap kombinasi server/database
    MSSQL yang dipakai (bisa beda-beda per submenu, walau kredensialnya sama).
    """
    settings_complete = all([
        settings.MCLOCK_MSSQL_USERNAME,
        settings.MCLOCK_MSSQL_PASSWORD_ENCRYPTED,
        settings.MCLOCK_ENCRYPTION_KEY,
    ])

    connection_results = None
    if request.GET.get('test_connection') == '1':
        connection_results = []
        for server, database in MOBILE_ATTENDANCE_UNIQUE_TARGETS:
            # Cari tds_version dari source manapun yang cocok server+database-nya
            # (kalau ada beberapa source share server/database yang sama,
            # tds_version-nya wajar sama juga -- ambil dari yang pertama ketemu).
            tds_version = next(
                (cfg.get('tds_version') for cfg in MOBILE_ATTENDANCE_SOURCES.values()
                 if cfg['server'] == server and cfg['database'] == database),
                None,
            )
            try:
                conn = get_mssql_connection(server=server, database=database, tds_version=tds_version)
                conn.close()
                connection_results.append({'server': server, 'database': database, 'ok': True, 'error': None})
            except MSSQLConnectionError as exc:
                connection_results.append({'server': server, 'database': database, 'ok': False, 'error': str(exc)})

    sources = [
        {'slug': slug, 'title': cfg['title'], 'server': cfg['server'], 'database': cfg['database']}
        for slug, cfg in MOBILE_ATTENDANCE_SOURCES.items()
    ]

    return render(request, 'mclock/mobile_attendance_home.html', {
        'settings_complete': settings_complete,
        'connection_results': connection_results,
        'sources': sources,
    })


@staff_required
def mobile_attendance_table(request, slug):
    """
    Tabel data Mobile Attendance utk SATU sumber data (submenu) --
    read-only murni, TANPA edit/aksi apapun. Search (kolom 'nik'), sort,
    dan pagination semuanya dijalankan SERVER-SIDE di MSSQL (bukan fetch
    semua baris ke Python lalu paginate manual) supaya tetap ringan walau
    datanya banyak.
    """
    source = MOBILE_ATTENDANCE_SOURCES.get(slug)
    if not source:
        raise Http404(f"Submenu Mobile Attendance '{slug}' tidak dikenal.")

    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'ttime')
    if sort_key not in MOBILE_ATTENDANCE_COLUMNS:
        sort_key = 'ttime'
    direction = request.GET.get('dir', 'desc') if request.GET.get('dir') in ('asc', 'desc') else 'desc'

    try:
        page = int(request.GET.get('page', 1) or 1)
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    page_size = _resolve_page_size(request)

    error = None
    rows = []
    total_count = 0
    try:
        rows, total_count = fetch_paginated_from_sql(
            base_sql=source['base_sql'],
            server=source['server'],
            database=source['database'],
            search_column=MOBILE_ATTENDANCE_SEARCH_COLUMN,
            search_term=search,
            sort_column=sort_key,
            sort_direction=direction,
            page=page,
            page_size=page_size,
            tds_version=source.get('tds_version'),
        )
    except MSSQLConnectionError as exc:
        error = str(exc)

    page_obj = SimplePage(rows, page, total_count, page_size)
    sort_urls = {col: _build_sort_url(request, col, sort_key, direction) for col in MOBILE_ATTENDANCE_COLUMNS}

    return render(request, 'mclock/mobile_attendance_table.html', {
        'slug': slug,
        'source': source,
        'sources': [
            {'slug': s, 'title': cfg['title']} for s, cfg in MOBILE_ATTENDANCE_SOURCES.items()
        ],
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'error': error,
    })


@staff_required
def mobile_pool_list(request):
    """
    "Mobile Pool" -- daftar pool/lokasi yang sudah DISINKRONKAN dari MSSQL ke
    tabel lokal `MobilePool` (lewat management command `sync_mobile_pool`).
    BEDA dari submenu Mobile Attendance lain: ini baca dari database Django
    sendiri (pakai Django ORM biasa), bukan langsung ke MSSQL setiap request.
    """
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'PoolID')
    if sort_key not in ['PoolID', 'PoolCode', 'PoolName', 'Radius', 'SyncedAt']:
        sort_key = 'PoolID'
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)

    qs = MobilePool.objects.all()
    if search:
        qs = qs.filter(PoolID__icontains=search) | qs.filter(PoolCode__icontains=search) | qs.filter(PoolName__icontains=search)

    order_field = sort_key if direction == 'asc' else f'-{sort_key}'
    qs = qs.order_by(order_field, 'PoolID')

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page') or 1)
    sort_urls = {
        col: _build_sort_url(request, col, sort_key, direction)
        for col in ['PoolID', 'PoolCode', 'PoolName', 'Radius', 'SyncedAt']
    }

    last_synced = MobilePool.objects.order_by('-SyncedAt').values_list('SyncedAt', flat=True).first()

    return render(request, 'mclock/mobile_pool_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'last_synced': last_synced,
    })


@staff_required
def mobile_pool_add(request):
    """
    Tambah 1 MobilePool MANUAL -- BUKAN alur normal (seharusnya lewat
    `sync_mobile_pool`), murni utk keperluan TESTING (mis. bikin pool
    percobaan buat coba check-in/out). Data manual ini akan HILANG/TERTIMPA
    begitu sinkronisasi berikutnya jalan (mirror penuh).
    """
    form = MobilePoolForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f"MobilePool '{form.cleaned_data['PoolID']}' berhasil ditambahkan.")
        return redirect('mclock:mobile_pool_list')
    return render(request, 'mclock/mobile_pool_form.html', {'form': form})


@staff_required
@require_POST
def mobile_pool_delete(request, pool_id):
    """Hapus 1 MobilePool secara permanen -- staff-only."""
    pool = get_object_or_404(MobilePool, pk=pool_id)
    pool.delete()
    messages.success(request, f"MobilePool '{pool_id}' berhasil dihapus.")
    return redirect('mclock:mobile_pool_list')


@staff_required
def mobile_pool_loc_list(request):
    """
    "Mobile Pool Location (Polygon)" -- daftar titik-titik polygon geofence
    yang sudah disinkronkan dari MSSQL (tabel `MobilePoolLoc`, lewat
    management command `sync_mobile_pool_loc`).

    Di-GROUP per PoolID (1 baris per polygon/PoolID, bukan 1 baris per
    titik) supaya tidak terlalu panjang -- klik "Lihat Detail" utk expand
    semua titik (Urut, Latitude, Longitude) milik PoolID itu, sama seperti
    pola grouping di Fingerprint Template (iclock).
    """
    from django.db.models import Count, Max

    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'PoolID')
    if sort_key not in ['PoolID', 'point_count', 'latest_synced']:
        sort_key = 'PoolID'
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)

    base_qs = MobilePoolLoc.objects.all()
    if search:
        base_qs = base_qs.filter(PoolID__icontains=search)

    grouped_qs = (
        base_qs.values('PoolID')
        .annotate(point_count=Count('id'), latest_synced=Max('SyncedAt'))
    )
    order_field = sort_key if direction == 'asc' else f'-{sort_key}'
    grouped_qs = grouped_qs.order_by(order_field, 'PoolID')

    paginator = Paginator(grouped_qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page') or 1)
    sort_urls = {
        col: _build_sort_url(request, col, sort_key, direction)
        for col in ['PoolID', 'point_count', 'latest_synced']
    }

    # Detail titik-titik HANYA diambil utk PoolID yang tampil di halaman aktif.
    page_pool_ids = [row['PoolID'] for row in page_obj.object_list]
    points_by_pool = {}
    if page_pool_ids:
        detail_qs = MobilePoolLoc.objects.filter(PoolID__in=page_pool_ids).order_by('PoolID', 'Urut')
        for point in detail_qs:
            points_by_pool.setdefault(point.PoolID, []).append(point)

    # Ambil PoolName dari MobilePool (lookup) kalau ada, utk ditampilkan
    # bareng PoolID -- murni informatif, tidak wajib ada.
    pool_names = dict(MobilePool.objects.filter(PoolID__in=page_pool_ids).values_list('PoolID', 'PoolName'))

    start_no = page_obj.start_index() if page_pool_ids else 0
    rows = []
    for i, group in enumerate(page_obj.object_list):
        pool_id = group['PoolID']
        rows.append({
            'no': start_no + i,
            'pool_id': pool_id,
            'pool_name': pool_names.get(pool_id),
            'point_count': group['point_count'],
            'latest_synced': group['latest_synced'],
            'points': points_by_pool.get(pool_id, []),
        })

    return render(request, 'mclock/mobile_pool_loc_list.html', {
        'page_obj': page_obj,
        'rows': rows,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
def mobile_pool_loc_add(request):
    """
    Tambah 1 TITIK polygon MANUAL ke MobilePoolLoc -- murni utk TESTING
    (bikin geofence percobaan). Data manual ini akan HILANG/TERTIMPA begitu
    `sync_mobile_pool_loc` jalan lagi (mirror penuh). Utk bikin 1 polygon
    lengkap, tambahkan MINIMAL 3 titik dengan PoolID yang SAMA satu-satu
    lewat form ini (Urut berbeda tiap titik).
    """
    form = MobilePoolLocForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(
            request,
            f"Titik #{form.cleaned_data['Urut']} utk PoolID '{form.cleaned_data['PoolID']}' berhasil ditambahkan. "
            f"Tambahkan minimal 3 titik dgn PoolID yang sama supaya jadi polygon valid.",
        )
        return redirect('mclock:mobile_pool_loc_add')
    return render(request, 'mclock/mobile_pool_loc_form.html', {'form': form})


@staff_required
def mobile_pool_loc_draw(request, pool_id=None):
    """
    "Gambar Polygon di Peta" -- alternatif yang JAUH lebih praktis dari
    mobile_pool_loc_add (ketik koordinat manual satu-satu): admin klik
    titik-titik LANGSUNG di Google Maps, urutan klik otomatis jadi urutan
    keliling polygon, submit sekali jadi semua titik.

    Kalau `pool_id` diisi DAN sudah ada titik tersimpan -- titik yang SUDAH
    ADA dimuat ke peta sbg polygon yang bisa diedit (tambah/hapus/geser
    titik), bukan mulai dari kosong. Simpan MENGGANTI SELURUH titik lama
    milik PoolID ini (replace-all, bukan tambah) -- sesuai sifat data ini
    yang "murni testing, akan tertimpa sync" (sama seperti mobile_pool_loc_add).
    """
    existing_points = []
    if pool_id:
        existing_points = list(
            MobilePoolLoc.objects.filter(PoolID=pool_id).order_by('Urut').values('Latitude', 'Longitude')
        )

    known_pool_ids = list(MobilePool.objects.order_by('PoolID').values_list('PoolID', 'PoolName'))

    return render(request, 'mclock/mobile_pool_loc_draw.html', {
        'pool_id': pool_id or '',
        'existing_points_json': json.dumps(existing_points),
        'known_pool_ids': known_pool_ids,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    })


@staff_required
@require_POST
def mobile_pool_loc_draw_save(request, pool_id):
    """
    Simpan HASIL gambar polygon dari peta -- body POST berisi `points`
    (JSON array [{lat, lng}, ...], urutan klik = urutan Urut). MENGGANTI
    SELURUH titik lama milik PoolID ini (delete semua, insert ulang sesuai
    urutan baru) -- supaya hapus titik di peta juga tersimpan benar (bukan
    cuma tambah/update).
    """
    pool_id = pool_id.strip()
    if not pool_id:
        return JsonResponse({'success': False, 'message': "PoolID wajib diisi."}, status=400)

    try:
        points = json.loads(request.POST.get('points', '[]'))
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'message': "Data titik tidak valid (bukan JSON)."}, status=400)

    if len(points) < 3:
        return JsonResponse({'success': False, 'message': f"Minimal 3 titik utk jadi polygon valid (sekarang {len(points)})."}, status=400)

    try:
        cleaned_points = [(float(p['lat']), float(p['lng'])) for p in points]
    except (KeyError, TypeError, ValueError):
        return JsonResponse({'success': False, 'message': "Format titik tidak valid -- tiap titik butuh 'lat' & 'lng' numerik."}, status=400)

    MobilePoolLoc.objects.filter(PoolID=pool_id).delete()
    MobilePoolLoc.objects.bulk_create([
        MobilePoolLoc(PoolID=pool_id, Urut=i + 1, Latitude=str(lat), Longitude=str(lng))
        for i, (lat, lng) in enumerate(cleaned_points)
    ])

    return JsonResponse({'success': True, 'message': f"Polygon PoolID '{pool_id}' tersimpan ({len(cleaned_points)} titik).", 'count': len(cleaned_points)})


@staff_required
@require_POST
def mobile_pool_loc_delete(request, pk):
    """Hapus 1 TITIK polygon secara permanen -- staff-only."""
    point = get_object_or_404(MobilePoolLoc, pk=pk)
    messages.success(request, f"Titik #{point.Urut} milik PoolID '{point.PoolID}' berhasil dihapus.")
    point.delete()
    return redirect('mclock:mobile_pool_loc_list')


@staff_required
@require_POST
def mobile_pool_loc_delete_pool(request, pool_id):
    """
    Hapus SEMUA titik polygon milik 1 PoolID sekaligus (bukan 1 titik saja)
    -- kemudahan utk bersihkan 1 polygon percobaan penuh sekali klik.
    """
    deleted_count, _ = MobilePoolLoc.objects.filter(PoolID=pool_id).delete()
    messages.success(request, f"{deleted_count} titik milik PoolID '{pool_id}' berhasil dihapus.")
    return redirect('mclock:mobile_pool_loc_list')


@staff_required
def pool_device_function_list(request):
    """
    "Pool Device Function" -- kelola mapping PoolID -> KANTIN/Bukan KANTIN.
    BEDA dari Mobile Pool/Mobile Pool Location (yang disinkronkan dari
    MSSQL): tabel ini SENGAJA TIDAK disinkronkan dari mana pun, murni
    dikelola manual di sini -- dipakai `mattendance` utk menentukan kode
    fungsi (settings.DEVICEFUNCTION) tiap check-in/out/meal (cek KANTIN
    dulu sbg prioritas tertinggi, baru fallback ke prefix PIN).
    """
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'PoolID')
    if sort_key not in ['PoolID', 'function_type', 'updated_at']:
        sort_key = 'PoolID'
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)

    qs = PoolDeviceFunction.objects.all()
    if search:
        qs = qs.filter(PoolID__icontains=search)

    order_field = sort_key if direction == 'asc' else f'-{sort_key}'
    qs = qs.order_by(order_field, 'PoolID')

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page') or 1)
    sort_urls = {
        col: _build_sort_url(request, col, sort_key, direction)
        for col in ['PoolID', 'function_type', 'updated_at']
    }

    # Lookup PoolName (dari Mobile Pool) utk ditampilkan bareng, murni
    # informatif -- dilampirkan LANGSUNG ke tiap object (bukan dict lookup
    # di template, Django template tidak native mendukung lookup dict pakai
    # variable key tanpa custom filter).
    page_pool_ids = [row.PoolID for row in page_obj.object_list]
    pool_names = dict(MobilePool.objects.filter(PoolID__in=page_pool_ids).values_list('PoolID', 'PoolName'))
    for row in page_obj.object_list:
        row.pool_name = pool_names.get(row.PoolID)

    return render(request, 'mclock/pool_device_function_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
def pool_device_function_add(request):
    """Tambah mapping PoolID -> function type baru."""
    form = PoolDeviceFunctionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f"Mapping PoolID '{form.cleaned_data['PoolID']}' berhasil ditambahkan.")
        return redirect('mclock:pool_device_function_list')
    return render(request, 'mclock/pool_device_function_form.html', {'form': form, 'mode': 'add'})


@staff_required
def pool_device_function_edit(request, pk):
    """Ubah function type (KANTIN/Bukan KANTIN) utk 1 mapping PoolID yang sudah ada."""
    obj = get_object_or_404(PoolDeviceFunction, pk=pk)
    form = PoolDeviceFunctionForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f"Mapping PoolID '{obj.PoolID}' berhasil diperbarui.")
        return redirect('mclock:pool_device_function_list')
    return render(request, 'mclock/pool_device_function_form.html', {'form': form, 'mode': 'edit', 'obj': obj})


@staff_required
@require_POST
def pool_device_function_delete(request, pk):
    """Hapus 1 mapping PoolID -> function type secara permanen -- staff-only."""
    obj = get_object_or_404(PoolDeviceFunction, pk=pk)
    pool_id = obj.PoolID
    obj.delete()
    messages.success(request, f"Mapping PoolID '{pool_id}' berhasil dihapus.")
    return redirect('mclock:pool_device_function_list')