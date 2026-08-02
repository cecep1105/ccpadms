"""
Dropdown "Router" di halaman Mikrotik DHCP Lease & Firewall Filter --
pilihan diambil dari `iclock.RegisteredDevice.IPRouter` (field router
per-site yang SUDAH ADA di data registered device, BUKAN data baru),
dipasangkan dgn nama Dept/Pool device itu (lihat
`RegisteredDevice.DeptName()`) supaya admin gampang kenali router mana
yang mana ("Kantor Pusat - 10.0.0.1", bukan cuma angka IP polos).

Plus endpoint default router PER-HALAMAN (`NetmgmtRouterDefault`, model
key-value simpel) -- diedit lewat Django Admin, dipakai frontend sbg
fallback kalau user belum pilih router lain dari dropdown.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission, IsStaffRole
from iclock.models import RegisteredDevice

from .models import NetmgmtRouterDefault


class RouterChoicesView(APIView):
    """
    GET /api/v1/netmgmt/router-choices/ -- daftar (nama dept, IP router)
    UNIK dari RegisteredDevice.IPRouter (device dgn IPRouter kosong
    dilewati -- tidak berguna sbg pilihan router).
    """
    permission_classes = [IsAuthenticated & (IsStaffRole | HasFeaturePermission('iclock.can_view_fwfilter'))]

    def get(self, request):
        devices = (
            RegisteredDevice.objects
            .select_related('DeptID')
            .exclude(IPRouter__isnull=True)
            .exclude(IPRouter__exact='')
            .order_by('DeptID__DeptName', 'IPRouter')
        )
        seen = set()
        choices = []
        for device in devices:
            if device.IPRouter in seen:
                continue  # SATU router bisa dipakai BANYAK device di dept yg sama -- tampilkan sekali saja per IP unik
            seen.add(device.IPRouter)
            choices.append({'dept_name': device.DeptName(), 'ip_router': device.IPRouter})
        return Response({'results': choices}, status=status.HTTP_200_OK)


class RouterDefaultView(APIView):
    """GET /api/v1/netmgmt/router-default/?page=dhcp|fwfilter -- IP router default utk 1 halaman (diedit lewat Django Admin)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        page_key = request.query_params.get('page', '')
        if page_key not in dict(NetmgmtRouterDefault.PAGE_CHOICES):
            return Response({'error': f"Parameter 'page' wajib salah satu dari {list(dict(NetmgmtRouterDefault.PAGE_CHOICES))}."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            default = NetmgmtRouterDefault.objects.get(page_key=page_key)
            return Response({'router_ip': default.router_ip}, status=status.HTTP_200_OK)
        except NetmgmtRouterDefault.DoesNotExist:
            # Belum diset admin sama sekali -- BUKAN error, cukup balikin
            # kosong, frontend jatuh ke fallback env var lama (backward
            # compatible dgn setup yg SUDAH jalan sebelum fitur ini ada).
            return Response({'router_ip': None}, status=status.HTTP_200_OK)
