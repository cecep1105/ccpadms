"""
API aplikasi ID Card -- Generate/lihat/ubah-status kartu (SEMUA jenis)
& daftar/tambah data Visitor-BHL TERSEDIA utk portal (izin granular
can_view_idcard, staf tetap selalu lolos apa pun izinnya) -- TAPI
kelola TEMPLATE (bikin/edit background) & ubah/hapus data Visitor/BHL
TETAP staff-only (keputusan cakupan: portal generate & pakai data yg
SUDAH ada, TIDAK atur konfigurasi/hapus data punya orang lain -- lihat
IdCardPortalWritePermission di bawah). Business logic (generate kartu,
cari foto, ubah status) dijaga TIPIS di sini, dilempar ke
idcard/services.py, photo_utils.py, card_generator.py.
"""
import base64
import binascii

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission, IsStaffRole
from iclock.models import employee

from . import card_generator, photo_utils, services
from .models import CARD_TYPE_CHOICES, EMPLOYEE_LINKED_CARD_TYPES, IDCard, IDCardHolder, IDCardTemplate
from .serializers import (
    IDCardDetailSerializer,
    IDCardHolderSerializer,
    IDCardListSerializer,
    IDCardTemplateSerializer,
)

User = get_user_model()


def _decode_data_uri(data_uri):
    """`data:image/jpeg;base64,...` -> bytes mentah -- dipakai foto dari webcam (canvas.toDataURL()) MAUPUN foto yang dipilih dari hasil pencarian FTP (SAMA-SAMA data URI, lihat photo_utils.py)."""
    if ',' not in data_uri:
        raise ValueError('Format data foto tidak valid (bukan data URI).')
    _header, encoded = data_uri.split(',', 1)
    try:
        return base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f'Gagal decode data foto: {exc}') from exc


class IdCardPortalWritePermission(BasePermission):
    """
    Staff/superuser SELALU lolos APA PUN method-nya. User portal
    berizin can_view_idcard CUMA lolos utk GET -- dipakai
    IDCardTemplateListView (portal BOLEH lihat daftar template buat
    dropdown generate, TIDAK BOLEH bikin template baru) &
    IDCardHolderDetailView (portal BOLEH lihat detail 1 holder, TIDAK
    BOLEH ubah/hapus data punya orang lain sembarangan -- beda dari
    IDCardHolderListView yg POST-nya SENGAJA diizinkan portal, krn
    nambah data holder BARU memang bagian dari alur kerja mereka
    sehari-hari).
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff or user.is_superuser:
            return True
        if not user.has_perm('iclock.can_view_idcard'):
            return False
        return request.method == 'GET'


class IDCardTemplateListView(APIView):
    """GET (list, filter ?card_type=) -- TERSEDIA portal (lihat IdCardPortalWritePermission). POST (tambah) -- STAFF-ONLY."""
    permission_classes = [IsAuthenticated, IdCardPortalWritePermission]

    def get(self, request):
        qs = IDCardTemplate.objects.all()
        card_type = request.query_params.get('card_type')
        if card_type:
            qs = qs.filter(card_type=card_type)
        return Response(IDCardTemplateSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = IDCardTemplateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class IDCardTemplateDetailView(APIView):
    """PATCH (ubah, mis. toggle is_active) / DELETE -- STAFF-ONLY (kelola template TIDAK termasuk cakupan portal, beda dari IDCardTemplateListView.get() yg boleh dibaca portal)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def patch(self, request, pk=None):
        template = get_object_or_404(IDCardTemplate, pk=pk)
        serializer = IDCardTemplateSerializer(template, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk=None):
        template = get_object_or_404(IDCardTemplate, pk=pk)
        if template.id_cards.exists():
            return Response(
                {'error': 'Template ini sudah dipakai utk generate kartu -- tidak bisa dihapus (nonaktifkan saja lewat is_active).'},
                status=status.HTTP_409_CONFLICT,
            )
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IDCardHolderListView(APIView):
    """
    GET (list, filter ?card_type=visitor|bhl&_q=) / POST (tambah) -- data manual Visitor/BHL.
    TERSEDIA portal (can_view_idcard) utk KEDUA method -- nambah data
    holder baru MEMANG bagian alur kerja portal sehari-hari.
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_idcard')]

    def get(self, request):
        qs = IDCardHolder.objects.all()
        card_type = request.query_params.get('card_type')
        if card_type:
            qs = qs.filter(card_type=card_type)
        search = request.query_params.get('_q', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(full_name__icontains=search) | Q(id_number__icontains=search) | Q(company__icontains=search))

        page = int(request.query_params.get('_page', 1) or 1)
        page_size = int(request.query_params.get('_limit', 20) or 20)
        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)
        return Response({
            'count': paginator.count, 'page': page_obj.number,
            'results': IDCardHolderSerializer(page_obj.object_list, many=True, context={'request': request}).data,
        })

    def post(self, request):
        serializer = IDCardHolderSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class IDCardHolderDetailView(APIView):
    """GET (detail, TERSEDIA portal) / PATCH (ubah) / DELETE -- 2 terakhir STAFF-ONLY."""
    permission_classes = [IsAuthenticated, IdCardPortalWritePermission]

    def get(self, request, pk=None):
        holder = get_object_or_404(IDCardHolder, pk=pk)
        return Response(IDCardHolderSerializer(holder, context={'request': request}).data)

    def patch(self, request, pk=None):
        holder = get_object_or_404(IDCardHolder, pk=pk)
        serializer = IDCardHolderSerializer(holder, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk=None):
        holder = get_object_or_404(IDCardHolder, pk=pk)
        if holder.id_cards.exists():
            return Response({'error': 'Holder ini sudah punya kartu ID -- tidak bisa dihapus.'}, status=status.HTTP_409_CONFLICT)
        holder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IDCardPhotoSearchView(APIView):
    """
    GET /api/v1/idcard/photo-search/?pin=&card_type=karyawan|driver
    Cari kandidat foto dari FTP/DB eksternal (idcard/photo_utils.py) --
    HANYA relevan utk 'karyawan'/'driver' (Visitor/BHL TIDAK ada sumber
    ini, foto mereka SELALU shoot/upload manual).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_idcard')]

    def get(self, request):
        pin = (request.query_params.get('pin') or '').lstrip('0')
        card_type = request.query_params.get('card_type', 'karyawan')
        if not pin:
            return Response({'error': "Parameter 'pin' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if card_type not in EMPLOYEE_LINKED_CARD_TYPES:
            return Response({'error': f"Pencarian foto FTP cuma relevan utk jenis kartu {sorted(EMPLOYEE_LINKED_CARD_TYPES)}."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            results = photo_utils.fetch_photos_for_card_type(pin, card_type)
        except photo_utils.PhotoFetchError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({'results': results})


class IDCardGenerateView(APIView):
    """
    POST /api/v1/idcard/cards/generate/
    Body: {
      "card_type": "karyawan"|"driver"|"visitor"|"bhl",
      "template_id": 1,
      "pin": "89100" (WAJIB utk karyawan/driver),
      "holder_id": 5 (WAJIB utk visitor/bhl),
      "photo_source": "ftp"|"shoot"|"upload",
      "photo_data": "data:image/jpeg;base64,..." (SELALU data URI, apa pun sumbernya),
      "extra_text": "Staff IT" (opsional)
    }
    Generate 1 IDCard baru: susun gambar (card_generator.py), simpan
    foto sumber + hasil composite, status awal SELALU 'belum_cetak'.
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_idcard')]

    def post(self, request):
        card_type = request.data.get('card_type')
        if card_type not in dict(CARD_TYPE_CHOICES):
            return Response({'error': "'card_type' tidak valid."}, status=status.HTTP_400_BAD_REQUEST)

        template_id = request.data.get('template_id')
        template = get_object_or_404(IDCardTemplate, pk=template_id)

        photo_source = request.data.get('photo_source')
        if photo_source not in dict(IDCard._meta.get_field('photo_source').choices):
            return Response({'error': "'photo_source' tidak valid."}, status=status.HTTP_400_BAD_REQUEST)

        photo_data = request.data.get('photo_data')
        if not photo_data:
            return Response({'error': "'photo_data' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            photo_bytes = _decode_data_uri(photo_data)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        emp = None
        holder = None

        if card_type in EMPLOYEE_LINKED_CARD_TYPES:
            pin = (request.data.get('pin') or '').strip()
            if not pin:
                return Response({'error': "'pin' wajib diisi utk kartu jenis ini."}, status=status.HTTP_400_BAD_REQUEST)
            emp = employee.objects.filter(PIN=pin).first()
            if not emp:
                return Response({'error': f"Employee dengan PIN '{pin}' tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
            name = emp.EName or ''
            identifier = emp.PIN
        else:
            holder_id = request.data.get('holder_id')
            if not holder_id:
                return Response({'error': "'holder_id' wajib diisi utk kartu jenis ini."}, status=status.HTTP_400_BAD_REQUEST)
            holder = get_object_or_404(IDCardHolder, pk=holder_id)
            name = holder.full_name
            identifier = holder.id_number.lstrip('0')

        extra_text = request.data.get('extra_text', '')

        try:
            with open(template.background_image.path, 'rb') as f:
                background_bytes = f.read()
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal membaca file template: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            card_image_bytes = card_generator.generate_card_image(background_bytes, photo_bytes, name, identifier, extra_text)
        except Exception as exc:  # noqa: BLE001 -- Pillow bisa lempar berbagai jenis exception (format foto tidak dikenal, dst)
            return Response({'error': f'Gagal menyusun gambar kartu: {exc}'}, status=status.HTTP_400_BAD_REQUEST)

        card = IDCard(
            card_type=card_type, employee=emp, holder=holder, template=template,
            photo_source=photo_source, generated_by=request.user,
        )
        identifier_safe = (identifier or 'x').replace('/', '_')
        card.photo.save(f'{identifier_safe}_source.jpg', ContentFile(photo_bytes), save=False)
        card.card_image.save(f'{identifier_safe}_card.png', ContentFile(card_image_bytes), save=False)
        card.full_clean(exclude=['photo', 'card_image'])
        card.save()

        # Log AWAL ('belum_cetak') -- SAMA nilai dgn default IDCard.status,
        # TAPI TETAP dicatat eksplisit di sini supaya riwayat log-nya
        # LENGKAP dari titik nol, bukan "muncul" pertama kali baru pas
        # status BERUBAH.
        services.change_card_status(request.user, card.id, 'belum_cetak', notes='Kartu baru digenerate.')
        card.refresh_from_db()

        return Response(IDCardDetailSerializer(card, context={'request': request}).data, status=status.HTTP_201_CREATED)


class IDCardListView(APIView):
    """GET -- daftar kartu, filter ?card_type=&status=&_q= (cari nama/PIN/no. identitas)."""
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_idcard')]

    def get(self, request):
        qs = IDCard.objects.select_related('employee', 'holder', 'template').all()
        card_type = request.query_params.get('card_type')
        if card_type:
            qs = qs.filter(card_type=card_type)
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        search = request.query_params.get('_q', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(employee__EName__icontains=search) | Q(employee__PIN__icontains=search)
                | Q(holder__full_name__icontains=search) | Q(holder__id_number__icontains=search)
            )

        page = int(request.query_params.get('_page', 1) or 1)
        page_size = int(request.query_params.get('_limit', 20) or 20)
        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)
        return Response({
            'count': paginator.count, 'page': page_obj.number,
            'results': IDCardListSerializer(page_obj.object_list, many=True, context={'request': request}).data,
        })


class IDCardDetailView(APIView):
    """
    GET -- 1 kartu LENGKAP termasuk riwayat log (TERSEDIA portal).
    DELETE -- hapus kartu PERMANEN (STAFF-ONLY, lihat IdCardPortalWritePermission
    -- SAMA pola dgn IDCardHolderDetailView: portal boleh lihat, TIDAK
    boleh hapus data). Menghapus row DB SEKALIGUS file fisik (`photo` &
    `card_image`) dari storage -- Django TIDAK otomatis membersihkan
    file saat model instance dihapus (gotcha yg cukup terkenal), jadi
    file HARUS dihapus EKSPLISIT lewat FieldFile.delete(save=False)
    SEBELUM baris DB-nya dihapus, KALAU TIDAK file yatim akan
    menumpuk terus di server (media/idcard/...) meski row-nya sudah
    tidak ada lagi.
    """
    permission_classes = [IsAuthenticated, IdCardPortalWritePermission]

    def get(self, request, pk=None):
        card = get_object_or_404(IDCard.objects.select_related('employee', 'holder', 'template').prefetch_related('logs__changed_by'), pk=pk)
        return Response(IDCardDetailSerializer(card, context={'request': request}).data)

    def delete(self, request, pk=None):
        card = get_object_or_404(IDCard, pk=pk)
        # save=False -- JANGAN sampai FieldFile.delete() ikut trigger
        # card.save() (yg butuh full_clean() gara2 model.clean() custom
        # kita), row-nya TOH akan dihapus SEKALIAN sesudah ini.
        if card.photo:
            card.photo.delete(save=False)
        if card.card_image:
            card.card_image.delete(save=False)
        card.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IDCardStatusChangeView(APIView):
    """POST -- ubah status kartu (belum_cetak/sudah_cetak/hilang/cetak_ulang), SELALU lewat services.change_card_status (log + status sinkron)."""
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_idcard')]

    def post(self, request, pk=None):
        new_status = request.data.get('status')
        if new_status not in dict(IDCard._meta.get_field('status').choices):
            return Response({'error': "'status' tidak valid."}, status=status.HTTP_400_BAD_REQUEST)
        notes = request.data.get('notes', '')
        card = services.change_card_status(request.user, pk, new_status, notes=notes)
        return Response(IDCardDetailSerializer(card, context={'request': request}).data)
