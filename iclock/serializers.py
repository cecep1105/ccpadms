"""
Serializer DRF untuk app 'iclock', dipakai oleh api_views.py (dikonsumsi
frontend Nuxt). Field yang diekspos di masing-masing serializer sengaja
disamakan dengan field yang ada di form dashboard (forms.py) supaya
kapabilitas API & dashboard konsisten.
"""
from rest_framework import serializers

from .models import RegisteredDevice, department, devcmds, devlog, employee, fptemp, iclock, oplog, transaction


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = department
        fields = ['DeptID', 'DeptName', 'NetID', 'DeptRouter', 'DeptSubnet']

    def validate_DeptID(self, value):
        # DeptID adalah primary key -> tidak boleh diubah setelah dibuat (mirip SN di ActiveDevice)
        if self.instance is not None and self.instance.pk != value:
            raise serializers.ValidationError('Pool ID tidak bisa diubah setelah dibuat.')
        return value


class ActiveDeviceSerializer(serializers.ModelSerializer):
    DeptName = serializers.CharField(source='DeptID.DeptName', read_only=True, default=None)

    class Meta:
        model = iclock
        fields = [
            'SN', 'Alias', 'DeptID', 'DeptName', 'Function', 'IPAddress', 'MAC', 'TZAdj',
            'State', 'LastActivity', 'PushVersion',
            # Konfigurasi PUSH SDK per-device (test/myrule.md Rule 2) --
            # disamakan dgn ActiveDeviceForm supaya API & dashboard konsisten.
            # PENTING: field2 ini (termasuk Realtime) SEBELUMNYA pernah hilang
            # dari sini -- akibatnya field itu MISSING TOTAL dari respons API
            # (bukan cuma salah nilai), dan React/JS menganggap `undefined`
            # sbg falsy, jadi kolom Realtime di Next.js SELALU tampil "Tidak"
            # apapun nilai sebenarnya di database. Kalau field ini hilang
            # LAGI di masa depan, itu gejalanya: cek dulu di sini.
            'LogStamp', 'OpLogStamp', 'PhotoStamp', 'TransTimes', 'TransInterval',
            'UpdateDB', 'ErrorDelay', 'Delay', 'Realtime', 'Encrypt',
        ]
        read_only_fields = ['State', 'LastActivity', 'PushVersion']

    def validate_SN(self, value):
        if self.instance is not None and self.instance.pk != value:
            raise serializers.ValidationError('Serial Number tidak bisa diubah setelah dibuat.')
        return value


class RegisteredDeviceSerializer(serializers.ModelSerializer):
    DeptName = serializers.CharField(source='DeptID.DeptName', read_only=True, default=None)

    class Meta:
        model = RegisteredDevice
        fields = [
            'id', 'SN', 'DeviceName', 'DeptID', 'DeptName', 'Function',
            'IPAddress', 'MAC', 'IPRouter',
        ]
        read_only_fields = ['id']


class EmployeeSerializer(serializers.ModelSerializer):
    DeptName = serializers.CharField(source='DeptID.DeptName', read_only=True, default=None)
    LastPool = serializers.SerializerMethodField()
    LastDevice = serializers.SerializerMethodField()

    class Meta:
        model = employee
        fields = [
            'id', 'PIN', 'EName', 'DeptID', 'DeptName', 'SN', 'Gender', 'Title',
            'Card', 'Privilege', 'Tele', 'Mobile', 'Password',
            # Aktivitas TERAKHIR (check-in/out/meal) -- diisi
            # iclock/tasks.py::_refresh_employee_last_seen SETIAP ada transaksi
            # ATTLOG baru (device fisik ATAU mobile). PENTING: field ini HANYA
            # terisi utk transaksi yang lewat PIPELINE PUSH SDK BARU -- data
            # historis dari SEBELUM refactor ini TIDAK di-backfill otomatis,
            # jadi employee yang belum pernah check-in LAGI sejak fitur ini
            # ada akan tetap tampil kosong (bukan bug, memang belum ada
            # transaksi baru utk employee itu).
            'UTime', 'LastVerify', 'LastPool', 'LastDevice',
        ]
        read_only_fields = ['id', 'UTime', 'LastVerify', 'LastPool', 'LastDevice']
        extra_kwargs = {
            'Password': {'write_only': True, 'required': False, 'allow_blank': True},
        }

    def get_LastPool(self, obj):
        return obj.LastPool()

    def get_LastDevice(self, obj):
        return obj.LastDevice()


class FingerprintTemplateSerializer(serializers.ModelSerializer):
    EmployeeName = serializers.CharField(source='UserID.EName', read_only=True, default=None)
    FingerIDDisplay = serializers.CharField(source='get_FingerID_display', read_only=True)

    class Meta:
        model = fptemp
        fields = [
            'id', 'UserID', 'EmployeeName', 'FingerID', 'FingerIDDisplay',
            'Valid', 'DelTag', 'SN', 'Template', 'UTime',
        ]
        read_only_fields = ['id', 'UTime']


class TransactionSerializer(serializers.ModelSerializer):
    EmployeeName = serializers.CharField(source='UserID.EName', read_only=True, default=None)
    StateDisplay = serializers.CharField(source='get_State_display', read_only=True)
    VerifyDisplay = serializers.CharField(source='get_Verify_display', read_only=True)

    class Meta:
        model = transaction
        fields = [
            'id', 'UserID', 'EmployeeName', 'TTime', 'State', 'StateDisplay',
            'Verify', 'VerifyDisplay', 'SN', 'WorkCode', 'Reserved',
        ]
        read_only_fields = ['id']


class OperationLogSerializer(serializers.ModelSerializer):
    OpName = serializers.CharField(source='op_name', read_only=True)

    class Meta:
        model = oplog
        fields = ['id', 'SN', 'admin', 'OP', 'OpName', 'OPTime', 'Object', 'Param1', 'Param2', 'Param3']
        read_only_fields = ['id']


class DeviceLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = devlog
        fields = ['id', 'SN', 'OP', 'Object', 'Cnt', 'ECnt', 'OpTime']
        read_only_fields = ['id']


class DeviceCommandSerializer(serializers.ModelSerializer):
    Username = serializers.CharField(source='User.username', read_only=True, default=None)

    class Meta:
        model = devcmds
        fields = [
            'id', 'SN', 'CmdContent', 'CmdCommitTime', 'CmdTransTime',
            'CmdOverTime', 'CmdReturn', 'User', 'Username',
        ]
        read_only_fields = ['id', 'User']


# ---------------------------------------------------------------------------
# Serializer utk AKSI (bukan CRUD model) -- device control, transfer finger,
# attendance recap. Field-nya disamakan dgn forms.py (dashboard web) supaya
# validasi konsisten.
# ---------------------------------------------------------------------------
class NetworkParamsActionSerializer(serializers.Serializer):
    new_ip = serializers.CharField(required=False, allow_blank=True, default='')
    new_netmask = serializers.CharField(required=False, allow_blank=True, default='')
    new_gateway = serializers.CharField(required=False, allow_blank=True, default='')

    def _validate_ip_field(self, value):
        if value:
            from django.core.validators import validate_ipv4_address
            validate_ipv4_address(value)
        return value

    def validate_new_ip(self, value):
        return self._validate_ip_field(value)

    def validate_new_netmask(self, value):
        return self._validate_ip_field(value)

    def validate_new_gateway(self, value):
        return self._validate_ip_field(value)


class GenericParamActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['get', 'set'])
    param_name = serializers.CharField()
    param_value = serializers.CharField(required=False, allow_blank=True, default='')
    do_refresh = serializers.BooleanField(required=False, default=True)


class BackupFingerprintActionSerializer(serializers.Serializer):
    pin_pattern = serializers.CharField(required=False, allow_blank=True, default='')


class TransferFingerActionSerializer(serializers.Serializer):
    pins = serializers.CharField(help_text='1+ PIN, pisah baris baru atau koma')
    from_device = serializers.PrimaryKeyRelatedField(queryset=iclock.objects.all())
    to_pool = serializers.PrimaryKeyRelatedField(queryset=department.objects.all())
    target_device = serializers.PrimaryKeyRelatedField(queryset=iclock.objects.all(), required=False, allow_null=True)

    def validate_pins(self, value):
        import re
        pins = [p.strip() for p in re.split(r'[,\n\r]+', value) if p.strip()]
        if not pins:
            raise serializers.ValidationError('Minimal 1 PIN harus diisi.')
        return pins


class TogglePrivilegeActionSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    current_privilege = serializers.IntegerField(required=False, default=0)


class DeviceUserIdActionSerializer(serializers.Serializer):
    user_id = serializers.CharField()


class AttendanceRecapQuerySerializer(serializers.Serializer):
    pin = serializers.CharField(required=False, allow_blank=True, default='')
    function = serializers.CharField(required=False, allow_blank=True, default='')
    pool = serializers.PrimaryKeyRelatedField(queryset=department.objects.all(), required=False, allow_null=True)
    device = serializers.PrimaryKeyRelatedField(queryset=iclock.objects.all(), required=False, allow_null=True)
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def validate(self, attrs):
        if attrs['date_from'] > attrs['date_to']:
            raise serializers.ValidationError('date_from tidak boleh lebih besar dari date_to.')
        return attrs