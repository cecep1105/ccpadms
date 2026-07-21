from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import permission_or_staff_required, staff_required

from .forms import (
    ActiveDeviceForm,
    AttendanceRecapFilterForm,
    BackupFingerForm,
    DepartmentForm,
    DeviceCommandForm,
    DeviceLogForm,
    EmployeeForm,
    EmployeeTransferFingerForm,
    FingerprintTemplateForm,
    GenericParamForm,
    NetworkParamsForm,
    OperationLogForm,
    RegisteredDeviceForm,
    TransactionForm,
    TransferFingerForm,
)
from .models import RegisteredDevice, department, devcmds, devlog, employee, fptemp, iclock, oplog, transaction
from .services import backup_device_fingerprints, maybe_activate_after_pool_change, normalize_pin
from .zk_client import (
    PRIVILEGE_ADMIN,
    PRIVILEGE_DEFAULT,
    DeviceConnectionError,
    delete_user_from_device,
    fetch_device_users,
    get_device_network_params,
    get_device_param,
    reboot_device,
    set_device_param,
    set_network_params,
    set_user_privilege_on_device,
    sync_device_time,
    transfer_fingerprints,
    transfer_fingerprints_from_db,
)


def _paginate(request, qs, page_size=10):
    paginator = Paginator(qs, page_size)
    return paginator.get_page(request.GET.get('page') or 1)


# ---------------------------------------------------------------------------
# DEPARTMENT / Pool (model: department)
# ---------------------------------------------------------------------------
@staff_required
def department_list(request):
    search = request.GET.get('q', '').strip()
    qs = department.objects.all().order_by('DeptName')
    if search:
        qs = qs.filter(DeptName__icontains=search)
    page_obj = _paginate(request, qs)
    return render(request, 'iclock/department_list.html', {'page_obj': page_obj, 'search': search})


@staff_required
def department_add(request):
    form = DepartmentForm(request.POST or None, is_create=True)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Department berhasil ditambahkan.')
        return redirect('iclock:department_list')
    return render(request, 'iclock/department_form.html', {'form': form, 'mode': 'create'})


@staff_required
def department_edit(request, pk):
    dept = get_object_or_404(department, pk=pk)
    form = DepartmentForm(request.POST or None, instance=dept, is_create=False)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Department berhasil diperbarui.')
        return redirect('iclock:department_list')
    return render(request, 'iclock/department_form.html', {'form': form, 'mode': 'edit', 'target': dept})


@staff_required
@require_POST
def department_delete(request, pk):
    dept = get_object_or_404(department, pk=pk)
    dept.delete()
    messages.success(request, 'Department berhasil dihapus.')
    return redirect('iclock:department_list')


# ---------------------------------------------------------------------------
# ACTIVE DEVICE (model: iclock)
# ---------------------------------------------------------------------------
ACTIVE_DEVICE_SORT_FIELDS = {
    'sn': 'SN',
    'alias': 'Alias',
    'pool': 'DeptID__DeptName',
    'ip': 'IPAddress',
    'last_activity': 'LastActivity',
}

# Ambang batas "device dianggap tidak aktif" -- LastActivity lebih lama dari
# ini (atau belum pernah ada sama sekali / None) ditandai merah di tabel
# Active Device. Dipakai server-side (render awal) & sisi JS (real-time,
# lihat template active_device_list.html) -- keduanya HARUS konsisten.
ACTIVE_DEVICE_STALE_MINUTES = 60

# Ambang batas terpisah utk kolom "Last Data" (waktu transaksi/attendance
# TERAKHIR dari device, beda dgn LastActivity yg cuma heartbeat/request) --
# sengaja dipisah dari ACTIVE_DEVICE_STALE_MINUTES supaya bisa diatur beda
# kalau perlu (mis. device tertentu wajar jarang ada transaksi tapi tetap
# harus sering heartbeat).
ACTIVE_DEVICE_LASTDATA_STALE_MINUTES = 60


@staff_required
def active_device_list(request):
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'alias')
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)

    qs = iclock.objects.select_related('DeptID').all()
    if search:
        qs = qs.filter(SN__icontains=search) | qs.filter(Alias__icontains=search)

    order_field = ACTIVE_DEVICE_SORT_FIELDS.get(sort_key, 'Alias')
    if direction == 'desc':
        order_field = f'-{order_field}'
    qs = qs.order_by(order_field, 'SN')

    page_obj = _paginate(request, qs, page_size=page_size)
    sort_urls = {key: _build_sort_url(request, key, sort_key, direction) for key in ACTIVE_DEVICE_SORT_FIELDS}

    # Tandai device yang LastActivity/LastData-nya sudah lewat ambang batas
    # (atau belum pernah ada sama sekali) -- dipakai template utk kasih
    # warna merah. Dihitung di Python (bukan langsung {% if %} di template)
    # supaya perbandingan None-nya jelas & tidak rawan salah di template.
    # `LastData()` melakukan 1 query per device (lihat catatan performa di
    # method-nya, iclock/models.py) -- wajar utk listing yang dipaginate.
    stale_cutoff = timezone.now() - timedelta(minutes=ACTIVE_DEVICE_STALE_MINUTES)
    lastdata_cutoff = timezone.now() - timedelta(minutes=ACTIVE_DEVICE_LASTDATA_STALE_MINUTES)
    for device in page_obj.object_list:
        device.is_stale = (device.LastActivity is None) or (device.LastActivity < stale_cutoff)
        device.last_data_value = device.LastData()
        device.is_lastdata_stale = (device.last_data_value is None) or (device.last_data_value < lastdata_cutoff)

    return render(request, 'iclock/active_device_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'stale_minutes': ACTIVE_DEVICE_STALE_MINUTES,
        'lastdata_stale_minutes': ACTIVE_DEVICE_LASTDATA_STALE_MINUTES,
    })


@staff_required
def active_device_add(request):
    form = ActiveDeviceForm(request.POST or None, is_create=True)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Active Device berhasil ditambahkan.')
        return redirect('iclock:active_device_list')
    return render(request, 'iclock/active_device_form.html', {'form': form, 'mode': 'create'})


@staff_required
def active_device_edit(request, sn):
    device = get_object_or_404(iclock, pk=sn)
    form = ActiveDeviceForm(request.POST or None, instance=device, is_create=False)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Active Device berhasil diperbarui.')
        return redirect('iclock:active_device_list')
    return render(request, 'iclock/active_device_form.html', {'form': form, 'mode': 'edit', 'target': device})


@staff_required
@require_POST
def active_device_delete(request, sn):
    device = get_object_or_404(iclock, pk=sn)
    device.delete()
    messages.success(request, 'Active Device berhasil dihapus.')
    return redirect('iclock:active_device_list')


DEVICE_LIVE_USER_SORT_FIELDS = {
    'uid': 'uid',
    'user_id': 'user_id',
    'name': 'name',
    'privilege': 'privilege',
    'card': 'card',
}


@staff_required
def active_device_show_users(request, sn):
    """
    Konek LANGSUNG ke device fisik (lewat pyzk, protokol native ZKTeco) dan
    tampilkan daftar user yang benar-benar tersimpan di memori device saat
    ini -- beda dengan data di tabel Employee (yang bisa saja belum sinkron
    dengan kondisi device sebenarnya).

    Filter (User ID/Nama), sort semua kolom, dan pagination diproses manual
    di Python (bukan lewat QuerySet), karena sumber datanya list biasa dari
    pyzk, bukan dari database.
    """
    device = get_object_or_404(iclock, pk=sn)
    users = None
    error = None
    try:
        users = fetch_device_users(device.IPAddress)
    except DeviceConnectionError as exc:
        error = str(exc)

    pin_filter = request.GET.get('pin', '').strip()
    name_filter = request.GET.get('name', '').strip()
    sort_key = request.GET.get('sort', 'user_id')
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)
    sort_urls = {key: _build_sort_url(request, key, sort_key, direction) for key in DEVICE_LIVE_USER_SORT_FIELDS}

    page_obj = None
    total_count = 0
    if users is not None:
        if pin_filter:
            users = [u for u in users if pin_filter.lower() in str(u.get('user_id') or '').lower()]
        if name_filter:
            users = [u for u in users if name_filter.lower() in str(u.get('name') or '').lower()]

        sort_field = DEVICE_LIVE_USER_SORT_FIELDS.get(sort_key, 'user_id')
        users.sort(key=lambda u: u.get(sort_field), reverse=(direction == 'desc'))
        total_count = len(users)
        page_obj = _paginate(request, users, page_size=page_size)

    return render(request, 'iclock/active_device_show_users.html', {
        'device': device,
        'error': error,
        'page_obj': page_obj,
        'total_count': total_count,
        'pin_filter': pin_filter,
        'name_filter': name_filter,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
def active_device_backup_fingerprints(request, sn):
    """
    "Backup Data Finger": ambil user + template fingerprint dari device fisik
    ini, add/modify (upsert) ke tabel Fingerprint Template (fptemp). Bisa
    difilter by PIN (regex) supaya tidak perlu proses semua user tiap kali --
    device dengan banyak user bisa lama sekali kalau full backup.
    """
    device = get_object_or_404(iclock, pk=sn)
    log_output = None

    if request.method == 'POST':
        form = BackupFingerForm(request.POST)
        if form.is_valid():
            pin_pattern = form.cleaned_data['pin_pattern']
            log_lines = backup_device_fingerprints(device, pin_pattern=pin_pattern)
            log_output = '\n'.join(log_lines)
    else:
        form = BackupFingerForm()

    return render(request, 'iclock/active_device_backup_fingerprints.html', {
        'device': device, 'form': form, 'log_output': log_output,
    })


@staff_required
@require_POST
def active_device_reboot(request, sn):
    """Reboot device fisik via pyzk. Aksi disruptif -- konfirmasi sudah di sisi JS (confirm() dialog)."""
    device = get_object_or_404(iclock, pk=sn)
    success, message = reboot_device(device.IPAddress)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect('iclock:active_device_list')


@staff_required
@require_POST
def active_device_sync_time(request, sn):
    """Sinkronkan jam device fisik dengan jam server (komputer ini) via pyzk."""
    device = get_object_or_404(iclock, pk=sn)
    success, message = sync_device_time(device.IPAddress)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect('iclock:active_device_list')


@staff_required
def active_device_set_network_params(request, sn):
    """
    "Set Network Param": ganti IP Address/NetMask/Gateway device fisik via
    pyzk (CMD_OPTIONS_WRQ + CMD_REFRESHOPTION). GET nampilin form (pre-fill
    dengan nilai SEKARANG dari device kalau berhasil dibaca), POST beneran
    menjalankan perubahannya.

    Berguna khusus utk mesin fingerprint yang punya IP 'bawaan' (dipakai
    kalau tidak ada jaringan) yang justru masuk sebagai 'Alias' di protokol
    push-sdk, bukan IP DHCP-nya -- fitur ini mempermudah mengganti parameter
    itu langsung dari portal, tanpa perlu akses menu device secara fisik.
    """
    device = get_object_or_404(iclock, pk=sn)
    current_params = None
    read_error = None
    log_output = None

    if request.method == 'POST':
        form = NetworkParamsForm(request.POST)
        if form.is_valid():
            success, message = set_network_params(
                device.IPAddress,
                new_ip=form.cleaned_data.get('new_ip', ''),
                new_netmask=form.cleaned_data.get('new_netmask', ''),
                new_gateway=form.cleaned_data.get('new_gateway', ''),
            )
            log_output = message
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
    else:
        form = NetworkParamsForm()
        try:
            current_params = get_device_network_params(device.IPAddress)
        except DeviceConnectionError as exc:
            read_error = str(exc)

    return render(request, 'iclock/active_device_set_network_params.html', {
        'device': device,
        'form': form,
        'current_params': current_params,
        'read_error': read_error,
        'log_output': log_output,
    })


@staff_required
def active_device_generic_param(request, sn):
    """
    "Get/Set Param" generic -- testing bebas nama & nilai parameter
    konfigurasi device fisik (CMD_OPTIONS_RRQ/CMD_OPTIONS_WRQ), untuk admin
    yang sudah tahu daftar nama parameter yang valid dan mau coba-coba
    (mis. set 'DHCP' jadi '0' supaya device pakai IP static, bukan DHCP).
    """
    device = get_object_or_404(iclock, pk=sn)
    log_output = None

    if request.method == 'POST':
        form = GenericParamForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            param_name = form.cleaned_data['param_name'].strip()
            param_value = form.cleaned_data.get('param_value', '').strip()
            do_refresh = form.cleaned_data.get('do_refresh', True)

            if action == 'get':
                success, result = get_device_param(device.IPAddress, param_name)
                if success:
                    log_output = f"GET '{param_name}' = '{result}'"
                    messages.success(request, f"Nilai '{param_name}' saat ini: '{result}'")
                else:
                    log_output = f"GAGAL GET '{param_name}': {result}"
                    messages.error(request, result)
            else:
                success, message = set_device_param(device.IPAddress, param_name, param_value, do_refresh=do_refresh)
                log_output = message
                if success:
                    messages.success(request, message)
                else:
                    messages.error(request, message)
    else:
        form = GenericParamForm()

    return render(request, 'iclock/active_device_generic_param.html', {
        'device': device, 'form': form, 'log_output': log_output,
    })


def _sync_employee_privilege(device, user_id, new_privilege):
    """Kalau ada record Employee yang cocok (PIN + device ini), ikut update Privilege-nya di DB."""
    employee.objects.filter(SN=device, PIN=normalize_pin(user_id)).update(Privilege=new_privilege)


@staff_required
@require_POST
def active_device_user_toggle_privilege(request, sn, user_id):
    """
    Toggle privilege 14 (Admin) <-> 0 (User biasa) LANGSUNG di device ini
    (bukan lewat tabel Employee). Arah toggle ditentukan dari privilege saat
    ini yang dikirim form (`current_privilege`), supaya tidak perlu query
    ulang ke device cuma buat tahu privilege sekarang (sudah tampil di layar).
    Kalau ada record Employee yang cocok (PIN + device ini), ikut disinkronkan.
    """
    device = get_object_or_404(iclock, pk=sn)
    try:
        current_privilege = int(request.POST.get('current_privilege', 0))
    except (TypeError, ValueError):
        current_privilege = 0
    new_privilege = PRIVILEGE_DEFAULT if current_privilege == PRIVILEGE_ADMIN else PRIVILEGE_ADMIN
    label = 'Admin' if new_privilege == PRIVILEGE_ADMIN else 'User biasa'

    try:
        set_user_privilege_on_device(device.IPAddress, user_id, new_privilege)
    except DeviceConnectionError as exc:
        messages.error(request, f"Gagal mengubah privilege user '{user_id}' di device: {exc}")
    else:
        _sync_employee_privilege(device, user_id, new_privilege)
        messages.success(request, f"Privilege user '{user_id}' di device berhasil diubah jadi {label}.")
    return redirect('iclock:active_device_show_users', sn=sn)


@staff_required
@require_POST
def active_device_user_delete(request, sn, user_id):
    """Hapus user LANGSUNG dari device ini lewat pyzk. Record Employee yang cocok ikut dihapus kalau ada."""
    device = get_object_or_404(iclock, pk=sn)
    try:
        deleted = delete_user_from_device(device.IPAddress, user_id)
    except DeviceConnectionError as exc:
        messages.error(request, f"Gagal menghapus user '{user_id}' dari device: {exc}")
    else:
        employee.objects.filter(SN=device, PIN=normalize_pin(user_id)).delete()
        if deleted:
            messages.success(request, f"User '{user_id}' berhasil dihapus dari device.")
        else:
            messages.info(request, f"User '{user_id}' tidak ditemukan di device (mungkin sudah terhapus sebelumnya).")
    return redirect('iclock:active_device_show_users', sn=sn)


@staff_required
def active_device_user_transfer_finger(request, sn, user_id):
    """
    Form transfer fingerprint: admin bisa isi 1+ PIN (textarea), pilih source
    device (default = device yang lagi dibuka), pilih pool tujuan, dan
    opsional pilih 1 device tujuan spesifik (kalau dikosongkan -> ke SEMUA
    device di pool tujuan). Hasilnya ditampilkan di kolom status (log per
    langkah), diproses lewat pyzk (iclock/zk_client.py::transfer_fingerprints).
    """
    source_device = get_object_or_404(iclock, pk=sn)
    log_output = None

    if request.method == 'POST':
        form = TransferFingerForm(request.POST)
        if form.is_valid():
            pins = form.cleaned_data['pins']
            from_device = form.cleaned_data['from_device']
            to_pool = form.cleaned_data['to_pool']
            target_device = form.cleaned_data['target_device']

            if target_device:
                targets = [(target_device.IPAddress, str(target_device))]
            else:
                targets = [
                    (d.IPAddress, str(d))
                    for d in iclock.objects.filter(DeptID=to_pool)
                ]

            log_lines = transfer_fingerprints(from_device.IPAddress, targets, pins)
            log_output = '\n'.join(log_lines)
    else:
        form = TransferFingerForm(initial={'pins': user_id, 'from_device': source_device.pk})

    return render(request, 'iclock/transfer_finger_form.html', {
        'form': form, 'source_device': source_device, 'log_output': log_output,
    })


@permission_or_staff_required('iclock.can_transfer_finger', 'iclock.can_view_attendance_recap')
def ajax_devices_by_pool(request):
    """Endpoint kecil buat combo 'Target Device' -- diisi ulang lewat JS pas 'To Pool' berubah."""
    pool_id = request.GET.get('pool_id')
    devices = []
    if pool_id:
        devices = list(
            iclock.objects.filter(DeptID_id=pool_id).order_by('Alias').values('SN', 'Alias')
        )
    return JsonResponse({'devices': devices})


# ---------------------------------------------------------------------------
# REGISTERED DEVICE (model: RegisteredDevice)
# ---------------------------------------------------------------------------
REGISTERED_DEVICE_SORT_FIELDS = {
    'sn': 'SN',
    'device_name': 'DeviceName',
    'pool': 'DeptID__DeptName',
    'ip': 'IPAddress',
    'ip_router': 'IPRouter',
}


@staff_required
def registered_device_list(request):
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'sn')
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)

    qs = RegisteredDevice.objects.select_related('DeptID').all()
    if search:
        qs = qs.filter(SN__icontains=search) | qs.filter(DeviceName__icontains=search)

    order_field = REGISTERED_DEVICE_SORT_FIELDS.get(sort_key, 'SN')
    if direction == 'desc':
        order_field = f'-{order_field}'
    qs = qs.order_by(order_field, 'SN')

    page_obj = _paginate(request, qs, page_size=page_size)
    sort_urls = {key: _build_sort_url(request, key, sort_key, direction) for key in REGISTERED_DEVICE_SORT_FIELDS}

    return render(request, 'iclock/registered_device_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
def registered_device_add(request):
    form = RegisteredDeviceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Registered Device berhasil ditambahkan.')
        return redirect('iclock:registered_device_list')
    return render(request, 'iclock/registered_device_form.html', {'form': form, 'mode': 'create'})


@staff_required
def registered_device_edit(request, pk):
    device = get_object_or_404(RegisteredDevice, pk=pk)
    old_dept_id = device.DeptID_id  # nilai Pool ID SEBELUM form memproses input baru
    form = RegisteredDeviceForm(request.POST or None, instance=device)
    if request.method == 'POST' and form.is_valid():
        with db_transaction.atomic():
            updated_device = form.save()
            activated = maybe_activate_after_pool_change(updated_device, old_dept_id)

        if activated:
            messages.success(
                request,
                f"Registered Device berhasil diperbarui. Device '{updated_device.SN}' otomatis "
                f"diaktifkan ke Active Device karena Pool ID diubah dari 0.",
            )
        else:
            messages.success(request, 'Registered Device berhasil diperbarui.')
        return redirect('iclock:registered_device_list')
    return render(request, 'iclock/registered_device_form.html', {'form': form, 'mode': 'edit', 'target': device})


@staff_required
@require_POST
def registered_device_delete(request, pk):
    device = get_object_or_404(RegisteredDevice, pk=pk)
    device.delete()
    messages.success(request, 'Registered Device berhasil dihapus.')
    return redirect('iclock:registered_device_list')


# ---------------------------------------------------------------------------
# DEVICE USER (model: employee)
# ---------------------------------------------------------------------------
DEVICE_USER_SORT_FIELDS = {
    'pin': 'PIN',
    'name': 'EName',
    'dept': 'DeptID__DeptName',
    'device': 'SN__SN',
    'gender': 'Gender',
    'privilege': 'Privilege',
    'mobile': 'Mobile',
}


def _build_sort_url(request, field, current_sort, current_dir):
    """URL utk header kolom yang bisa diklik: toggle asc/desc, reset ke halaman 1, pertahankan filter lain."""
    new_dir = 'desc' if (current_sort == field and current_dir == 'asc') else 'asc'
    params = request.GET.copy()
    params['sort'] = field
    params['dir'] = new_dir
    params.pop('page', None)
    return f'?{params.urlencode()}'


PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100]
DEFAULT_PAGE_SIZE = 10


def _resolve_page_size(request, default=DEFAULT_PAGE_SIZE, options=PAGE_SIZE_OPTIONS):
    """Baca ?page_size= dari request, validasi terhadap pilihan yang diizinkan (cegah nilai aneh/berlebihan)."""
    try:
        page_size = int(request.GET.get('page_size', default))
    except (TypeError, ValueError):
        return default
    return page_size if page_size in options else default


@permission_or_staff_required('iclock.can_transfer_finger')
def device_user_list(request):
    pin_filter = request.GET.get('pin', '').strip()
    name_filter = request.GET.get('name', '').strip()
    sort_key = request.GET.get('sort', 'pin')
    direction = request.GET.get('dir', 'asc') if request.GET.get('dir') in ('asc', 'desc') else 'asc'
    page_size = _resolve_page_size(request)

    qs = employee.objects.select_related('DeptID', 'SN', 'SN__DeptID').all()
    if pin_filter:
        qs = qs.filter(PIN__icontains=pin_filter)
    if name_filter:
        qs = qs.filter(EName__icontains=name_filter)

    order_field = DEVICE_USER_SORT_FIELDS.get(sort_key, 'PIN')
    if direction == 'desc':
        order_field = f'-{order_field}'
    qs = qs.order_by(order_field, 'PIN')  # 'PIN' sebagai tie-breaker biar urutan konsisten

    page_obj = _paginate(request, qs, page_size=page_size)
    sort_urls = {key: _build_sort_url(request, key, sort_key, direction) for key in DEVICE_USER_SORT_FIELDS}

    return render(request, 'iclock/device_user_list.html', {
        'page_obj': page_obj,
        'pin_filter': pin_filter,
        'name_filter': name_filter,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
    })


@staff_required
def device_user_add(request):
    form = EmployeeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Employee berhasil ditambahkan.')
        return redirect('iclock:device_user_list')
    return render(request, 'iclock/device_user_form.html', {'form': form, 'mode': 'create'})


@staff_required
def device_user_edit(request, pk):
    emp = get_object_or_404(employee, pk=pk)
    form = EmployeeForm(request.POST or None, instance=emp)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Employee berhasil diperbarui.')
        return redirect('iclock:device_user_list')
    return render(request, 'iclock/device_user_form.html', {'form': form, 'mode': 'edit', 'target': emp})


@staff_required
@require_POST
def device_user_delete(request, pk):
    """
    Hapus Employee. Kalau user ini terhubung ke sebuah Active Device (SN +
    IPAddress ada), sekalian coba hapus dari device fisiknya lewat pyzk
    (best-effort -- kalau gagal konek, penghapusan di database tetap jalan,
    cuma pesannya menyebutkan sync ke device gagal).
    """
    emp = get_object_or_404(employee, pk=pk)
    device_note = ''
    if emp.SN_id and emp.SN.IPAddress:
        try:
            deleted_on_device = delete_user_from_device(emp.SN.IPAddress, emp.PIN)
            device_note = (
                ' Juga berhasil dihapus dari device fisik.' if deleted_on_device
                else ' (User tidak ditemukan di device, dilewati.)'
            )
        except DeviceConnectionError as exc:
            device_note = f' Tapi GAGAL sync hapus ke device: {exc}'
    emp.delete()
    messages.success(request, f'Employee berhasil dihapus dari database.{device_note}')
    return redirect('iclock:device_user_list')


@staff_required
@require_POST
def device_user_toggle_privilege(request, pk):
    """
    Toggle privilege 14 (Admin) <-> 0 (User biasa). Kalau user ini terhubung
    ke sebuah Active Device, sekalian sync perubahan privilege ke device
    fisiknya lewat pyzk (best-effort, sama seperti delete).
    """
    emp = get_object_or_404(employee, pk=pk)
    new_privilege = PRIVILEGE_DEFAULT if emp.Privilege == PRIVILEGE_ADMIN else PRIVILEGE_ADMIN
    emp.Privilege = new_privilege
    emp.save(update_fields=['Privilege'])

    label = 'Admin' if new_privilege == PRIVILEGE_ADMIN else 'User biasa'
    if emp.SN_id and emp.SN.IPAddress:
        try:
            set_user_privilege_on_device(emp.SN.IPAddress, emp.PIN, new_privilege)
            device_note = ' Juga tersinkron ke device fisik.'
        except DeviceConnectionError as exc:
            device_note = f' Tapi GAGAL sync ke device: {exc}'
    else:
        device_note = ' (Device sync dilewati, user ini belum terhubung ke device manapun.)'

    messages.success(request, f"Privilege '{emp.PIN}' berhasil diubah jadi {label}.{device_note}")
    return redirect('iclock:device_user_list')


@permission_or_staff_required('iclock.can_transfer_finger')
def device_user_transfer_finger(request, pk):
    """
    Transfer fingerprint utk SATU employee (PIN tetap, tidak bisa diedit di
    sini -- beda dengan versi di Active Device yang bisa banyak PIN).

    SUMBER template-nya dari DATABASE (tabel Fingerprint Template / fptemp),
    BUKAN dari device fisik -- jadi tidak perlu employee.SN online/reachable
    sama sekali, cukup template-nya sudah pernah ke-backup ke database
    (lewat fitur "Backup Data Finger" di Active Device, atau proses push
    sinkronisasi Anda sendiri).
    """
    emp = get_object_or_404(employee, pk=pk)

    db_templates_qs = fptemp.objects.filter(UserID=emp)
    if not db_templates_qs.exists():
        messages.error(
            request,
            f"Employee '{emp.PIN}' belum punya template fingerprint tersimpan di database "
            f"(tabel Fingerprint Template). Backup dulu dari device fisik (menu 'Backup Data Finger' "
            f"di Active Device) sebelum bisa transfer.",
        )
        return redirect('iclock:device_user_list')

    log_output = None
    if request.method == 'POST':
        form = EmployeeTransferFingerForm(request.POST)
        if form.is_valid():
            to_pool = form.cleaned_data['to_pool']
            target_device = form.cleaned_data['target_device']
            if target_device:
                targets = [(target_device.IPAddress, str(target_device))]
            else:
                targets = [(d.IPAddress, str(d)) for d in iclock.objects.filter(DeptID=to_pool)]

            db_templates = [
                {'fid': t.FingerID, 'valid': t.Valid, 'template_b64': t.Template}
                for t in db_templates_qs
            ]
            try:
                card_value = int(emp.Card) if emp.Card else 0
            except (TypeError, ValueError):
                card_value = 0

            log_lines = transfer_fingerprints_from_db(
                pin=emp.PIN,
                name=emp.EName or emp.PIN,
                privilege=emp.Privilege or 0,
                password=emp.Password or '',
                card=card_value,
                group_id=str(emp.AccGroup) if emp.AccGroup else '',
                db_templates=db_templates,
                target_ips=targets,
            )
            log_output = '\n'.join(log_lines)
    else:
        form = EmployeeTransferFingerForm()

    return render(request, 'iclock/device_user_transfer_finger_form.html', {
        'form': form,
        'target_employee': emp,
        'log_output': log_output,
        'db_template_count': db_templates_qs.count(),
    })


# ---------------------------------------------------------------------------
# FINGERPRINT TEMPLATE / Template Jari (model: fptemp)
# ---------------------------------------------------------------------------
FINGERPRINT_TEMPLATE_SORT_FIELDS = {
    'pin': 'UserID__PIN',
    'name': 'UserID__EName',
    'count': 'template_count',
    'utime': 'latest_utime',
}


@staff_required
def fingerprint_template_list(request):
    """
    Di-GROUP per employee (bukan 1 baris per template) supaya tampilannya
    tidak terlalu banyak kalau 1 employee punya beberapa jari terdaftar --
    klik nama/PIN-nya utk lihat semua template jari milik employee itu.
    """
    from django.db.models import Count, Max

    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'utime')
    direction = request.GET.get('dir', 'desc') if request.GET.get('dir') in ('asc', 'desc') else 'desc'
    page_size = _resolve_page_size(request)

    base_qs = fptemp.objects.all()
    if search:
        base_qs = base_qs.filter(UserID__PIN__icontains=search) | base_qs.filter(UserID__EName__icontains=search)

    # Group per employee langsung di level SQL (values + annotate), BUKAN
    # ambil semua baris lalu di-group manual di Python -- lebih efisien
    # utk data banyak, dan pagination-nya berlaku ke jumlah EMPLOYEE, bukan
    # jumlah baris template mentah.
    grouped_qs = (
        base_qs.values('UserID_id', 'UserID__PIN', 'UserID__EName')
        .annotate(template_count=Count('id'), latest_utime=Max('UTime'))
    )

    order_field = FINGERPRINT_TEMPLATE_SORT_FIELDS.get(sort_key, 'latest_utime')
    if direction == 'desc':
        order_field = f'-{order_field}'
    grouped_qs = grouped_qs.order_by(order_field, 'UserID__PIN')

    page_obj = _paginate(request, grouped_qs, page_size=page_size)
    sort_urls = {key: _build_sort_url(request, key, sort_key, direction) for key in FINGERPRINT_TEMPLATE_SORT_FIELDS}

    # Detail template (per jari) HANYA diambil utk employee yang tampil di
    # halaman aktif -- konsisten dgn pola efisiensi pagination yang sama
    # dipakai di Attendance Recap.
    page_employee_ids = [row['UserID_id'] for row in page_obj.object_list]
    templates_by_employee = defaultdict(list)
    if page_employee_ids:
        detail_qs = (
            fptemp.objects.filter(UserID_id__in=page_employee_ids)
            .select_related('SN')
            .order_by('UserID_id', 'FingerID')
        )
        for tpl in detail_qs:
            templates_by_employee[tpl.UserID_id].append(tpl)

    start_no = page_obj.start_index() if page_employee_ids else 0
    rows = []
    for i, group in enumerate(page_obj.object_list):
        rows.append({
            'no': start_no + i,
            'pin': group['UserID__PIN'],
            'name': group['UserID__EName'],
            'count': group['template_count'],
            'latest_utime': group['latest_utime'],
            'templates': templates_by_employee.get(group['UserID_id'], []),
        })

    return render(request, 'iclock/fingerprint_template_list.html', {
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
def fingerprint_template_add(request):
    form = FingerprintTemplateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Fingerprint Template berhasil ditambahkan.')
        return redirect('iclock:fingerprint_template_list')
    return render(request, 'iclock/fingerprint_template_form.html', {'form': form, 'mode': 'create'})


@staff_required
def fingerprint_template_edit(request, pk):
    tpl = get_object_or_404(fptemp, pk=pk)
    form = FingerprintTemplateForm(request.POST or None, instance=tpl)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Fingerprint Template berhasil diperbarui.')
        return redirect('iclock:fingerprint_template_list')
    return render(request, 'iclock/fingerprint_template_form.html', {'form': form, 'mode': 'edit', 'target': tpl})


@staff_required
@require_POST
def fingerprint_template_delete(request, pk):
    tpl = get_object_or_404(fptemp, pk=pk)
    tpl.delete()
    messages.success(request, 'Fingerprint Template berhasil dihapus.')
    return redirect('iclock:fingerprint_template_list')


# ---------------------------------------------------------------------------
# TRANSACTION / Log Absensi (model: transaction)
# ---------------------------------------------------------------------------
TRANSACTION_SORT_FIELDS = {
    'pin': 'UserID__PIN',
    'name': 'UserID__EName',
    'ttime': 'TTime',
    'state': 'State',
    'verify': 'Verify',
    'device': 'SN__SN',
}


@staff_required
def transaction_list(request):
    search = request.GET.get('q', '').strip()
    sort_key = request.GET.get('sort', 'ttime')
    direction = request.GET.get('dir', 'desc') if request.GET.get('dir') in ('asc', 'desc') else 'desc'
    page_size = _resolve_page_size(request)

    qs = transaction.objects.select_related('UserID', 'SN').all()
    if search:
        qs = qs.filter(UserID__PIN__icontains=search) | qs.filter(UserID__EName__icontains=search)

    order_field = TRANSACTION_SORT_FIELDS.get(sort_key, 'TTime')
    if direction == 'desc':
        order_field = f'-{order_field}'
    qs = qs.order_by(order_field, 'id')

    page_obj = _paginate(request, qs, page_size=page_size)
    sort_urls = {key: _build_sort_url(request, key, sort_key, direction) for key in TRANSACTION_SORT_FIELDS}

    return render(request, 'iclock/transaction_list.html', {
        'page_obj': page_obj,
        'search': search,
        'sort': sort_key,
        'dir': direction,
        'sort_urls': sort_urls,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@staff_required
def transaction_add(request):
    form = TransactionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Transaction berhasil ditambahkan.')
        return redirect('iclock:transaction_list')
    return render(request, 'iclock/transaction_form.html', {'form': form, 'mode': 'create'})


@staff_required
@require_POST
def transaction_delete(request, pk):
    trx = get_object_or_404(transaction, pk=pk)
    trx.delete()
    messages.success(request, 'Transaction berhasil dihapus.')
    return redirect('iclock:transaction_list')


# ---------------------------------------------------------------------------
# OPERATION LOG (model: oplog)
# ---------------------------------------------------------------------------
@staff_required
def operation_log_list(request):
    search = request.GET.get('q', '').strip()
    qs = oplog.objects.select_related('SN').all().order_by('-OPTime')
    if search:
        qs = qs.filter(SN__SN__icontains=search)
    page_obj = _paginate(request, qs)
    return render(request, 'iclock/operation_log_list.html', {'page_obj': page_obj, 'search': search})


@staff_required
def operation_log_add(request):
    form = OperationLogForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Operation Log berhasil ditambahkan.')
        return redirect('iclock:operation_log_list')
    return render(request, 'iclock/operation_log_form.html', {'form': form, 'mode': 'create'})


@staff_required
def operation_log_edit(request, pk):
    log = get_object_or_404(oplog, pk=pk)
    form = OperationLogForm(request.POST or None, instance=log)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Operation Log berhasil diperbarui.')
        return redirect('iclock:operation_log_list')
    return render(request, 'iclock/operation_log_form.html', {'form': form, 'mode': 'edit', 'target': log})


@staff_required
@require_POST
def operation_log_delete(request, pk):
    log = get_object_or_404(oplog, pk=pk)
    log.delete()
    messages.success(request, 'Operation Log berhasil dihapus.')
    return redirect('iclock:operation_log_list')


# ---------------------------------------------------------------------------
# DEVICE LOG (model: devlog)
# ---------------------------------------------------------------------------
@staff_required
def device_log_list(request):
    search = request.GET.get('q', '').strip()
    qs = devlog.objects.select_related('SN').all().order_by('-OpTime')
    if search:
        qs = qs.filter(SN__SN__icontains=search) | qs.filter(OP__icontains=search)
    page_obj = _paginate(request, qs)
    return render(request, 'iclock/device_log_list.html', {'page_obj': page_obj, 'search': search})


@staff_required
def device_log_add(request):
    form = DeviceLogForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Device Log berhasil ditambahkan.')
        return redirect('iclock:device_log_list')
    return render(request, 'iclock/device_log_form.html', {'form': form, 'mode': 'create'})


@staff_required
def device_log_edit(request, pk):
    log = get_object_or_404(devlog, pk=pk)
    form = DeviceLogForm(request.POST or None, instance=log)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Device Log berhasil diperbarui.')
        return redirect('iclock:device_log_list')
    return render(request, 'iclock/device_log_form.html', {'form': form, 'mode': 'edit', 'target': log})


@staff_required
@require_POST
def device_log_delete(request, pk):
    log = get_object_or_404(devlog, pk=pk)
    log.delete()
    messages.success(request, 'Device Log berhasil dihapus.')
    return redirect('iclock:device_log_list')


# ---------------------------------------------------------------------------
# DEVICE COMMAND (model: devcmds)
# ---------------------------------------------------------------------------
@staff_required
def device_command_list(request):
    search = request.GET.get('q', '').strip()
    qs = devcmds.objects.select_related('SN', 'User').all().order_by('-CmdCommitTime')
    if search:
        qs = qs.filter(SN__SN__icontains=search) | qs.filter(CmdContent__icontains=search)
    page_obj = _paginate(request, qs)
    return render(request, 'iclock/device_command_list.html', {'page_obj': page_obj, 'search': search})


@staff_required
def device_command_add(request):
    form = DeviceCommandForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        cmd = form.save(commit=False)
        cmd.User = request.user
        cmd.save()
        messages.success(request, 'Device Command berhasil ditambahkan.')
        return redirect('iclock:device_command_list')
    return render(request, 'iclock/device_command_form.html', {'form': form, 'mode': 'create'})


@staff_required
def device_command_edit(request, pk):
    cmd = get_object_or_404(devcmds, pk=pk)
    form = DeviceCommandForm(request.POST or None, instance=cmd)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Device Command berhasil diperbarui.')
        return redirect('iclock:device_command_list')
    return render(request, 'iclock/device_command_form.html', {'form': form, 'mode': 'edit', 'target': cmd})


@staff_required
@require_POST
def device_command_delete(request, pk):
    cmd = get_object_or_404(devcmds, pk=pk)
    cmd.delete()
    messages.success(request, 'Device Command berhasil dihapus.')
    return redirect('iclock:device_command_list')


# ---------------------------------------------------------------------------
# ATTENDANCE RECAP / Rekap Kehadiran
# ---------------------------------------------------------------------------
INDONESIAN_DAYS = {
    0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu',
}
INDONESIAN_MONTHS = {
    1: 'JANUARI', 2: 'FEBRUARI', 3: 'MARET', 4: 'APRIL', 5: 'MEI', 6: 'JUNI',
    7: 'JULI', 8: 'AGUSTUS', 9: 'SEPTEMBER', 10: 'OKTOBER', 11: 'NOVEMBER', 12: 'DESEMBER',
}


def _normalize_state(state):
    """
    Django ORM idealnya selalu mengembalikan `State` sebagai string (field-nya
    CharField), tapi kalau kolom `checktype` di database sebenarnya bertipe
    numeric/lain (skema legacy sering begini), nilainya bisa ke-retrieve
    sebagai int/bytes -- perbandingan string biasa (`trx.State == '0'`) diam-
    diam selalu False kalau begitu, bikin SEMUA transaksi tidak pernah
    kehitung IN maupun OUT (baris tetap tampil krn PIN-nya sukses di-list,
    tapi jam kosong). Fungsi ini menyamakan tipenya dulu sebelum dibandingkan.
    """
    if state is None:
        return ''
    if isinstance(state, bytes):
        state = state.decode('utf-8', errors='ignore')
    return str(state).strip()


def _is_in_state(state):
    """
    True kalau `state` termasuk kode "IN" (lihat settings.ATTENDANCE_IN_STATE_CODES,
    default ['0', 'I'] -- device berbeda bisa pakai konvensi kode berbeda).
    Selain kode IN, dianggap OUT (tidak ada kategori ketiga).
    """
    from django.conf import settings
    in_codes = {_normalize_state(c) for c in getattr(settings, 'ATTENDANCE_IN_STATE_CODES', ['0', 'I'])}
    return _normalize_state(state) in in_codes


def _to_local_time(dt):
    """
    Handle baik datetime aware maupun naive tanpa crash -- `timezone.localtime()`
    akan raise ValueError kalau dikasih naive datetime (bisa kejadian kalau
    USE_TZ=False, atau device fisik menulis timestamp naive langsung ke DB).
    Kalau naive, dipakai apa adanya (diasumsikan sudah waktu lokal).
    """
    if dt is None:
        return None
    if timezone.is_aware(dt):
        return timezone.localtime(dt)
    return dt


@permission_or_staff_required('iclock.can_view_attendance_recap')
def attendance_recap(request):
    """
    Rekap Kehadiran: filter by PIN (lookup atau regex) / Device Function /
    Pool / Device / rentang tanggal, tampilkan matrix PIN x tanggal berisi
    jam IN (paling awal) dan jam OUT (paling akhir) per hari, dengan jumlah
    transaksi (format "HH:MM|n") -- diklik utk lihat semua transaksi IN/OUT
    hari itu.

    "IN" = transaction.State termasuk settings.ATTENDANCE_IN_STATE_CODES.
    SEMUA state lain dianggap "OUT" -- sesuai instruksi: tidak ada kategori
    ketiga.

    Kalau `pin_exact` ada di query string (di-set JS pas admin klik salah
    satu hasil autocomplete PIN), redirect ke halaman card rekap bulanan
    utk 1 karyawan itu -- filter lain (function/pool/device/date) diabaikan.
    """
    pin_exact = request.GET.get('pin_exact', '').strip()
    if pin_exact:
        return redirect('iclock:attendance_recap_employee_card', pin=pin_exact)

    form = AttendanceRecapFilterForm(request.GET or None)
    page_size = _resolve_page_size(request)

    queried = bool(request.GET.get('date_from') and request.GET.get('date_to'))
    date_columns = []
    recap_rows = []
    page_obj = None

    if queried and form.is_valid():
        pin_pattern = form.cleaned_data.get('pin')
        function_code = form.cleaned_data.get('function')
        pool = form.cleaned_data.get('pool')
        device = form.cleaned_data.get('device')
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']

        # Kolom tanggal, TERBARU dulu (descending) sesuai contoh yang diminta.
        d = date_to
        while d >= date_from:
            date_columns.append({
                'date': d,
                'day_name': INDONESIAN_DAYS[d.weekday()],
                'label': d.strftime('%Y/%m/%d'),
            })
            d -= timedelta(days=1)

        base_qs = transaction.objects.filter(TTime__date__gte=date_from, TTime__date__lte=date_to)
        if pin_pattern:
            # Regex diterapkan di level DB (bukan di Python) supaya tetap
            # efisien walau jumlah transaksi besar -- MySQL & SQLite modern
            # sama2 mendukung REGEXP lewat lookup __iregex Django.
            base_qs = base_qs.filter(UserID__PIN__iregex=pin_pattern)
        if function_code:
            base_qs = base_qs.filter(Function=function_code)
        if device:
            base_qs = base_qs.filter(SN=device)
        elif pool:
            base_qs = base_qs.filter(SN__DeptID=pool)

        # Pagination di-terapkan ke daftar PIN (baris), BUKAN ke raw transaksi
        # -- supaya query detail cuma dijalankan utk PIN yang tampil di
        # halaman saat ini, bukan semua PIN yang match filter sekaligus.
        pin_list = sorted(set(base_qs.values_list('UserID__PIN', flat=True)))
        page_obj = _paginate(request, pin_list, page_size=page_size)
        page_pins = list(page_obj.object_list)

        if page_pins:
            detail_qs = (
                base_qs.filter(UserID__PIN__in=page_pins)
                .select_related('UserID')
                .order_by('UserID__PIN', 'TTime')
            )

            matrix = defaultdict(lambda: defaultdict(lambda: {'in': [], 'out': []}))
            names = {}
            for trx in detail_qs:
                pin = trx.UserID.PIN
                names[pin] = trx.UserID.EName
                local_time = _to_local_time(trx.TTime)
                if local_time is None:
                    continue
                trx_date = local_time.date()
                if _is_in_state(trx.State):
                    matrix[pin][trx_date]['in'].append(local_time)
                else:
                    matrix[pin][trx_date]['out'].append(local_time)

            start_no = page_obj.start_index()
            for i, pin in enumerate(page_pins):
                row = {'no': start_no + i, 'pin': pin, 'name': names.get(pin, ''), 'cells': []}
                for col in date_columns:
                    day_data = matrix[pin].get(col['date'], {'in': [], 'out': []})
                    in_times = sorted(day_data['in'])
                    out_times = sorted(day_data['out'])
                    row['cells'].append({
                        'in_first': in_times[0] if in_times else None,
                        'in_count': len(in_times),
                        'in_all': in_times,
                        'out_last': out_times[-1] if out_times else None,
                        'out_count': len(out_times),
                        'out_all': out_times,
                    })
                recap_rows.append(row)

    return render(request, 'iclock/attendance_recap.html', {
        'form': form,
        'queried': queried,
        'date_columns': date_columns,
        'recap_rows': recap_rows,
        'page_obj': page_obj,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
    })


@permission_or_staff_required('iclock.can_view_attendance_recap')
def ajax_employee_search(request):
    """Endpoint kecil buat autocomplete PIN di Attendance Recap -- cari by PIN atau nama."""
    q = request.GET.get('q', '').strip()
    results = []
    if len(q) >= 2:
        qs = employee.objects.filter(Q(PIN__icontains=q) | Q(EName__icontains=q)).order_by('PIN')[:15]
        results = [{'pin': e.PIN, 'name': e.EName or ''} for e in qs]
    return JsonResponse({'employees': results})


@permission_or_staff_required('iclock.can_view_attendance_recap')
def attendance_recap_employee_card(request, pin):
    """
    Rekap kehadiran 1 karyawan, 1 bulan penuh (default bulan berjalan),
    ditampilkan sebagai card dengan header sticky (info karyawan + periode +
    navigasi Prev/Next bulan) dan daftar transaksi yang scrollable.
    """
    emp = get_object_or_404(employee, PIN=pin)

    today = date.today()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month

    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    qs = (
        transaction.objects.filter(UserID=emp, TTime__date__gte=first_day, TTime__date__lte=last_day)
        .select_related('SN')
        .order_by('TTime')
    )

    rows = []
    last_date = None
    for trx in qs:
        local_time = _to_local_time(trx.TTime)
        if local_time is None:
            continue
        trx_date = local_time.date()
        show_date = trx_date != last_date
        last_date = trx_date
        rows.append({
            'date': trx_date if show_date else None,
            'device': str(trx.SN) if trx.SN_id else '-',
            'time': local_time,
            'type_label': 'C/In' if _is_in_state(trx.State) else 'C/Out',
        })

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    return render(request, 'iclock/attendance_recap_card.html', {
        'target_employee': emp,
        'rows': rows,
        'year': year,
        'month': month,
        'month_label': f'{INDONESIAN_MONTHS.get(month, month)} {year}',
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
    })