"""
API utk app 'mclock' (Mobile Pool, Mobile Pool Location, Pool Device
Function), dikonsumsi frontend Nuxt. Semua staff-only, pola sama dgn
iclock/api_views.py.
"""
from django.db import transaction as db_transaction
from django.db.models import Q
from rest_framework import filters, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole

from .models import MobilePool, MobilePoolLoc, PoolDeviceFunction
from .serializers import MobilePoolLocSerializer, MobilePoolSerializer, PoolDeviceFunctionSerializer


class BaseMclockViewSet(viewsets.ModelViewSet):
    """
    Base viewset: staff-only, dukung pencarian lewat ?q= DAN sorting lewat
    ?ordering=field (atau ?ordering=-field utk descending) -- lihat
    iclock/api_views.py::BaseIclockViewSet, pola identik.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = '__all__'
    search_fields = []

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('q')
        if search and self.search_fields:
            q_obj = Q()
            for field in self.search_fields:
                q_obj |= Q(**{f'{field}__icontains': search})
            qs = qs.filter(q_obj)
        return qs


class MobilePoolViewSet(BaseMclockViewSet):
    """
    CRUD Mobile Pool. PENTING: tabel ini disinkronkan dari MSSQL eksternal
    (management command `sync_mobile_pool`, mirror penuh) -- perubahan
    lewat API ini HANYA cocok utk TESTING (akan tertimpa/hilang begitu
    sync berikutnya jalan), sama seperti tombol tambah/hapus di dashboard
    web. `Radius` sekadar informasi, geofence check-in/out sekarang pakai
    Mobile Pool Location (polygon), bukan radius ini.
    """
    queryset = MobilePool.objects.all()
    serializer_class = MobilePoolSerializer
    search_fields = ['PoolID', 'PoolCode', 'PoolName']


class MobilePoolLocViewSet(BaseMclockViewSet):
    """
    CRUD titik polygon Mobile Pool Location -- SAMA seperti Mobile Pool di
    atas, data ini disinkronkan dari MSSQL (`sync_mobile_pool_loc`),
    perubahan lewat API cuma cocok utk testing. 1 PoolID butuh MINIMAL 3
    titik (Urut berbeda-beda) supaya jadi polygon valid dipakai geofence.
    """
    queryset = MobilePoolLoc.objects.all()
    serializer_class = MobilePoolLocSerializer
    search_fields = ['PoolID']


class MobilePoolLocBulkSaveAPIView(APIView):
    """
    POST /api/v1/mclock/mobile-pool-loc/bulk-save/<pool_id>/
    body: {"points": [{"lat": ..., "lng": ...}, ...]}

    Endpoint KHUSUS utk fitur "Gambar Polygon di Peta" (frontend Nuxt) --
    BEDA dari MobilePoolLocViewSet biasa (CRUD 1 titik per request): endpoint
    ini MENGGANTI SELURUH titik lama milik PoolID ini sekaligus, ATOMIK
    (delete semua + insert ulang dalam 1 transaksi DB) -- supaya hapus/geser
    titik di peta tersimpan benar tanpa risiko state gagal-sebagian yang
    bisa terjadi kalau frontend melakukan banyak request CRUD terpisah
    (mis. network putus di tengah, sebagian titik lama sudah kehapus tapi
    titik baru belum semua ke-insert). Padanan persis
    `iclock/views.py::mobile_pool_loc_draw_save` (dashboard Django).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request, pool_id):
        pool_id = (pool_id or '').strip()
        if not pool_id:
            return Response({'detail': "PoolID wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        points = request.data.get('points', [])
        if not isinstance(points, list) or len(points) < 3:
            return Response(
                {'detail': f"Minimal 3 titik utk jadi polygon valid (sekarang {len(points) if isinstance(points, list) else 0})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cleaned_points = [(float(p['lat']), float(p['lng'])) for p in points]
        except (KeyError, TypeError, ValueError):
            return Response(
                {'detail': "Format titik tidak valid -- tiap titik butuh 'lat' & 'lng' numerik."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with db_transaction.atomic():
            MobilePoolLoc.objects.filter(PoolID=pool_id).delete()
            MobilePoolLoc.objects.bulk_create([
                MobilePoolLoc(PoolID=pool_id, Urut=i + 1, Latitude=str(lat), Longitude=str(lng))
                for i, (lat, lng) in enumerate(cleaned_points)
            ])

        return Response({
            'detail': f"Polygon PoolID '{pool_id}' tersimpan ({len(cleaned_points)} titik).",
            'count': len(cleaned_points),
        })


class PoolDeviceFunctionViewSet(BaseMclockViewSet):
    """
    CRUD mapping PoolID -> KANTIN/Bukan KANTIN. BEDA dari 2 viewset di
    atas -- tabel ini TIDAK disinkronkan dari mana pun, dikelola manual
    sepenuhnya (ini cara UTAMA mengelolanya, bukan cuma testing). Dipakai
    `mattendance` menentukan kode fungsi (settings.DEVICEFUNCTION) tiap
    check-in/out/meal.
    """
    queryset = PoolDeviceFunction.objects.all()
    serializer_class = PoolDeviceFunctionSerializer
    search_fields = ['PoolID']