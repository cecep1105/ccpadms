from rest_framework import serializers

from .models import IDCard, IDCardHolder, IDCardLog, IDCardTemplate


class IDCardTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = IDCardTemplate
        fields = ['id', 'card_type', 'name', 'background_image', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class IDCardHolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = IDCardHolder
        fields = [
            'id', 'card_type', 'full_name', 'id_number', 'company', 'purpose',
            'photo', 'valid_from', 'valid_until', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class IDCardLogSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    changed_by_username = serializers.CharField(source='changed_by.username', read_only=True, default=None)

    class Meta:
        model = IDCardLog
        fields = ['id', 'status', 'status_label', 'notes', 'changed_by_username', 'changed_at']
        read_only_fields = fields


class IDCardListSerializer(serializers.ModelSerializer):
    """Dipakai LIST (ringkas) -- TANPA riwayat log (lihat IDCardDetailSerializer utk itu)."""
    card_type_label = serializers.CharField(source='get_card_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True)
    holder_name = serializers.CharField(read_only=True)
    holder_identifier = serializers.CharField(read_only=True)

    class Meta:
        model = IDCard
        fields = [
            'id', 'card_type', 'card_type_label', 'holder_name', 'holder_identifier',
            'template_name', 'photo_source', 'card_image', 'status', 'status_label', 'generated_at',
        ]
        read_only_fields = fields


class IDCardDetailSerializer(IDCardListSerializer):
    """LENGKAP -- termasuk riwayat log & foto sumber (utk generate-ulang)."""
    logs = IDCardLogSerializer(many=True, read_only=True)

    class Meta(IDCardListSerializer.Meta):
        fields = IDCardListSerializer.Meta.fields + ['photo', 'template', 'employee_id', 'holder_id', 'logs']
        read_only_fields = fields
