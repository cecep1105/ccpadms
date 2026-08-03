"""Business logic aplikasi ID Card -- dipakai bareng oleh dashboard Django & API (lihat pola yang sama di accounts/services.py)."""
from django.db import transaction as db_transaction

from .models import IDCard, IDCardLog


def change_card_status(actor, card_id, status, notes=''):
    """
    Ganti status 1 kartu -- SELALU lewat fungsi ini (BUKAN
    `card.status = ...; card.save()` langsung), supaya IDCardLog
    (riwayat) & IDCard.status (status TERKINI, cache dari log
    terbaru) TIDAK PERNAH tidak sinkron -- dibungkus 1 transaction
    (atomic) supaya KEDUANYA berhasil/gagal BARENG.
    """
    card = IDCard.objects.select_related('employee', 'holder', 'template').get(pk=card_id)
    with db_transaction.atomic():
        IDCardLog.objects.create(card=card, status=status, notes=notes, changed_by=actor if actor and actor.is_authenticated else None)
        card.status = status
        card.save(update_fields=['status', 'updated_at'])
    return card
