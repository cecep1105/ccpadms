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
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole

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
from .services import backup_device_fingerprints, maybe_activate_after_pool_change, normalize_pin
from .views import INDONESIAN_DAYS, _is_in_state, _to_local_time
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


class BaseIclockViewSet(viewsets.ModelViewSet):
    """Base viewset: staff-only, dukung pencarian lewat ?q= (field dikonfigurasi per subclass)."""

    permission_classes = [IsAuthenticated, IsStaffRole]
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


class ActiveDeviceViewSet(BaseIclockViewSet):
    queryset = iclock.objects.select_related('DeptID').all().order_by('Alias')
    serializer_class = ActiveDeviceSerializer
    search_fields = ['SN', 'Alias']

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

    @action(detail=True, methods=['post'], url_path='transfer-finger')
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
class AttendanceRecapAPIView(APIView):
    """
    GET /api/v1/iclock/attendance-recap/?pin=&function=&pool=&device=&date_from=&date_to=&page=&page_size=
    Sama persis logic-nya dgn iclock/views.py::attendance_recap -- matrix
    PIN x tanggal berisi jam IN (paling awal)/OUT (paling akhir) per hari.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

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
    """GET /api/v1/iclock/employee-search/?q= -- autocomplete PIN/nama, dipakai Attendance Recap."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        results = []
        if len(q) >= 2:
            qs = employee.objects.filter(Q(PIN__icontains=q) | Q(EName__icontains=q)).order_by('PIN')[:15]
            results = [{'pin': e.PIN, 'name': e.EName or ''} for e in qs]
        return Response({'employees': results})


class AttendanceRecapEmployeeCardAPIView(APIView):
    """
    GET /api/v1/iclock/attendance-recap/<pin>/card/?year=&month=
    Rekap 1 employee, 1 bulan penuh (default bulan berjalan) -- daftar
    transaksi lengkap (bukan cuma ringkasan in-pertama/out-terakhir spt
    matrix utama).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

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
