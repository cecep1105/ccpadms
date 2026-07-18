from rest_framework import serializers

from .models import AttendanceLog, FaceProfile


class MobileLoginSerializer(serializers.Serializer):
    """POST /api/v1/mattendance/auth/login/ -- PIN Employee + password mobile (BUKAN username/password akun biasa)."""
    pin = serializers.CharField()
    mobile_password = serializers.CharField(write_only=True)


class MobileChangePasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)


class CheckinSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    check_type = serializers.ChoiceField(choices=[AttendanceLog.CheckType.IN, AttendanceLog.CheckType.OUT])
    face_image = serializers.CharField()


class CheckinMealSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    qr_content = serializers.CharField()


class FaceEnrollSerializer(serializers.Serializer):
    face_image = serializers.CharField()


class AttendanceLogSerializer(serializers.ModelSerializer):
    """Dipakai riwayat milik sendiri (/history/) MAUPUN daftar admin (/admin/logs/)."""
    username = serializers.CharField(source='user.username', read_only=True)
    check_type_display = serializers.CharField(source='get_check_type_display', read_only=True)
    pool_id = serializers.CharField(source='PoolID.PoolID', read_only=True, default=None)
    pool_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceLog
        fields = [
            'id', 'username', 'timestamp', 'check_type', 'check_type_display',
            'pool_id', 'pool_name', 'location_verified', 'face_verified',
            'face_distance', 'qr_content', 'Function',
        ]
        read_only_fields = fields

    def get_pool_name(self, obj):
        return obj.PoolID.PoolName if obj.PoolID else None


class FaceProfileAdminSerializer(serializers.ModelSerializer):
    """Admin-only -- daftar Face Profile, tampilkan PIN & nama Employee (bukan username akun)."""
    pin = serializers.CharField(source='employee.PIN', read_only=True)
    employee_name = serializers.CharField(source='employee.EName', read_only=True)

    class Meta:
        model = FaceProfile
        fields = ['id', 'pin', 'employee_name', 'is_locked', 'enrolled_at', 'updated_at']
        read_only_fields = ['id', 'pin', 'employee_name', 'enrolled_at', 'updated_at']
