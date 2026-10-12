"""
API untuk app 'iclock', dikonsumsi frontend Nuxt. Semua endpoint staff-only
(permission sama seperti akses dashboard). Business logic yang genuinely
dipakai bersama dashboard & API (auto-aktivasi Registered Device -> Active
Device) ada di services.py, bukan diduplikasi di sini.
"""
from collections import defaultdict
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission, IsStaffRole
from iclock.ws_utils import wsinfo

from .models import RegisteredDevice, department, devcmds, devlog, employee, fptemp, iclock, oplog, transaction
from .serializers import (
    ActiveDeviceSerializer,
    AttendanceRecapQuerySerializer,
    BackupFingerprintActionSerializer,
    DepartmentSerializer,
    DeviceCommandSerializer,
    DeviceLogSerializer,
    DeviceUserIdActionSerializer,
    EmployeeSerializer,
    FingerprintTemplateSerializer,
    GenericParamActionSerializer,
    NetworkParamsActionSerializer,
    OperationLogSerializer,
    RegisteredDeviceSerializer,
    TogglePrivilegeActionSerializer,
    TransactionSerializer,
    TransferFingerActionSerializer,
)
from . import services
from .services import backup_device_fingerprints, getemp_adms_prod, maybe_activate_after_pool_change, normalize_pin
from .views import INDONESIAN_DAYS, _is_in_state, _to_local_time
from .zk_client import (
    PRIVILEGE_ADMIN,
    PRIVILEGE_DEFAULT,
    DeviceConnectionError,
    delete_user_from_device,
    fetch_device_logs,
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


class BaseIclockViewSet(viewsets.ModelViewSet):
    """
    Base viewset: staff-only, dukung pencarian lewat ?q= (field
    dikonfigurasi per subclass) DAN sorting lewat ?ordering=field (atau
    ?ordering=-field utk descending) -- standar DRF OrderingFilter,
    dipakai frontend Next.js utk header kolom tabel yang bisa diklik.
    `ordering_fields = '__all__'` sbg default (semua field model boleh
    dipakai sort) -- override per subclass kalau perlu dibatasi.
    """

    permission_classes = [IsAuthenticated, IsStaffRole]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = '__all__'
    search_fields = []  # diisi subclass, mis. ['SN', 'Alias']

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('q')
        if search and self.search_fields:
            q_obj = Q()
            for field in self.search_fields:
                q_obj |= Q(**{f'{field}__icontains': search})
            qs = qs.filter(q_obj)
        return qs


class DepartmentViewSet(BaseIclockViewSet):
    queryset = department.objects.all().order_by('DeptName')
    serializer_class = DepartmentSerializer
    search_fields = ['DeptName']

    # GET (list/retrieve) TERSEDIA portal (can_view_active_device) --
    # dibutuhkan halaman portal Active Device utk isi dropdown "Pool
    # Tujuan" di dialog Transfer Finger (lihat portal/active-device/
    # _components/portal-device-actions-menu.tsx -- DeviceTransferFingerDialog
    # dipakai ULANG dari staff, & dialog itu perlu daftar department).
    # SEKADAR lihat NAMA department, bukan data sensitif -- aman
    # dibuka lebih luas drpd endpoint Active Device sendiri.
    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated(), HasFeaturePermission('iclock.can_view_active_device')()]
        return [permission() for permission in self.permission_classes]


class ActiveDeviceViewSet(BaseIclockViewSet):
    queryset = iclock.objects.select_related('DeptID').all().order_by('Alias')
    serializer_class = ActiveDeviceSerializer
    search_fields = ['SN', 'Alias','DeviceName']  # Alias & DeviceName sama-sama dicari utk ?q=, walau di DB beda kolom

    # 5 aksi PALING AMAN (lihat SEMUA -- BUKAN aksi tulis yg TERUS
    # ubah/hapus data device fisik) -- TERSEDIA portal (izin granular
    # can_view_active_device). SISANYA (reboot, network_params,
    # generic_param -- KHUSUSNYA generic_param yg pd dasarnya backdoor
    # KE PARAMETER APAPUN di device, live_users, backup_fingerprints,
    # user_toggle_privilege, user_delete) TETAP staff-only -- semua itu
    # aksi yg BISA merusak/mengubah konfigurasi device fisik kalau
    # dipakai sembarangan, DI LUAR cakupan yg disepakati portal.
    _PORTAL_SAFE_ACTIONS = {'list', 'retrieve', 'sync_time', 'live_logs', 'user_transfer_finger'}

    def get_permissions(self):
        if self.action in self._PORTAL_SAFE_ACTIONS:
            return [IsAuthenticated(), HasFeaturePermission('iclock.can_view_active_device')()]
        return [permission() for permission in self.permission_classes]

    # -----------------------------------------------------------------
    # Aksi device (pyzk, koneksi LANGSUNG ke device fisik) -- reuse fungsi
    # yang SAMA dgn dashboard web (iclock/zk_client.py), sudah dikonfirmasi
    # bekerja terhadap hardware sungguhan di sesi sebelumnya.
    # -----------------------------------------------------------------
    @action(detail=True, methods=['post'])
    def reboot(self, request, pk=None):
        """POST .../reboot/ -- reboot device fisik. Aksi disruptif, konfirmasi di sisi client."""
        device = self.get_object()
        success, message = reboot_device(device.IPAddress)
        return Response({'success': success, 'message': message}, status=status.HTTP_200_OK if success else status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['post'], url_path='sync-time')
    def sync_time(self, request, pk=None):
        """POST .../sync-time/ -- sinkronkan jam device fisik dgn jam server."""
        device = self.get_object()
        success, message = sync_device_time(device.IPAddress)
        return Response({'success': success, 'message': message}, status=status.HTTP_200_OK if success else status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['get', 'post'], url_path='network-params')
    def network_params(self, request, pk=None):
        """
        GET .../network-params/ -- baca IP/Netmask/Gateway SEKARANG dari device.
        POST .../network-params/ body: {new_ip, new_netmask, new_gateway} -- ubah parameter itu.
        """
        device = self.get_object()
        if request.method == 'GET':
            try:
                current_params = get_device_network_params(device.IPAddress)
            except DeviceConnectionError as exc:
                return Response({'success': False, 'message': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
            return Response(current_params)

        serializer = NetworkParamsActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        success, message = set_network_params(
            device.IPAddress,
            new_ip=serializer.validated_data.get('new_ip', ''),
            new_netmask=serializer.validated_data.get('new_netmask', ''),
            new_gateway=serializer.validated_data.get('new_gateway', ''),
        )
        return Response({'success': success, 'message': message}, status=status.HTTP_200_OK if success else status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['post'], url_path='generic-param')
    def generic_param(self, request, pk=None):
        """POST .../generic-param/ body: {action: get|set, param_name, param_value?, do_refresh?}."""
        device = self.get_object()
        serializer = GenericParamActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data['action'] == 'get':
            success, result = get_device_param(device.IPAddress, data['param_name'])
            if success:
                return Response({'success': True, 'param_name': data['param_name'], 'value': result})
            return Response({'success': False, 'message': result}, status=status.HTTP_502_BAD_GATEWAY)

        success, message = set_device_param(
            device.IPAddress, data['param_name'], data.get('param_value', ''), do_refresh=data.get('do_refresh', True),
        )
        return Response({'success': success, 'message': message}, status=status.HTTP_200_OK if success else status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['get'], url_path='live-users')
    def live_users(self, request, pk=None):
        """
        GET .../live-users/ -- konek LANGSUNG ke device, tampilkan user yang
        BENAR-BENAR tersimpan di memori device saat ini (beda dari tabel
        Employee, yang bisa saja belum sinkron). Filter ?pin=&name=, sort
        ?sort=&dir=, page ?page=&page_size= diproses manual di Python
        (sumbernya list biasa dari pyzk, bukan QuerySet).
        """
        device = self.get_object()
        try:
            users = fetch_device_users(device.IPAddress)
        except DeviceConnectionError as exc:
            return Response({'success': False, 'message': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        pin_filter = request.query_params.get('pin', '').strip()
        name_filter = request.query_params.get('name', '').strip()
        if pin_filter:
            users = [u for u in users if pin_filter.lower() in str(u.get('user_id') or '').lower()]
        if name_filter:
            users = [u for u in users if name_filter.lower() in str(u.get('name') or '').lower()]

        sort_map = {'user_id': 'user_id', 'name': 'name', 'privilege': 'privilege'}
        sort_key = sort_map.get(request.query_params.get('sort'), 'user_id')
        direction = request.query_params.get('dir') == 'desc'
        users.sort(key=lambda u: u.get(sort_key) or '', reverse=direction)

        page = int(request.query_params.get('page', 1) or 1)
        page_size = int(request.query_params.get('page_size', 20) or 20)
        start = (page - 1) * page_size
        page_users = users[start:start + page_size]

        return Response({'count': len(users), 'page': page, 'page_size': page_size, 'results': page_users})

    @action(detail=True, methods=['get'], url_path='live-logs')
    def live_logs(self, request, pk=None):
        """
        GET .../live-logs/ -- konek LANGSUNG ke device, tampilkan log
        absensi yang MASIH TERSIMPAN DI MEMORI DEVICE saat ini (BEDA dari
        tabel `transaction` di database -- itu cuma berisi log yang
        SUDAH ter-push/transfer, log ini bisa BELUM sampai server sama
        sekali). Filter ?pin=, sort ?sort=&dir=, page ?page=&page_size=
        diproses manual di Python (sumbernya list biasa dari pyzk, bukan
        QuerySet) -- SAMA PERSIS pola dgn live_users() di atas.
        """
        device = self.get_object()
        try:
            logs = fetch_device_logs(device.IPAddress)
        except DeviceConnectionError as exc:
            return Response({'success': False, 'message': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        pin_filter = request.query_params.get('pin', '').strip()
        if pin_filter:
            logs = [l for l in logs if pin_filter.lower() in str(l.get('user_id') or '').lower()]

        sort_map = {'user_id': 'user_id', 'timestamp': 'timestamp', 'status': 'status_label', 'punch': 'punch_label'}
        sort_key = sort_map.get(request.query_params.get('sort'), 'timestamp')
        # Default DESCENDING (log paling baru dulu) -- BEDA dari live_users
        # (default ASCENDING) krn utk LOG, yang paling relevan dilihat
        # PERTAMA biasanya yang PALING BARU, bukan yang PALING LAMA.
        direction = request.query_params.get('dir', 'desc') != 'asc'
        logs.sort(key=lambda l: l.get(sort_key) or '', reverse=direction)

        page = int(request.query_params.get('page', 1) or 1)
        page_size = int(request.query_params.get('page_size', 20) or 20)
        start = (page - 1) * page_size
        page_logs = logs[start:start + page_size]

        return Response({'count': len(logs), 'page': page, 'page_size': page_size, 'results': page_logs})

    @action(detail=True, methods=['post'], url_path='backup-fingerprints')
    def backup_fingerprints(self, request, pk=None):
        """POST .../backup-fingerprints/ body: {pin_pattern?} -- upsert user+template dari device fisik ke DB (fptemp)."""
        device = self.get_object()
        serializer = BackupFingerprintActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log_lines = backup_device_fingerprints(device, pin_pattern=serializer.validated_data.get('pin_pattern', ''))
        return Response({'log': log_lines})

    @action(detail=True, methods=['post'], url_path='user-toggle-privilege')
    def user_toggle_privilege(self, request, pk=None):
        """POST .../user-toggle-privilege/ body: {user_id, current_privilege?} -- toggle privilege LANGSUNG di device."""
        device = self.get_object()
        serializer = TogglePrivilegeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id = serializer.validated_data['user_id']
        current_privilege = serializer.validated_data.get('current_privilege', 0)
        new_privilege = PRIVILEGE_DEFAULT if current_privilege == PRIVILEGE_ADMIN else PRIVILEGE_ADMIN

        try:
            set_user_privilege_on_device(device.IPAddress, user_id, new_privilege)
        except DeviceConnectionError as exc:
            return Response({'success': False, 'message': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        employee.objects.filter(SN=device, PIN=normalize_pin(user_id)).update(Privilege=new_privilege)
        label = 'Admin' if new_privilege == PRIVILEGE_ADMIN else 'User biasa'
        return Response({'success': True, 'message': f"Privilege '{user_id}' berhasil diubah jadi {label}.", 'new_privilege': new_privilege})

    @action(detail=True, methods=['post'], url_path='user-delete')
    def user_delete(self, request, pk=None):
        """POST .../user-delete/ body: {user_id} -- hapus user LANGSUNG dari device fisik."""
        device = self.get_object()
        serializer = DeviceUserIdActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id = serializer.validated_data['user_id']

        try:
            deleted = delete_user_from_device(device.IPAddress, user_id)
        except DeviceConnectionError as exc:
            return Response({'success': False, 'message': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        employee.objects.filter(SN=device, PIN=normalize_pin(user_id)).delete()
        return Response({'success': True, 'deleted_from_device': deleted})

    @action(detail=True, methods=['post'], url_path='user-transfer-finger')
    def user_transfer_finger(self, request, pk=None):
        """
        POST .../user-transfer-finger/ body: {pins, from_device, to_pool, target_device?}
        Transfer fingerprint dari SOURCE DEVICE ke 1/banyak device tujuan
        (pool tujuan, atau 1 device spesifik) -- via pyzk LANGSUNG (bukan dari DB).
        """
        serializer = TransferFingerActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get('target_device'):
            targets = [(data['target_device'].IPAddress, str(data['target_device']))]
        else:
            targets = [(d.IPAddress, str(d)) for d in iclock.objects.filter(DeptID=data['to_pool'])]

        log_lines = transfer_fingerprints(data['from_device'].IPAddress, targets, data['pins'])
        return Response({'log': log_lines})


class RegisteredDeviceViewSet(BaseIclockViewSet):
    queryset = RegisteredDevice.objects.select_related('DeptID').all().order_by('SN')
    serializer_class = RegisteredDeviceSerializer
    search_fields = ['SN', 'DeviceName']

    def update(self, request, *args, **kwargs):
        """
        Sama seperti dashboard: kalau Pool ID berubah dari 0 -> non-0, otomatis
        copy device ini ke Active Device (kalau SN-nya belum ada di sana).
        Response menyertakan flag `activated_to_active_device` supaya Nuxt
        tahu kalau ada side-effect ini terjadi.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        old_dept_id = instance.DeptID_id  # tangkap SEBELUM divalidasi/disimpan

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        with db_transaction.atomic():
            self.perform_update(serializer)
            activated = maybe_activate_after_pool_change(serializer.instance, old_dept_id)

        data = dict(serializer.data)
        data['activated_to_active_device'] = activated
        return Response(data)


class EmployeeViewSet(BaseIclockViewSet):
    queryset = employee.objects.select_related('DeptID', 'SN').all().order_by('PIN')
    serializer_class = EmployeeSerializer
    search_fields = ['PIN', 'EName']

    @action(detail=True, methods=['post'], url_path='toggle-privilege')
    def toggle_privilege(self, request, pk=None):
        """
        POST .../toggle-privilege/ -- toggle privilege Admin<->User biasa DI
        TABEL EMPLOYEE. Kalau employee ini terhubung ke Active Device
        (SN terisi & device online), best-effort sync juga ke device fisiknya.
        """
        emp = self.get_object()
        new_privilege = PRIVILEGE_DEFAULT if emp.Privilege == PRIVILEGE_ADMIN else PRIVILEGE_ADMIN
        emp.Privilege = new_privilege
        emp.save(update_fields=['Privilege'])

        device_synced = False
        device_error = None
        if emp.SN_id and emp.SN.IPAddress:
            try:
                set_user_privilege_on_device(emp.SN.IPAddress, emp.PIN, new_privilege)
                device_synced = True
            except DeviceConnectionError as exc:
                device_error = str(exc)

        return Response({
            'success': True,
            'new_privilege': new_privilege,
            'device_synced': device_synced,
            'device_error': device_error,
        })

    @action(detail=True, methods=['post'], url_path='transfer-finger', permission_classes=[HasFeaturePermission('iclock.can_transfer_finger')])
    def transfer_finger(self, request, pk=None):
        """
        POST .../transfer-finger/ body: {to_pool, target_device?}
        Transfer fingerprint 1 employee ke device tujuan -- SUMBER dari
        DATABASE (fptemp), BUKAN dari device fisik employee ini (jadi
        device asalnya TIDAK perlu online), asal template-nya sudah pernah
        di-backup (lihat ActiveDeviceViewSet.backup_fingerprints).
        """
        emp = self.get_object()
        db_templates_qs = fptemp.objects.filter(UserID=emp)
        if not db_templates_qs.exists():
            return Response({
                'success': False,
                'message': f"Employee '{emp.PIN}' belum punya template fingerprint di database -- backup dulu dari device fisik.",
            }, status=status.HTTP_400_BAD_REQUEST)

        # Field yang genuinely dipakai di endpoint ini cuma to_pool/target_device
        # (PIN & sumber template sudah pasti dari `emp`, beda dgn versi Active Device).
        to_pool_id = request.data.get('to_pool')
        target_device_id = request.data.get('target_device')
        if not to_pool_id:
            return Response({'success': False, 'message': "'to_pool' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        to_pool = department.objects.filter(pk=to_pool_id).first()
        if to_pool is None:
            return Response({'success': False, 'message': f"Pool '{to_pool_id}' tidak ditemukan."}, status=status.HTTP_400_BAD_REQUEST)
        target_device = iclock.objects.filter(pk=target_device_id).first() if target_device_id else None

        if target_device:
            targets = [(target_device.IPAddress, str(target_device))]
        else:
            targets = [(d.IPAddress, str(d)) for d in iclock.objects.filter(DeptID=to_pool)]

        db_templates = [{'fid': t.FingerID, 'valid': t.Valid, 'template_b64': t.Template} for t in db_templates_qs]
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
        return Response({'log': log_lines, 'db_template_count': db_templates_qs.count()})


class FingerprintTemplateViewSet(BaseIclockViewSet):
    queryset = fptemp.objects.select_related('UserID', 'SN').all().order_by('-UTime')
    serializer_class = FingerprintTemplateSerializer
    search_fields = ['UserID__PIN', 'UserID__EName']


class TransactionViewSet(BaseIclockViewSet):
    queryset = transaction.objects.select_related('UserID', 'SN').all().order_by('-TTime')
    serializer_class = TransactionSerializer
    search_fields = ['UserID__PIN', 'UserID__EName']


class OperationLogViewSet(BaseIclockViewSet):
    queryset = oplog.objects.select_related('SN').all().order_by('-OPTime')
    serializer_class = OperationLogSerializer
    search_fields = ['SN__SN']


class DeviceLogViewSet(BaseIclockViewSet):
    queryset = devlog.objects.select_related('SN').all().order_by('-OpTime')
    serializer_class = DeviceLogSerializer
    search_fields = ['SN__SN', 'OP']


class DeviceCommandViewSet(BaseIclockViewSet):
    queryset = devcmds.objects.select_related('SN', 'User').all().order_by('-CmdCommitTime')
    serializer_class = DeviceCommandSerializer
    search_fields = ['SN__SN', 'CmdContent']

    def perform_create(self, serializer):
        # User (admin pengaju) otomatis dari request, sama seperti dashboard,
        # bukan field yang dikirim client.
        serializer.save(User=self.request.user)


# ---------------------------------------------------------------------------
# ATTENDANCE RECAP (fitur besar: matrix PIN x tanggal) & pendukungnya
# ---------------------------------------------------------------------------
class HasAttendanceRecapPermission(BasePermission):
    """
    Cek permission SESUAI `recap_type` yang diminta (all/kantin/driver) --
    BEDA dari `HasFeaturePermission` biasa (OR sederhana antar beberapa
    permission utk 1 view) krn di sini permission yang RELEVAN tergantung
    PARAMETER request (?recap_type=), bukan cuma view-nya. Staff/superuser
    SELALU lolos (spt HasFeaturePermission), user non-staff HARUS py
    permission yang PERSIS sesuai jenis rekap yang diminta -- user yang
    cuma dikasih izin 'Rekap Kantin' TIDAK BISA akses 'Rekap Driver' atau
    'Rekap All' dgn cara ganti parameter URL saja.

    Logic INTI ada di iclock/services.py::has_attendance_recap_permission
    -- SATU sumber, dipakai BARENG dgn iclock/views.py::attendance_recap
    (versi server-rendered/Django, dituju card dashboard) supaya KEDUANYA
    SELALU konsisten (lihat catatan lengkap di services.py -- versi
    Django SEMPAT ketinggalan update saat granular permission ditambah).
    """

    def has_permission(self, request, view):
        recap_type = request.query_params.get('recap_type', 'all')
        return services.has_attendance_recap_permission(request.user, recap_type)


class AttendanceRecapAPIView(APIView):
    """
    GET /api/v1/iclock/attendance-recap/?recap_type=all|kantin|driver&pin=&function=&pool=&device=&date_from=&date_to=&page=&page_size=
    Sama persis logic-nya dgn iclock/views.py::attendance_recap -- matrix
    PIN x tanggal berisi jam IN (paling awal)/OUT (paling akhir) per hari.

    3 varian (`recap_type`, granular permission via HasAttendanceRecapPermission
    di atas):
    - 'all' (default): semua data, TANPA filter Function tambahan (perilaku LAMA, tidak berubah).
    - 'kantin': HANYA transaksi yg Function-nya KANTIN (device/pool ber-function
      KANTIN di mclock.PoolDeviceFunction -- lihat mattendance/function_utils.py
      yg MENENTUKAN Function='X' persis krn alasan itu, jadi filter di sini
      cukup cocokkan Function yg SUDAH tersimpan, tidak perlu join ulang).
    - 'driver': HANYA transaksi yg Function-nya salah satu kode DRIVER-*
      (settings.DEVICEFUNCTION yg value-nya diawali 'DRIVER' -- ada BEBERAPA
      vendor/rute driver berbeda, kode BEDA-BEDA tapi SEMUA dihitung 'Driver').
    """
    permission_classes = [IsAuthenticated, HasAttendanceRecapPermission]

    def get(self, request):
        serializer = AttendanceRecapQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        date_from, date_to = data['date_from'], data['date_to']
        date_columns = []
        d = date_to
        while d >= date_from:
            date_columns.append({'date': d.isoformat(), 'day_name': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][d.weekday()]})
            d -= timedelta(days=1)

        base_qs = transaction.objects.filter(TTime__date__gte=date_from, TTime__date__lte=date_to)

        recap_type = data.get('recap_type', 'all')
        if recap_type == 'kantin':
            base_qs = base_qs.filter(Function__in=services.kantin_function_codes())
        elif recap_type == 'driver':
            base_qs = base_qs.filter(Function__in=services.driver_function_codes())

        if data.get('pin'):
            base_qs = base_qs.filter(UserID__PIN__iregex=data['pin'])
        if data.get('function'):
            base_qs = base_qs.filter(Function=data['function'])
        if data.get('device'):
            base_qs = base_qs.filter(SN=data['device'])
        elif data.get('pool'):
            base_qs = base_qs.filter(SN__DeptID=data['pool'])

        pin_list = sorted(set(base_qs.values_list('UserID__PIN', flat=True)))
        page = int(request.query_params.get('page', 1) or 1)
        page_size = int(request.query_params.get('page_size', 20) or 20)
        start = (page - 1) * page_size
        page_pins = pin_list[start:start + page_size]

        recap_rows = []
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

            for i, pin in enumerate(page_pins):
                row = {'no': start + i + 1, 'pin': pin, 'name': names.get(pin, ''), 'cells': []}
                for col in date_columns:
                    col_date = date.fromisoformat(col['date'])
                    day_data = matrix[pin].get(col_date, {'in': [], 'out': []})
                    in_times = sorted(day_data['in'])
                    out_times = sorted(day_data['out'])
                    row['cells'].append({
                        'date': col['date'],
                        'in_first': in_times[0].isoformat() if in_times else None,
                        'in_count': len(in_times),
                        'out_last': out_times[-1].isoformat() if out_times else None,
                        'out_count': len(out_times),
                    })
                recap_rows.append(row)

        return Response({
            'count': len(pin_list),
            'page': page,
            'page_size': page_size,
            'date_columns': date_columns,
            'results': recap_rows,
        })


class EmployeeSearchAPIView(APIView):
    """
    GET /api/v1/iclock/employee-search/?q= -- autocomplete PIN/nama, dipakai
    Attendance Recap (staff) DAN halaman Transfer Finger non-staff (perlu
    'id' -- BUKAN cuma PIN -- krn endpoint transfer-finger dipanggil pakai
    PK numerik, bukan PIN) DAN halaman Generate ID Card (staff & portal,
    cari employee by PIN utk karyawan/driver).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission(
        'iclock.can_transfer_finger', 'iclock.can_view_attendance_recap',
        'iclock.can_view_attendance_recap_kantin', 'iclock.can_view_attendance_recap_driver',
        'iclock.can_view_idcard',
    )]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        results = []
        if len(q) >= 2:
            qs = employee.objects.filter(Q(PIN__icontains=q) | Q(EName__icontains=q)).order_by('PIN')[:15]
            results = [{'id': e.id, 'pin': e.PIN, 'name': e.EName or ''} for e in qs]
        return Response({'employees': results})


class DeviceFunctionChoicesAPIView(APIView):
    """
    GET /api/v1/iclock/device-function-choices/ -- daftar {value, label}
    dari settings.DEVICEFUNCTION, dipakai isi dropdown Function code
    (Active Device, Attendance Recap DASHBOARD & PORTAL, dst) supaya
    SELALU sinkron dgn konfigurasi backend -- SEBELUMNYA field ini plain
    text input di frontend (rawan salah ketik, & admin harus HAPAL kode
    apa saja yang valid).

    Izin akses diperluas dari SEBELUMNYA staff-only -- user non-staff yg
    py izin granular Rekap Absensi (All/Kantin/Driver) SEKARANG JUGA
    perlu endpoint ini (halaman portal /portal/attendance-recap, dropdown
    Function baru utk user izin 'All'). Response TETAP kirim SEMUA kode
    apa adanya (TIDAK difilter di sini) -- penyaringan kode KANTIN/DRIVER-*
    sesuai izin granular user dikerjakan di FRONTEND (RecapFilterBar.tsx/
    PortalRecapFilterBar.tsx), SAMA persis pola kedua tempat itu, supaya
    logic filter-nya di 1 tempat per platform (React), bukan dobel di
    backend & frontend.
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission(
        'iclock.can_view_attendance_recap', 'iclock.can_view_attendance_recap_kantin', 'iclock.can_view_attendance_recap_driver',
    )]

    def get(self, request):
        choices = [{'value': k, 'label': f'{k} — {v}'} for k, v in settings.DEVICEFUNCTION.items()]
        return Response({'choices': choices})


class PoolDeviceChoicesAPIView(APIView):
    """
    GET /api/v1/iclock/pool-device-choices/?pool_id= -- versi RINGAN &
    READ-ONLY dari Department/ActiveDevice, KHUSUS isi dropdown Pool &
    Device di form Transfer Finger DAN Rekap Absensi portal non-staff
    (padanan iclock/views.py::ajax_devices_by_pool dashboard Django). SENGAJA
    endpoint TERPISAH dari DepartmentViewSet/ActiveDeviceViewSet biasa
    (yang staff-only & expose SEMUA field termasuk IP/MAC/konfigurasi
    PUSH SDK) -- user non-staff yang cuma dikasih izin
    'can_transfer_finger' TIDAK PERLU & TIDAK SEHARUSNYA lihat detail
    device selengkap itu, cukup {id, name} sekadar buat pilihan dropdown.
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission(
        'iclock.can_transfer_finger', 'iclock.can_view_attendance_recap',
        'iclock.can_view_attendance_recap_kantin', 'iclock.can_view_attendance_recap_driver',
    )]

    def get(self, request):
        pools = list(department.objects.order_by('DeptName').values('DeptID', 'DeptName'))
        data = {'pools': [{'id': p['DeptID'], 'name': p['DeptName']} for p in pools]}

        pool_id = request.query_params.get('pool_id')
        if pool_id:
            devices = list(iclock.objects.filter(DeptID_id=pool_id).order_by('Alias').values('SN', 'Alias', 'DeviceName'))
            data['devices'] = [{'sn': d['SN'], 'name': d['Alias'], 'device_name': d['DeviceName']} for d in devices]

        return Response(data)


class AttendanceRecapExportAPIView(APIView):
    """
    GET /api/v1/iclock/attendance-recap/export/?recap_type=&pin=&function=&pool=&device=&date_from=&date_to=
    -- export .xlsx dgn format RAPI (lihat iclock/xlsx_export.py utk detail
    styling) -- filter & permission SAMA PERSIS dgn AttendanceRecapAPIView
    (di atas), TAPI TIDAK dipaginasi (SEMUA baris yg cocok filter).
    Response BINARY (bukan JSON) -- pakai HttpResponse Django langsung
    (bukan DRF Response) drpd DRF coba nego content-type.
    """
    permission_classes = [IsAuthenticated, HasAttendanceRecapPermission]

    def get(self, request):
        serializer = AttendanceRecapQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recap_type = data.get('recap_type', 'all')

        from .xlsx_export import build_attendance_recap_workbook, workbook_to_bytes

        filter_extra = []
        pool = data.get('pool')
        device = data.get('device')
        if pool:
            filter_extra.append(f'Pool: {pool.DeptName}')
        if device:
            filter_extra.append(f'Device: {device.Alias}')

        wb = build_attendance_recap_workbook(
            recap_type=recap_type,
            pin=data.get('pin'),
            function=data.get('function'),
            pool=pool.DeptID if pool else None,
            device=device.SN if device else None,
            date_from=data['date_from'],
            date_to=data['date_to'],
            filter_summary_extra=filter_extra,
        )

        filename = f"rekap-absensi-{recap_type}-{data['date_from']}-{data['date_to']}.xlsx"
        response = HttpResponse(
            workbook_to_bytes(wb),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class AttendanceRecapEmployeeCardAPIView(APIView):
    """
    GET /api/v1/iclock/attendance-recap/<pin>/card/?year=&month=
    Rekap 1 employee, 1 bulan penuh (default bulan berjalan) -- daftar
    transaksi lengkap (bukan cuma ringkasan in-pertama/out-terakhir spt
    matrix utama).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_attendance_recap')]

    def get(self, request, pin):
        from calendar import monthrange

        emp = employee.objects.filter(PIN=pin).first()
        if emp is None:
            return Response({'code': 'not_found', 'message': f"Employee dgn PIN '{pin}' tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        today = date.today()
        try:
            year = int(request.query_params.get('year', today.year))
            month = int(request.query_params.get('month', today.month))
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
        for trx in qs:
            local_time = _to_local_time(trx.TTime)
            if local_time is None:
                continue
            rows.append({
                'date': local_time.date().isoformat(),
                'time': local_time.isoformat(),
                'device': str(trx.SN) if trx.SN_id else None,
                'type': 'IN' if _is_in_state(trx.State) else 'OUT',
            })

        return Response({
            'pin': emp.PIN,
            'name': emp.EName,
            'year': year,
            'month': month,
            'rows': rows,
        })


class MyAttendanceCardAPIView(APIView):
    """
    GET /api/v1/iclock/my-attendance/?year=&month=
    Versi SELF-SERVICE dari AttendanceRecapEmployeeCardAPIView di atas
    (SAMA PERSIS bentuk response & logic query-nya, SENGAJA sedikit
    duplikasi drpd refactor berisiko ke view yg SUDAH jalan) -- BEDA
    utama:
    - TIDAK BUTUH parameter <pin> di URL & TIDAK BUTUH permission
      granular can_view_attendance_recap SAMA SEKALI -- endpoint ini
      utk lihat data ABSENSI DIRI SENDIRI, konsepnya beda TOTAL dari
      "lihat rekap absensi ORANG LAIN" (itu yg granular permission-nya
      atur). Employee yg dilihat ditentukan LANGSUNG dari
      `request.user.EmpID` (link opsional User<->Employee, lihat
      accounts/models.py), BUKAN dari input user -- TIDAK ADA CARA
      user portal minta data absensi PIN/employee LAIN lewat endpoint
      ini (beda dari endpoint umum yg terima <pin> bebas).
    - User yang akunnya TIDAK py EmpID (belum dikaitkan ke data
      employee) dapat 404 dgn pesan jelas (BUKAN 403 -- ini bukan soal
      "tidak diizinkan", tapi "datanya memang belum ada/terkait").
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from calendar import monthrange

        emp = request.user.EmpID
        if emp is None:
            return Response(
                {'code': 'not_linked', 'message': 'Akun Anda belum terkait dengan data Employee (PIN absensi). Hubungi admin untuk mengaitkan akun Anda.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        today = date.today()
        try:
            year = int(request.query_params.get('year', today.year))
            month = int(request.query_params.get('month', today.month))
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
        for trx in qs:
            local_time = _to_local_time(trx.TTime)
            if local_time is None:
                continue
            rows.append({
                'date': local_time.date().isoformat(),
                'time': local_time.isoformat(),
                'device': str(trx.SN) if trx.SN_id else None,
                'type': 'IN' if _is_in_state(trx.State) else 'OUT',
            })

        return Response({
            'pin': emp.PIN,
            'name': emp.EName,
            'year': year,
            'month': month,
            'rows': rows,
        })



def convert_hhmm_to_minutes(time_str):
    try:
        hours_str, minutes_str = time_str.split(':')
        hours = int(hours_str)
        minutes = int(minutes_str)
        total_minutes = (hours * 60) + minutes
        return total_minutes
    except ValueError:
        print("Invalid time format. Please use HH:MM.")
        return None

class AttendanceRecapAdmsProdAPIView(APIView):
    def post(self, request):
        from django.core.paginator import Paginator
        import pandas as pd
        import paramiko
        from django.core.cache import cache
        from datetime import datetime
        from django.utils import translation
        from django.utils.formats import date_format
        import json

        postdata = request.data
        pool = postdata.get('pool', None)
        poolname = postdata.get('poolname','')
        device = postdata.get('device', None)
        function = postdata.get('fnc', None)
        empgroup = postdata.get('empgroup', '')
        perpage = postdata.get('perpage', 20)
        page = postdata.get('page', 1)
        format = postdata.get('format', 'table')
        searchnik = postdata.get('searchtext', '')
        timeid = postdata.get('timeid', '')

        print(postdata)

        if 'nikNames' in cache:
            niknames = cache.get('nikNames')
        else:
            niknames = getemp_adms_prod('')
            cache.set('nikNames', niknames)

        kantindevs = []
        try:
            kantindevs = [ x['SN'] for x in iclock.objects.filter(Function='X').values('SN')]
        except: pass

        arrSN = []
        if device:
            arrSN.append(device)
        elif pool:
            arrSN = [x['SN'] for x in iclock.objects.filter(DeptID=pool).values('SN')]
        else:
            pass

        files = [ "%s/masterlog/%s.txt" % (settings.BASE_DIR, d.strftime('%m%Y/%d'))  for d in pd.date_range(datetime.strftime(datetime.today().replace(day=1),'%Y/%m/%d'),datetime.strftime(datetime.today(),'%Y/%m/%d'))]
        ftpfiles = []
        smbfiles = []

        try:
            d1 = postdata.get('datefrom',datetime.now().strftime('%Y/%m/%d'))
            d2 = postdata.get('dateto',datetime.now().strftime('%Y/%m/%d'))
            if int(d1.replace('/', '')) < int(d2.replace('/', '')):
                files = ["%s/data/masterlog/%s.txt" % (settings.BASE_DIR, d.strftime('%m%Y/%d'))  for d in pd.date_range(d1,d2)]
                ftpfiles = ["%s/masterlog/%s.txt" % ('djangoapp/mysite', d.strftime('%m%Y/%d'))  for d in pd.date_range(d1,d2)]
                smbfiles = ["data/masterlog/%s.txt" % (d.strftime('%m%Y/%d'))  for d in pd.date_range(d1,d2)]

            else:
                files = ["%s/data/masterlog/%s.txt" % (settings.BASE_DIR, d.strftime('%m%Y/%d'))  for d in pd.date_range(d2,d1)]
                ftpfiles = ["%s/masterlog/%s.txt" % ('djangoapp/mysite', d.strftime('%m%Y/%d'))  for d in pd.date_range(d2,d1)]
                smbfiles = ["data/masterlog/%s.txt" % (d.strftime('%m%Y/%d'))  for d in pd.date_range(d2,d1)]
        except Exception as e:
            pass


        inoutdata = {}
        _nikdata = []

        opener = None
        datasource = 'ftp'
        sftp = None

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(settings.ADMSPROD_HOST,username=settings.ADMSPROD_USERNAME,password=settings.ADMSPROD_PASSWORD)
        sftp = ssh_client.open_sftp()
        sftp.chdir('.')
        remote_base_dir = sftp.getcwd()

        for _ftpf in ftpfiles:
            ftpf = f"{remote_base_dir}/{_ftpf}"
            r = []
            try:
                with sftp.open(ftpf,'r') as r:
                    for line in r:
                        _SN, _NIK, _TTIME, _CTYPE = line.strip().split(',')
                        if _NIK not in _nikdata:
                            if function in 'X':
                                if _SN in arrSN or (len(_SN) == 4 and _SN[-1] == 'M'):
                                    if searchnik == '':
                                        _nikdata.append(_NIK)
                                    else:
                                        if _NIK[:len(searchnik)] == searchnik:
                                            _nikdata.append(_NIK)
                            else:
                                if searchnik == '':
                                    _nikdata.append(_NIK)
                                else:
                                    if _NIK[:len(searchnik)] == searchnik:
                                        _nikdata.append(_NIK)

            except Exception as e:
                print(e)

        if empgroup:
            folder = '%s/data/EMPGROUP' % settings.BASE_DIR
            filename = "%s/%s.txt" % (folder, empgroup)
            with open(filename, 'r') as f:
                _nikdata  = [d.strip() for d in f.readlines() if d.strip() != '' ]

        if function in settings.DEVICEFUNCTION.keys() and function != 'X':
            _nikdata = list(filter(lambda x: x[:1] in function, _nikdata))

        counter = int(perpage) * (int(page)-1) + 0

        workbook = None
        worksheet = None
        y = 0
        x = 0

        if format == 'table':
            paginator = Paginator(_nikdata, perpage)
            if perpage >0:
                _nikdata = paginator.page(page)
        else:
            import xlsxwriter
            paginator = Paginator(_nikdata, len(_nikdata))
            if perpage >0:
                _nikdata = paginator.page(page)

            workbook = xlsxwriter.Workbook("%s.xlsx" % 'inoutdata')
            worksheet = workbook.add_worksheet()
            cell_format1 = workbook.add_format({
                'bold': True,
                'font_color': 'blue',
                'font_size': 12,
                'text_wrap': True,
                'valign': 'vcenter',
                'align': 'center',
                'border': 1,
                'bg_color': 'yellow'
            })
            cell_format2 = workbook.add_format({
                'bold': False,
                'font_color': 'black',
                'font_size': 12,
                'text_wrap': True,
                'valign': 'vcenter',
                'align': 'center',
                'border': 1,
            })

            y = 4
            x = 1

        rowdata = []
        for nik in _nikdata:
            totalperhari = []
            data = []
            dataabsen = []

            sfiles = []
            if datasource == 'ftp':
                sfiles = ftpfiles
            elif datasource == 'smb':
                sfiles = smbfiles
            else:
                sfiles = files

            for filename in sfiles:
                _date = datetime.strptime(filename[-13:-4], "%m%Y/%d")
                translation.activate('in')
                datename = datetime.strftime(_date, '%d%m%Y')
                dayname = "%s, %s" % (date_format(_date, 'l'), datetime.strftime(_date, '%d/%m/%Y'))
                datatgl = []

                try:
                    f = [line.strip() for line in sftp.open(filename, 'r')]
                    for line in f:
                        datacheck = {}
                        row = {}
                        try:
                            tgl = line.strip().split(',')[2].split()[0]
                        except Exception as e:
                            print(e)
                            continue

                        if str(int(nik)) in line.strip():
                            SN, NIK, TTIME, CTYPE = line.strip().split(',')
                            name = ''
                            try: name = list(filter(lambda x: x['badgenumber'] == NIK.zfill(9) ,niknames))[0]['name']
                            except Exception as e:
                                pass

                            row = {
                                'id': counter,
                                'device': 'dev',
                                'nik': NIK,
                                'name': name,
                                'tdate': TTIME.split()[0],
                                'ttime': TTIME.split()[1],
                                'ctype': CTYPE
                            }

                            devname = SN
                            try: devname = RegisteredDevice.objects.get(SN=SN).DeviceName
                            except Exception as e:
                                # print(e)
                                pass

                            datacheck = {
                                'id': counter,
                                'device': devname,
                                'sn': SN,
                                'nik': NIK,
                                'name': name,
                                'tdate': TTIME.split()[0],
                                'ttime': TTIME.split()[1],
                                'ctype': CTYPE
                            }

                            if function in 'X':
                                if SN in arrSN:
                                    datatgl.append(datacheck)
                                    data.append(row)
                            else:
                                if SN in kantindevs:
                                    continue
                                datatgl.append(datacheck)
                                data.append(row)

                    dt = []
                    dt_i = list(filter(lambda d: d['ctype'] == '0',datatgl))
                    dt_o = list(filter(lambda d: d['ctype'] !='0',datatgl))
                    try: dt.append(dt_i[0])
                    except: pass
                    try: dt.append(dt_o[-1])
                    except: pass


                    dataabsen.append({ 'tanggal': dayname, 'detail': dt if function=='X' else datatgl,  'detailfull': datatgl  })
                except Exception as e:
                    dataabsen.append({'tanggal': dayname, 'detail': [],  'detailfull': []  })
                    # print(e)

            info = {
                'message': '%-4s/%-4d: %-9s' % (counter+1, len(_nikdata),nik),
                'data': {'id': counter, 'total_record': paginator.count if format == 'table' else len(_nikdata),
                         'total': len(_nikdata), 'progress': int(100 * (counter + 1) / len(_nikdata)), 'nik': nik,
                         'inoutdata': { f"{nik}":  dataabsen }
                        },
                'target_id': 'progressbar'
            }

            _section = 'inout' if format=='table' else 'inoutxls'

            absen_length = sum(len(d['detail']) for d in dataabsen)
            if absen_length > 0:
                wsinfo('iclock', _section, info)
                inoutdata[nik] = dataabsen
            else:
                continue

            if format == 'excel':
                x = 1
                worksheet.write(y, x-1, str(counter+1).zfill(3),workbook.add_format({'bold': False, 'font_color': 'black', 'valign': 'vcenter', 'align': 'center', 'border': 0}))
                worksheet.write(y, x, nik,workbook.add_format({'bold': False, 'font_color': 'black', 'font_size': 14, 'valign': 'vcenter', 'align': 'center', 'border': 1}))
                name = ''
                try: name = list(filter(lambda x: x['badgenumber'] == nik.zfill(9), niknames))[0]['name']
                except: pass
                x = 2
                worksheet.write(y, x, name,workbook.add_format({'bold': False, 'font_color': 'black', 'font_size': 14, 'valign': 'vcenter', 'align': 'left', 'border': 1}))
                worksheet.write(3, 2, 'NAMA', workbook.add_format({'bold': True, 'font_color': 'black', 'font_size': 16, 'valign': 'vcenter', 'align': 'center', 'border': 1}))
                worksheet.write(3, 1, 'NIK', workbook.add_format({'bold': True, 'font_color': 'black', 'font_size': 16, 'valign': 'vcenter', 'align': 'center', 'border': 1}))
                emptydate=0
                daycount = []
                for dt in dataabsen:
                    dc=0
                    if(len(dt['detail'])) > 0:
                        emptydate = emptydate + 1
                    header = '\n'.join(dt['tanggal'].split(', '))
                    celldata = '\n'.join(["%s|%s|%s" % (v['ttime'], v['ctype'],v['device']) for v in dt['detail']])
                    if function == 'X':
                        arrTime = celldata.split('\n')
                        if len(arrTime) > 1:
                            arrTimeInMinutes = [{ 't1': a, 't2': convert_hhmm_to_minutes(a.split('|')[0])} for a in arrTime]
                            min_time_dict = min(arrTimeInMinutes, key=lambda d: d["t2"])
                            max_time_dict = max(arrTimeInMinutes, key=lambda d: d["t2"])
                            timediff = (max_time_dict['t2'] - min_time_dict['t2'])
                            if timediff > 3*60:
                                mindata = min_time_dict['t1']
                                maxdata = max_time_dict['t1']

                                celldata = '\n'.join([mindata,maxdata])
                                dc=2
                            else:
                                celldata = max_time_dict['t1']
                                dc=1
                        else:
                            dc=1 if celldata else 0

                    if y==4:
                        worksheet.write(y-1, x + 1, header, cell_format1)
                        worksheet.set_column(y-1, x + 1, 12)
                    if x==1:
                        cellf = cell_format1.set_align('vcenter')
                        worksheet.write(y, x - 1, counter+1, cellf)

                    if dc>1:
                        worksheet.write(y, x + 1, celldata, cell_format1)
                    else:
                        worksheet.write(y, x + 1, celldata, cell_format2)
                    daycount.append(dc)
                    x = x + 1

                if function == 'X':
                    if y==4:
                        worksheet.write(y-1, x + 1, 'JUMLAH', workbook.add_format({'bold': True, 'font_color': 'black', 'font_size': 12, 'valign': 'vcenter', 'align': 'center', 'border': 1}))
                    # cetak total per NIK (yg makan lebih dari 1x dianggap 1)
                    worksheet.write_formula(y, x + 1, '=COUNTA(%s%s..%s%s)' % (chr(68), y + 1, chr(68 + len(dataabsen) - 1), y + 1), cell_format1)

                if emptydate > 0:
                    y += 1
                    rowdata.append(daycount)
                else:
                    counter = counter-1
                    nx = 0
                    for dt in dataabsen:
                        worksheet.write(y, nx + 1, '', cell_format2)
            counter += 1
        columns = ['id', 'device', 'nik', 'tdate', 'ttime', 'ctype']

        totalperhari=0
        if len(rowdata)>0:
            for n in range(0, len(dataabsen)):
                sumdt = 0
                for m in rowdata:
                    sumdt += m[n]

                totalperhari.append(sumdt)


        if format == 'excel':
            import os
            from django.http import FileResponse
            worksheet.autofit()

            if function == 'X':
                merge_format = workbook.add_format({
                    'bold': 1,
                    'font_size': 16,
                    'border': 0,
                    'align': 'center',
                    'valign': 'vcenter',
                    'fg_color': 'green',
                })
                worksheet.merge_range(0,1,0,len(dataabsen)+3,'title1',merge_format)
                worksheet.merge_range(1,1,1,len(dataabsen)+3,'title2',merge_format)
                worksheet.write(0, 1, 'DATA ABSENSI KANTIN: %s to %s' % (postdata['datefrom'],postdata['dateto']), merge_format)
                worksheet.write(1, 1, poolname, merge_format)
                worksheet.write(y, 0, '', workbook.add_format({'bold': False, 'font_color': 'black', 'valign': 'vtop', 'align': 'left', 'border': 0}))
                worksheet.write(y, 1, '', workbook.add_format({'bold': False, 'font_color': 'black', 'valign': 'vtop', 'align': 'left', 'border': 0}))
                worksheet.write(y, 2, 'JUMLAH', workbook.add_format({'bold': True, 'font_color': 'black', 'font_size': 16, 'valign': 'vcenter', 'align': 'center', 'border': 0}))


                #cetak total per NIK termasuk lebih dari 1x makan
                for i,v in enumerate(rowdata):
                    worksheet.write(i+4,len(dataabsen)+4,sum(v),cell_format2)

                for n in range(0,len(dataabsen)):
                    sumdt = 0
                    for m in rowdata:
                        sumdt += m[n]

                    totalperhari.append(sumdt)

                    # cetak total per day (yg makan lebih dari 1x dianggap 1)
                    worksheet.write_formula(y,n+3,'=COUNTA(%s5..%s%s)' %(chr(68+n),chr(68+n), y), cell_format1)

                    # cetak total per day termasuk lebih dari 1x makan
                    worksheet.write(y+1, n + 3, sumdt, cell_format2)

                worksheet.write_formula(y, len(dataabsen) + 3, '=SUM(D%s..%s%s)' % (y+1, chr(68 + len(dataabsen)-1),y+1), merge_format)
                worksheet.write_formula(y+1, len(dataabsen) + 4, '=SUM(D%s..%s%s)' % (y+2, chr(68 + len(dataabsen)-1),y+2), merge_format)
                worksheet.freeze_panes(4, 0)
            worksheet.set_column(1, 1, 14)
            workbook.close()

            file_name = 'inoutdata.xlsx'
            path_to_file = os.path.realpath(file_name)
            response = FileResponse(open(path_to_file, 'rb'))
            response['Content-Disposition'] = 'inline; filename=' + file_name
            return response

        resp = json.dumps({
            'total_record': paginator.count,
            'total_page': paginator.num_pages,
            'data': inoutdata,
            'sumdata': totalperhari,
            'params': postdata,
            'current_page': page
        })
        return HttpResponse(resp, 'application/json')

        
