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
        ]
        read_only_fields = [
            'id', 'username', 'auth_source', 'is_superuser', 'created_at', 'updated_at',
            'can_transfer_finger', 'can_view_attendance_recap',
            'can_view_attendance_recap_kantin', 'can_view_attendance_recap_driver',
            'can_view_dhcp_lease', 'can_view_fwfilter', 'can_view_netwatch',
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
