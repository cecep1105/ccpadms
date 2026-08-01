"""
Endpoint Mikrotik KHUSUS PORTAL (non-staff) -- DHCP Lease (lihat saja),
Firewall Filter (lihat + Grant Access), Netwatch (lihat + Add/Edit host).

⚠️ SENGAJA BUKAN proxy generik (netmgmt/routeros_api_view.py::RouterOSCommandView)
yang dipakai halaman STAFF -- proxy itu bisa jalankan HAMPIR SEMUA
command RouterOS (baca/tulis, resource APA PUN) lewat parameter URL
bebas, staff-only KARENA ITU. Kalau endpoint GENERIK itu dibuka ke user
non-staff (walau cuma py izin granular utk 1 fitur, mis. DHCP Lease
saja), mereka BISA PIVOT ke command/resource LAIN yang TIDAK seharusnya
mereka akses (mis. firewall NAT, reboot system, dst) cuma dgn ganti
parameter URL -- privilege escalation. Endpoint di modul INI masing2
DI-HARDCODE ke 1 resource RouterOS SPESIFIK & 1 aksi TERBATAS (kalau
ada aksi tulis sama sekali) -- TIDAK menerima command/resource bebas
dari client sama sekali.

Router yang dipakai TIAP fitur:
- DHCP Lease/Firewall Filter: NetmgmtRouterDefault (page_key='dhcp'/'fwfilter',
  diset admin lewat Django Admin) -> fallback settings.MIKROTIK_DHCP_ROUTER_IP/
  MIKROTIK_FWFILTER_ROUTER_IP kalau belum diset -- SAMA mekanisme dgn
  halaman STAFF (Next.js, resolveRouterIp()), TAPI diresolve LANGSUNG di
  backend di sini (portal TIDAK py dropdown pilih router, beda dari
  staff yang py RouterSelector).
- Netwatch: settings.MIKROTIK_NETWATCH_ROUTER_IP (SAMA persis dgn yang
  dipakai webhook/summary Netwatch staff, cuma 1 router netwatch, tidak
  py konsep "default per-halaman" spt DHCP/FwFilter).
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission

from .list_utils import paginate_sort_filter, parse_list_params
from .models import NetmgmtRouterDefault
from .routeros_api_view import MikrotikConnectionError, get_routeros_connection


def _resolve_router_ip(page_key: str, env_fallback: str) -> str:
    """NetmgmtRouterDefault (Django Admin) -> fallback env var -- SAMA prioritas dgn resolveRouterIp() versi Next.js (staff)."""
    default = NetmgmtRouterDefault.objects.filter(page_key=page_key).first()
    return default.router_ip if default else env_fallback


class PortalDhcpLeaseListView(APIView):
    """GET /api/v1/netmgmt/portal/dhcp-lease/?_page=&_limit=&_sort_by=&_order=&_q= -- LIHAT SAJA (read-only), resource DI-HARDCODE ke /ip/dhcp-server/lease."""
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_dhcp_lease')]

    def get(self, request):
        host = _resolve_router_ip('dhcp', settings.MIKROTIK_DHCP_ROUTER_IP)
        try:
            connection, api = get_routeros_connection(host)
        except MikrotikConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            rows = api.get_resource('/ip/dhcp-server/lease').get()
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal membaca dari router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            connection.disconnect()

        params = parse_list_params(request)
        if not params['search_fields']:
            params['search_fields'] = ['address', 'mac-address', 'host-name']
        payload = paginate_sort_filter(rows, **params)
        return Response(payload, status=status.HTTP_200_OK)


class PortalFwFilterListView(APIView):
    """GET /api/v1/netmgmt/portal/fwfilter/?_page=&_limit=&_sort_by=&_order=&_q= -- LIHAT SAJA (read-only), resource DI-HARDCODE ke /ip/firewall/filter. Aksi Grant Access TERPISAH, lihat netmgmt/routeros_firewall_view.py::FirewallGrantAccessView (permission-nya SUDAH diperluas trima izin ini juga)."""
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_fwfilter')]

    def get(self, request):
        host = _resolve_router_ip('fwfilter', settings.MIKROTIK_FWFILTER_ROUTER_IP)
        try:
            connection, api = get_routeros_connection(host)
        except MikrotikConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            rows = api.get_resource('/ip/firewall/filter').get()
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal membaca dari router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            connection.disconnect()

        params = parse_list_params(request)
        if not params['search_fields']:
            params['search_fields'] = ['src-mac-address', 'comment']
        payload = paginate_sort_filter(rows, **params)
        # Router IP INI (bukan dari staff RouterSelector) yang dipakai
        # aksi Grant Access frontend -- disertakan di payload supaya
        # frontend TAHU host mana yg harus dipakai, TIDAK PERLU
        # nebak/hardcode sendiri di Next.js.
        payload['router_ip'] = host
        return Response(payload, status=status.HTTP_200_OK)


class PortalNetwatchListView(APIView):
    """GET /api/v1/netmgmt/portal/netwatch/?_page=&_limit=&_sort_by=&_order=&_q= -- LIHAT SAJA (read-only), resource DI-HARDCODE ke /tool/netwatch."""
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_netwatch')]

    def get(self, request):
        host = settings.MIKROTIK_NETWATCH_ROUTER_IP
        try:
            connection, api = get_routeros_connection(host)
        except MikrotikConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            rows = api.get_resource('/tool/netwatch').get()
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal membaca dari router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            connection.disconnect()

        params = parse_list_params(request)
        if not params['search_fields']:
            params['search_fields'] = ['host', 'comment']
        payload = paginate_sort_filter(rows, **params)
        return Response(payload, status=status.HTTP_200_OK)


class PortalNetwatchActionView(APIView):
    """
    POST /api/v1/netmgmt/portal/netwatch/action/
    Body: {"action": "add"|"edit", "host": "...", "comment": "...", "up-script": "...", "down-script": "...", "id"?: "...id RouterOS, WAJIB utk edit"}

    ⚠️ CUMA 2 aksi (add/edit) -- SENGAJA TIDAK ADA delete (sesuai scope
    yg diminta: "Add/Edit Netwatch host" doang utk portal, hapus TETAP
    staff-only lewat halaman Mikrotik biasa) -- & TIDAK menerima
    resource/command bebas spt proxy generik (`postcmd` dkk).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_netwatch')]

    def post(self, request):
        action = request.data.get('action')
        if action not in ('add', 'edit'):
            return Response({'error': "'action' wajib 'add' atau 'edit'."}, status=status.HTTP_400_BAD_REQUEST)

        host_field = (request.data.get('host') or '').strip()
        if not host_field:
            return Response({'error': "'host' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        entry = {
            'host': host_field,
            'comment': request.data.get('comment', ''),
            'up-script': request.data.get('up-script', ''),
            'down-script': request.data.get('down-script', ''),
        }

        router_host = settings.MIKROTIK_NETWATCH_ROUTER_IP
        try:
            connection, api = get_routeros_connection(router_host)
        except MikrotikConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            resource = api.get_resource('/tool/netwatch')
            if action == 'add':
                resource.add(**entry)
            else:
                entry_id = request.data.get('id')
                if not entry_id:
                    return Response({'error': "'id' wajib diisi utk edit."}, status=status.HTTP_400_BAD_REQUEST)
                resource.set(id=entry_id, **entry)
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal {action} netwatch host di router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            connection.disconnect()

        message = 'Netwatch host berhasil ditambahkan.' if action == 'add' else 'Netwatch host berhasil diperbarui.'
        return Response({'success': True, 'message': message}, status=status.HTTP_200_OK)
