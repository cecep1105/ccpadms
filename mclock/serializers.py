from rest_framework import serializers

from .models import MobilePool, MobilePoolLoc, PoolDeviceFunction


class MobilePoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = MobilePool
        fields = ['PoolID', 'PoolCode', 'PoolName', 'Latitude', 'Longitude', 'Radius', 'SyncedAt']
        read_only_fields = ['SyncedAt']

    def validate_PoolID(self, value):
        # Cek duplikat HANYA saat CREATE -- saat update, instance sendiri
        # (dgn PoolID yg sama) tidak boleh dianggap "bentrok".
        qs = MobilePool.objects.filter(PoolID=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"PoolID '{value}' sudah ada.")
        return value


class MobilePoolLocSerializer(serializers.ModelSerializer):
    class Meta:
        model = MobilePoolLoc
        fields = ['id', 'PoolID', 'Urut', 'Latitude', 'Longitude', 'SyncedAt']
        read_only_fields = ['id', 'SyncedAt']

    def validate(self, attrs):
        pool_id = attrs.get('PoolID', getattr(self.instance, 'PoolID', None))
        urut = attrs.get('Urut', getattr(self.instance, 'Urut', None))
        qs = MobilePoolLoc.objects.filter(PoolID=pool_id, Urut=urut)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"Titik dengan PoolID '{pool_id}' & Urut '{urut}' sudah ada.")
        return attrs


class PoolDeviceFunctionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoolDeviceFunction
        fields = ['id', 'PoolID', 'function_type', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_PoolID(self, value):
        qs = PoolDeviceFunction.objects.filter(PoolID=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"PoolID '{value}' sudah ada mapping-nya.")
        return value
