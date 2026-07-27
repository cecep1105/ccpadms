from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    can_transfer_finger = serializers.SerializerMethodField()
    can_view_attendance_recap = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone_number', 'department', 'title', 'auth_source',
            'is_active', 'is_staff', 'is_superuser', 'must_change_password',
            'created_at', 'updated_at',
            # Izin fitur granular utk user NON-staff (lihat
            # iclock/models.py::FeaturePermission & dashboard "Kelola Izin
            # User") -- staff/superuser otomatis True utk keduanya (efektif
            # selalu punya akses), dipakai frontend Next.js utk tahu kartu
            # mana yang perlu ditampilkan di halaman non-staff.
            'can_transfer_finger', 'can_view_attendance_recap',
        ]
        read_only_fields = [
            'id', 'username', 'auth_source', 'is_superuser', 'created_at', 'updated_at',
            'can_transfer_finger', 'can_view_attendance_recap',
        ]

    def get_can_transfer_finger(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_transfer_finger'))

    def get_can_view_attendance_recap(self, obj):
        return bool(obj.is_staff or obj.is_superuser or obj.has_perm('iclock.can_view_attendance_recap'))


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
