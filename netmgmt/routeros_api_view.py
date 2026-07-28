"""
Proxy generik ke RouterOS API (Mikrotik) -- SATU endpoint yang bisa
menjalankan HAMPIR SEMUA command RouterOS (baca/tulis), lewat parameter
URL `host` (IP/hostname router) & `command` (path RouterOS, format URL-safe).

KENAPA DESAINNYA BEGINI (generik, bukan 1 endpoint per resource spt
Employee/Department dkk): RouterOS API punya BANYAK SEKALI "resource"
(DHCP lease, firewall filter, netwatch, dst, puluhan lainnya) -- bikin 1
ViewSet Django per resource spt pola CRUD biasa di app lain TIDAK PRAKTIS
(perlu puluhan file/URL). Endpoint generik ini CUKUP 1 kali dibuat,
dipakai ULANG oleh SEMUA halaman Mikrotik di frontend (DHCP, Firewall
Filter, Netwatch, dst) cuma beda `command`-nya.

KONVENSI PENULISAN COMMAND (di URL, lihat contoh di frontend
nextadms/src/app/(dashboard)/netmgmt/mikrotik/*/page.tsx):
    ip-dhcp_server-lease   ->  /ip/dhcp-server/lease   (RouterOS asli)
    system-resource        ->  /system/resource
Aturan konversi (lihat _format_command() di bawah):  "_" -> "-",  "-" -> "/"

PENTING -- KENAPA PAGINATION/SORT/SEARCH BEDA POLA dari tabel Django
biasa: data di sini TIDAK ADA di database Django SAMA SEKALI -- diambil
LANGSUNG dari router lewat API tiap request. Pagination/sort/search
dikerjakan MANUAL di Python SETELAH data mentah didapat dari router --
logic-nya sekarang di `netmgmt/list_utils.py` (DIPAKAI BERSAMA fitur
netmgmt lain -- Active Directory, Zentyal LDAP -- BUKAN cuma Mikrotik,
supaya tidak duplikat 3x spt yang sempat terjadi di frontend).

Parameter kontrol (prefix underscore -- lihat netmgmt/list_utils.py):
    _page, _limit, _sort_by, _order, _q, _search_fields
"""
import re

import routeros_api
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_mikrotik_password
from netmgmt.list_utils import paginate_sort_filter, parse_list_params

# Semua parameter KONTROL (bukan argumen asli command RouterOS) -- WAJIB
# di-strip dari params sebelum diteruskan ke `.get(**params)`, supaya
# RouterOS tidak terima parameter aneh yang tidak dia kenal.
_CONTROL_PARAMS = {'_page', '_limit', '_sort_by', '_order', '_q', '_search_fields'}


def _format_command(command: str) -> str:
    """'ip-dhcp_server-lease' -> '/ip/dhcp-server/lease' (lihat konvensi di docstring modul)."""
    mapping = {'_': '-', '-': '/'}
    pattern = re.compile('|'.join(re.escape(k) for k in mapping))
    return '/' + pattern.sub(lambda m: mapping[m.group(0)], command)


class MikrotikConnectionError(Exception):
    """Gagal terhubung/autentikasi ke router Mikrotik."""


class RouterOSCommandView(APIView):
    """
    GET  /api/v1/netmgmt/routeros/<host>/<command>/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields=
        -> baca resource (mis. daftar DHCP lease), dgn pagination/sort/search MANUAL (lihat netmgmt/list_utils.py).
    POST /api/v1/netmgmt/routeros/<host>/<command>/?postcmd=<nama-command-RouterOS, mis. 'remove'/'make-static'>
        -> eksekusi command TULIS (body JSON diteruskan sbg argumen ke command itu, mis. {"id": ".id123"}).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.username = 'admin'  # TODO: kalau nanti multi-router dgn username beda2, jadikan bagian config per-router
        self.port = 8728
        self.connection = None
        self.api = None

        if not settings.MIKROTIK_PASSWORD_ENCRYPTED:
            raise MikrotikConnectionError(
                'Password Mikrotik belum diisi (MIKROTIK_PASSWORD_ENCRYPTED di .env) -- lihat '
                'netmgmt/crypto_utils.py & management command generate_mikrotik_key/encrypt_mikrotik_password.'
            )
        try:
            self.password = decrypt_mikrotik_password(settings.MIKROTIK_PASSWORD_ENCRYPTED)
        except NetmgmtCryptoError as exc:
            raise MikrotikConnectionError(str(exc)) from exc

    def initial(self, request, *args, **kwargs):
        """Konek ke router SEBELUM get()/post() diproses -- host diambil dari URL (lihat api_urls.py)."""
        super().initial(request, *args, **kwargs)
        host = kwargs.get('host')
        try:
            self.connection = routeros_api.RouterOsApiPool(
                host, username=self.username, password=self.password,
                port=self.port, plaintext_login=True,
            )
            self.api = self.connection.get_api()
        except Exception as exc:  # noqa: BLE001
            raise MikrotikConnectionError(f"Gagal terhubung ke router '{host}': {exc}") from exc

    def finalize_response(self, request, response, *args, **kwargs):
        """Tutup koneksi ke router SETELAH response selesai dibentuk -- jangan biarkan koneksi menggantung."""
        if self.connection:
            self.connection.disconnect()
        return super().finalize_response(request, response, *args, **kwargs)

    def get(self, request, host=None, command=None, format=None):
        if not command:
            return Response({'error': 'Command wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)

        extra_params = {k: v for k, v in request.GET.items() if k not in _CONTROL_PARAMS}
        params = parse_list_params(request)
        # RouterOS pakai dash ("mac-address") -- terima underscore JUGA (URL/JS lebih nyaman), konversi ke dash.
        params['sort_by'] = params['sort_by'].replace('_', '-')

        formatted_cmd = _format_command(command)
        try:
            rows = self.api.get_resource(formatted_cmd).get(**extra_params)
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'Gagal membaca dari router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        payload = paginate_sort_filter(rows, **params)
        payload['command'] = formatted_cmd
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request, host=None, command=None, format=None):
        """Eksekusi command TULIS RouterOS, mis. ?postcmd=remove utk hapus 1 lease (body: {"id": ".id..."})."""
        if not command:
            return Response({'error': 'Command wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)

        postcmd = request.query_params.get('postcmd', '')
        if not postcmd:
            return Response({'error': "Parameter '?postcmd=' wajib diisi utk POST (mis. 'remove', 'make-static')."}, status=status.HTTP_400_BAD_REQUEST)

        formatted_cmd = _format_command(command)
        try:
            result = self.api.get_resource(formatted_cmd).call(postcmd, request.data)
            return Response({'command': formatted_cmd, 'results': result}, status=status.HTTP_200_OK)
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f"Gagal eksekusi '{postcmd}' di router: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
