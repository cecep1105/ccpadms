"""
Webhook Netwatch -- BEDA TOTAL dari endpoint netmgmt LAIN (yang dipanggil
user login lewat Next.js/browser, pakai session/JWT) -- endpoint INI
dipanggil LANGSUNG oleh script RouterOS (`/tool fetch`, lihat
test/netwatchscript.txt) tiap kali status up/down 1 host netwatch
BERUBAH, TANPA session/JWT sama sekali (Mikrotik bukan browser).

ALUR (lihat test/netwatchscript.txt utk skrip RouterOS lengkapnya):
  1. Netwatch di Mikrotik pakai up-script/down-script yang panggil
     `/tool fetch` POST ke endpoint ini, body JSON berisi status 1 HOST
     yang BARU SAJA berubah (mis. {"host": "10.0.0.5", "status": "down", ...}).
  2. Endpoint ini TERIMA payload itu (dicatat ke log, TIDAK divalidasi
     ketat -- source-nya Mikrotik sendiri, bukan input user), TAPI --
     PENTING -- broadcast ke frontend BUKAN cuma 1 host itu, MELAINKAN
     QUERY BALIK ke router utk ambil DAFTAR LENGKAP semua netwatch entry
     saat ini (`/tool/netwatch` GET) -- sesuai permintaan: "message list
     netwatch status", bukan cuma 1 entry yang trigger event.
  3. Broadcast lewat wsinfo('netmgmt', 'netwatch', {'results': [...]})
     -- halaman Next.js Mikrotik Netwatch yang lagi dibuka nerima ini
     lewat WebSocket & update tampilan TANPA refresh manual.

KEAMANAN: endpoint ini SENGAJA TIDAK pakai autentikasi Django biasa
(session/JWT, `IsAuthenticated`/`IsStaffRole`) -- Mikrotik (RouterOS
`/tool fetch`) TIDAK bisa login spt browser. Proteksi lewat token
OPSIONAL di query string (`?token=...`, lihat NETWATCH_WEBHOOK_TOKEN di
config/settings.py) -- kalau env var itu KOSONG, endpoint TERBUKA TANPA
proteksi sama sekali (warning dicatat ke log tiap request) -- CUKUP utk
testing/LAN tertutup, tapi SEBAIKNYA diisi utk produksi.
"""
import logging

from django.conf import settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole

from iclock.ws_utils import wsinfo
from netmgmt.routeros_api_view import MikrotikConnectionError, get_routeros_connection

logger = logging.getLogger('netmgmt')

GROUP_NETMGMT = 'netmgmt'


class NetwatchWebhookView(APIView):
    """
    POST /api/v1/netmgmt/nwupdate?token=... (token opsional, lihat docstring modul)
    Body (dikirim Mikrotik, lihat test/netwatchscript.txt): {"host": "...", "status": "up"|"down"|"DOWN", "since": "...", "admshost": "...", "admsstatus": "up"|"down"}

    TIDAK pakai IsAuthenticated/IsStaffRole (lihat docstring modul) --
    permission_classes/authentication_classes SENGAJA dikosongkan/AllowAny
    supaya Django TIDAK minta session/CSRF/JWT apa pun dari Mikrotik.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # KOSONGKAN eksplisit -- default DRF (SessionAuthentication) enforce CSRF, TIDAK cocok utk request dari Mikrotik (bukan browser, tidak punya cookie/CSRF token)

    def post(self, request):
        provided_token = request.query_params.get('token', '')
        if settings.NETWATCH_WEBHOOK_TOKEN:
            if provided_token != settings.NETWATCH_WEBHOOK_TOKEN:
                logger.warning('Netwatch webhook: token ditolak (dari %s).', request.META.get('REMOTE_ADDR', '?'))
                return Response({'error': 'Token tidak valid.'}, status=401)
        else:
            logger.warning(
                'Netwatch webhook: NETWATCH_WEBHOOK_TOKEN belum diisi -- endpoint ini TERBUKA TANPA proteksi. '
                'Isi env var itu utk produksi (lihat config/settings.py).'
            )

        # Payload dari Mikrotik SEKADAR DICATAT (bukan validasi ketat) --
        # source-nya RouterOS sendiri (bukan input user via browser), &
        # yang di-broadcast ke frontend TETAP daftar LENGKAP hasil query
        # ulang (lihat di bawah), BUKAN payload mentah ini.
        logger.info('Netwatch webhook diterima: %s', request.data)

        try:
            connection, api = get_routeros_connection(settings.MIKROTIK_NETWATCH_ROUTER_IP)
        except MikrotikConnectionError as exc:
            logger.warning('Netwatch webhook: gagal konek ke router utk ambil daftar lengkap -- %s', exc)
            return Response({'error': str(exc)}, status=502)

        try:
            try:
                rows = api.get_resource('/tool/netwatch').get()
            except Exception as exc:  # noqa: BLE001
                logger.warning('Netwatch webhook: gagal baca /tool/netwatch dari router -- %s', exc)
                return Response({'error': f'Gagal membaca netwatch dari router: {exc}'}, status=502)
        finally:
            connection.disconnect()

        wsinfo(GROUP_NETMGMT, 'netwatch', {'results': rows})
        logger.info('Netwatch webhook: broadcast %d entry netwatch ke group netmgmt.', len(rows))

        return Response({'success': True, 'count': len(rows)}, status=200)


class NetwatchSummaryView(APIView):
    """
    GET /api/v1/netmgmt/netwatch-summary/ -- {"total_count": N, "down_count": M}

    Dipakai indikator GLOBAL di Topbar (jumlah host down, lihat
    src/components/layout/global-netmgmt-indicators.tsx) utk NILAI AWAL
    saat halaman pertama dibuka (SEBELUM broadcast WebSocket pertama
    masuk) -- update SELANJUTNYA murni lewat WebSocket (section=
    'netwatch', TIDAK panggil endpoint ini lagi berulang).

    PAKAI AUTENTIKASI Django BIASA (IsAuthenticated+IsStaffRole) -- BEDA
    dari NetwatchWebhookView (itu dipanggil Mikrotik langsung, endpoint
    INI dipanggil browser staff yg sudah login, sama spt endpoint netmgmt
    lain.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            connection, api = get_routeros_connection(settings.MIKROTIK_NETWATCH_ROUTER_IP)
        except MikrotikConnectionError as exc:
            return Response({'error': str(exc)}, status=502)

        try:
            try:
                rows = api.get_resource('/tool/netwatch').get()
            except Exception as exc:  # noqa: BLE001
                return Response({'error': f'Gagal membaca netwatch dari router: {exc}'}, status=502)
        finally:
            connection.disconnect()

        down_count = sum(1 for r in rows if r.get('status') == 'down')
        return Response({'total_count': len(rows), 'down_count': down_count}, status=200)
