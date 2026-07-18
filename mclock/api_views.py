"""
API utk app 'mclock' (Mobile Pool, Mobile Pool Location, Pool Device
Function), dikonsumsi frontend Nuxt. Semua staff-only, pola sama dgn
iclock/api_views.py.
"""
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from api.permissions import IsStaffRole

from .models import MobilePool, MobilePoolLoc, PoolDeviceFunction
from .serializers import MobilePoolLocSerializer, MobilePoolSerializer, PoolDeviceFunctionSerializer


class BaseMclockViewSet(viewsets.ModelViewSet):
    """Base viewset: staff-only, dukung pencarian lewat ?q= (field dikonfigurasi per subclass)."""

    permission_classes = [IsAuthenticated, IsStaffRole]
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
