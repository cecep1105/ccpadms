from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    can_transfer_finger = serializers.SerializerMethodField()
    can_view_attendance_recap = serializers.SerializerMethodField()
    can_view_attendance_recap_kantin = serializers.SerializerMethodField()
    can_view_attendance_recap_driver = serializers.SerializerMethodField()
    can_view_dhcp_lease = serializers.SerializerMethodField()
    can_view_fwfilter = serializers.SerializerMethodField()
    can_view_netwatch = serializers.SerializerMethodField()
    can_view_ad_users = serializers.SerializerMethodField()
    can_view_ad_locked_users = serializers.SerializerMethodField()
    can_view_ad_dns = serializers.SerializerMethodField()
    can_view_ad_groups = serializers.SerializerMethodField()
    can_view_zentyal_users = serializers.SerializerMethodField()
    can_view_zentyal_groups = serializers.SerializerMethodField()
    can_view_cloudflare = serializers.SerializerMethodField()
    can_view_itinfra = serializers.SerializerMethodField()
    can_view_idcard = serializers.SerializerMethodField()
    can_view_active_device = serializers.SerializerMethodField()
    has_employee_link = serializers.SerializerMethodField()
    emp_pin = serializers.SerializerMethodField()
    emp_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone_number', 'department', 'title', 'auth_source',
            'is_active', 'is_staff', 'is_superuser', 'must_change_password',
            'created_at', 'updated_at',
            # Izin fitur granular utk user NON-staff (lihat
            # iclock/models.py::FeaturePermission & dashboard "Kelola Izin
            # User") -- staff/superuser otomatis True utk semuanya (efektif
            # selalu punya akses), dipakai frontend Next.js utk tahu kartu/
            # tab mana yang perlu ditampilkan (mis. 3 tab Rekap Absensi:
            # All/Kantin/Driver, lihat iclock/api_views.py::AttendanceRecapAPIView;
            # DHCP Lease/Firewall Filter/Netwatch di portal, lihat
            # netmgmt/portal_views.py).
            'can_transfer_finger', 'can_view_attendance_recap',
            'can_view_attendance_recap_kantin', 'can_view_attendance_recap_driver',
            'can_view_dhcp_lease', 'can_view_fwfilter', 'can_view_netwatch',
            'can_view_ad_users', 'can_view_ad_locked_users', 'can_view_ad_dns', 'can_view_ad_groups',
            'can_view_zentyal_users', 'can_view_zentyal_groups',
            'can_view_cloudflare', 'can_view_itinfra', 'can_view_idcard', 'can_view_active_device', 'has_employee_link', 'emp_pin', 'emp_name',
        ]
        read_only_fields = [
            'id', 'username', 'auth_source', 'is_superuser', 'created_at', 'updated_at',
            'can_transfer_finger', 'can_view_attendance_recap',
            'can_view_attendance_recap_kantin', 'can_view_attendance_recap_driver',
            'can_view_dhcp_lease', 'can_view_fwfilter', 'can_view_netwatch',
            'can_view_ad_users', 'can_view_ad_locked_users', 'can_view_ad_dns', 'can_view_ad_groups',
            'can_view_zentyal_users', 'can_view_zentyal_groups',
            'can_view_cloudflare', 'can_view_itinfra', 'can_view_idcard', 'can_view_active_device', 'has_employee_link', 'emp_pin', 'emp_name',
        ]

    def get_can_transfer_finger(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_transfer_finger'))

    def get_can_view_attendance_recap(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_attendance_recap'))

    def get_can_view_attendance_recap_kantin(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_attendance_recap_kantin'))

    def get_can_view_attendance_recap_driver(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_attendance_recap_driver'))

    def get_can_view_dhcp_lease(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_dhcp_lease'))

    def get_can_view_fwfilter(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_fwfilter'))

    def get_can_view_netwatch(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_netwatch'))

    def get_can_view_ad_users(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_ad_users'))

    def get_can_view_ad_locked_users(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_ad_locked_users'))

    def get_can_view_ad_dns(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_ad_dns'))

    def get_can_view_ad_groups(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_ad_groups'))

    def get_can_view_zentyal_users(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_zentyal_users'))

    def get_can_view_zentyal_groups(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_zentyal_groups'))

    def get_can_view_cloudflare(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_cloudflare'))

    def get_can_view_itinfra(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_itinfra'))

    def get_can_view_idcard(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_idcard'))

    def get_can_view_active_device(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_active_device'))

    def get_has_employee_link(self, obj):
        """
        True kalau akun ini TERKAIT ke 1 data Employee (accounts.User.EmpID,
        lihat catatan lengkap di accounts/models.py) -- dipakai frontend
        Next.js utk tahu apakah kartu/menu "My Attendance" perlu
        ditampilkan (lihat iclock/api_views.py::MyAttendanceCardAPIView).
        """
        return obj.EmpID_id is not None

    def get_emp_pin(self, obj):
        """
        PIN Employee yang TERKAIT (kalau ada) -- BEDA dari has_employee_link
        di atas, field INI memang MENAMPILKAN nilai PIN-nya (bukan cuma
        True/False) -- dipakai isi ULANG form "Kelola User" di halaman
        admin Next.js (/users) supaya admin lihat PIN yang SUDAH terkait
        saat edit, SAMA pola dgn `current_employee_label` versi Django
        (dashboard/views.py::user_edit). AMAN krn CUMA admin/staff yang
        akses endpoint list/detail users (UserViewSet permission_classes
        = IsStaffRole) -- BEDA konteks dari sesi user sendiri.
        """
        return obj.EmpID.PIN if obj.EmpID_id else None

    def get_emp_name(self, obj):
        return obj.EmpID.EName if obj.EmpID_id else None


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class ProfileUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    department = serializers.CharField(required=False, allow_blank=True, max_length=100)
    title = serializers.CharField(required=False, allow_blank=True, max_length=100)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)


class CreateLocalUserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    password = serializers.CharField(write_only=True)
    is_staff = serializers.BooleanField(required=False, default=False)
    # PIN karyawan (STRING, BUKAN id Employee) -- diresolve jadi instance
    # Employee di validate_emp_id() di bawah, SAMA pola dgn Django Form
    # (accounts/forms.py::clean_emp_id) -- 1 PIN bisa terdaftar di
    # beberapa device (row Employee terpisah per kombinasi), jadi ambil
    # match PERTAMA (.first(), bukan .get() yg bisa crash
    # MultipleObjectsReturned), cukup baik utk keperluan link akun.
    emp_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, write_only=True)

    def validate_emp_id(self, pin):
        pin = (pin or '').strip()
        if not pin:
            return None
        from iclock.models import employee
        emp = employee.objects.filter(PIN=pin).first()
        if not emp:
            raise serializers.ValidationError(f"Employee dengan PIN '{pin}' tidak ditemukan.")
        return emp


class UserUpdateByAdminSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    department = serializers.CharField(required=False, allow_blank=True, max_length=100)
    title = serializers.CharField(required=False, allow_blank=True, max_length=100)
    # SAMA persis pola dgn CreateLocalUserSerializer.emp_id di atas --
    # `source='EmpID'` (HURUF BESAR) krn services.update_user_by_admin()
    # nge-filter kwarg lewat whitelist berisi 'EmpID' (nama field MODEL
    # asli), BUKAN 'emp_id' kecil spt di create_local_user() (asimetri
    # INI SUDAH ADA sebelumnya di Django Form jg, bukan ketidaksengajaan
    # baru -- lihat dashboard/views.py::user_edit,
    # `cleaned['EmpID'] = cleaned.pop('emp_id')`).
    emp_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, source='EmpID', write_only=True)

    def validate_emp_id(self, pin):
        pin = (pin or '').strip()
        if not pin:
            return None
        from iclock.models import employee
        emp = employee.objects.filter(PIN=pin).first()
        if not emp:
            raise serializers.ValidationError(f"Employee dengan PIN '{pin}' tidak ditemukan.")
        return emp


class AdminResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=False, allow_blank=True, write_only=True)
