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
    has_employee_link = serializers.SerializerMethodField()

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
            'can_view_cloudflare', 'can_view_itinfra', 'has_employee_link',
        ]
        read_only_fields = [
            'id', 'username', 'auth_source', 'is_superuser', 'created_at', 'updated_at',
            'can_transfer_finger', 'can_view_attendance_recap',
            'can_view_attendance_recap_kantin', 'can_view_attendance_recap_driver',
            'can_view_dhcp_lease', 'can_view_fwfilter', 'can_view_netwatch',
            'can_view_ad_users', 'can_view_ad_locked_users', 'can_view_ad_dns', 'can_view_ad_groups',
            'can_view_zentyal_users', 'can_view_zentyal_groups',
            'can_view_cloudflare', 'can_view_itinfra', 'has_employee_link',
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

    def get_has_employee_link(self, obj):
        """
        True kalau akun ini TERKAIT ke 1 data Employee (accounts.User.EmpID,
        lihat catatan lengkap di accounts/models.py) -- dipakai frontend
        Next.js utk tahu apakah kartu/menu "My Attendance" perlu
        ditampilkan (lihat iclock/api_views.py::MyAttendanceCardAPIView) --
        SENGAJA cuma True/False (BUKAN PIN-nya sendiri) -- PIN tidak perlu
        bocor ke session/frontend, backend cukup lookup ULANG dari
        `request.user.EmpID` tiap request ke endpoint itu.
        """
        return obj.EmpID_id is not None


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


class UserUpdateByAdminSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    department = serializers.CharField(required=False, allow_blank=True, max_length=100)
    title = serializers.CharField(required=False, allow_blank=True, max_length=100)


class AdminResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=False, allow_blank=True, write_only=True)
