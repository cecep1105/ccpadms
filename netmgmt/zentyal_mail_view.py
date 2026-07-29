"""
Proxy Django ke API Zentyal Mail (Flask, Python 2.7, server TERPISAH --
lihat test/zentyalmail_v2.py & test/README.md). Django panggil API ini
server-to-server (bukan browser langsung ke Flask) -- token API dikirim
lewat header `X-API-Token`, didekripsi dari ZENTYAL_MAIL_API_TOKEN_ENCRYPTED
tiap request (sama pola dgn kredensial netmgmt lain -- Mikrotik/AD/Zentyal
LDAP -- lihat netmgmt/crypto_utils.py).

BEDA dari netmgmt/zentyal_view.py (itu LDAP, users/groups) -- modul INI
protokolnya HTTP+JSON polos ke Flask app terpisah, konsepnya lebih mirip
netmgmt/routeros_api_view.py (proxy ke API eksternal) drpd LDAP.

PAGINATION/SORT/FILTER: Flask API kembalikan SEMUA hasil sekaligus (tidak
ada pagination server-side di Flask) -- jadi endpoint di sini yang
terapkan pagination/sort/filter, pakai helper yang SAMA dgn Mikrotik/AD/
Zentyal LDAP (netmgmt/list_utils.py, konvensi param _page/_limit/
_sort_by/_order/_q/_search_fields), supaya frontend bisa reuse komponen
RouterOS* yang sudah ada (lihat components/netmgmt/routeros-*.tsx).

`call_flask_mail_api()` SENGAJA PUBLIC (bukan `_call_flask_api` lagi) --
dipakai jg oleh netmgmt/tasks.py (Celery Beat, cek mailq tiap 1 menit &
broadcast lewat WebSocket, lihat netmgmt/consumers.py).
"""
import requests
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_zentyal_mail_token
from netmgmt.list_utils import paginate_sort_filter, parse_list_params


class ZentyalMailAPIError(Exception):
    """Gagal komunikasi ke Flask API Zentyal Mail (network/auth/format response)."""


def call_flask_mail_api(method: str, path: str, params: dict | None = None, json_body: dict | None = None):
    """
    Helper GENERIK panggil 1 endpoint Flask -- semua Resource class di
    bawah cuma bungkus tipis di atas ini, beda-beda path/params/method saja.
    JUGA dipakai netmgmt/tasks.py::check_mailq (Celery Beat).
    """
    if not settings.ZENTYAL_MAIL_API_URL:
        raise ZentyalMailAPIError('ZENTYAL_MAIL_API_URL belum diisi di .env.')
    if not settings.ZENTYAL_MAIL_API_TOKEN_ENCRYPTED:
        raise ZentyalMailAPIError(
            'Token API Zentyal Mail belum diisi (ZENTYAL_MAIL_API_TOKEN_ENCRYPTED di .env) -- lihat '
            'netmgmt/crypto_utils.py & management command generate_zentyal_mail_key/encrypt_zentyal_mail_token.'
        )
    try:
        token = decrypt_zentyal_mail_token(settings.ZENTYAL_MAIL_API_TOKEN_ENCRYPTED)
    except NetmgmtCryptoError as exc:
        raise ZentyalMailAPIError(str(exc)) from exc

    url = settings.ZENTYAL_MAIL_API_URL.rstrip('/') + path
    headers = {'X-API-Token': token}

    try:
        resp = requests.request(
            method, url, params=params, json=json_body, headers=headers,
            timeout=settings.ZENTYAL_MAIL_API_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise ZentyalMailAPIError(f'Gagal terhubung ke Zentyal Mail API di {url}: {exc}') from exc

    if resp.status_code == 401:
        raise ZentyalMailAPIError('Token API Zentyal Mail ditolak server (401) -- kemungkinan token di .env TIDAK COCOK dgn yang di-set di server Flask.')
    if resp.status_code >= 500:
        raise ZentyalMailAPIError(f'Zentyal Mail API error {resp.status_code}: {resp.text[:300]}')
    if resp.status_code >= 400:
        try:
            detail = resp.json().get('error', resp.text[:300])
        except ValueError:
            detail = resp.text[:300]
        raise ZentyalMailAPIError(f'Zentyal Mail API menolak request ({resp.status_code}): {detail}')

    try:
        return resp.json()
    except ValueError as exc:
        raise ZentyalMailAPIError(f'Respons Zentyal Mail API bukan JSON valid: {exc}') from exc


class ZentyalMailQueueView(APIView):
    """
    GET  /api/v1/netmgmt/zentyal-mail/queue/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields=
         -- daftar mail queue (dipaginasi/sort/filter) + imaplogs (APA ADANYA, tidak dipaginasi -- data sekunder).
    POST /api/v1/netmgmt/zentyal-mail/queue/ -- {"command": "DELETE"|"REQUEUE"|"DELQFROMSENDER", "qids": [...], "sender": "..."}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = call_flask_mail_api('GET', '/mailq')
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        # search default ke sender+recipient+id kalau frontend tidak kirim _search_fields eksplisit
        if not list_params['search_fields']:
            list_params['search_fields'] = ['sender', 'recipient', 'id']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        payload['imaplogs'] = data.get('imaplogs', [])
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        try:
            data = call_flask_mail_api('POST', '/mailq', json_body=request.data)
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailTodayLogView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/today-log/?_page=&_limit=&_sort_by=&_order=&_q= -- ringkasan mail hari ini."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = call_flask_mail_api('GET', '/postfix', params={'command': 'today_log'})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['sender', 'qid']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalMailDetailLogView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/detail-log/?qid=... -- baris log lengkap 1 queue ID (TIDAK dipaginasi -- log 1 pesan spesifik, biasanya sedikit baris)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        qid = request.query_params.get('qid', '')
        if not qid:
            return Response({'error': "Parameter 'qid' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = call_flask_mail_api('GET', '/postfix', params={'command': 'detail_log', 'qid': qid})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailQHeaderView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/qheader/?qid=... -- header mentah 1 pesan di queue (postcat -h) -- TIDAK dipaginasi."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        qid = request.query_params.get('qid', '')
        if not qid:
            return Response({'error': "Parameter 'qid' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = call_flask_mail_api('GET', '/postfix', params={'command': 'qheader', 'qid': qid})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailLogView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/log/?date_from=&date_to=&_page=&_limit=&_sort_by=&_order=&_q= -- histori mail dari DB Zentyal."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        params = {}
        if request.query_params.get('date_from'):
            params['date_from'] = request.query_params['date_from']
        if request.query_params.get('date_to'):
            params['date_to'] = request.query_params['date_to']
        try:
            data = call_flask_mail_api('GET', '/postfix', params=dict(params, command='mail_log'))
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['from_address', 'to_address', 'qid']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalMailTransportView(APIView):
    """
    GET  /api/v1/netmgmt/zentyal-mail/transport/?_page=&_limit=&_sort_by=&_order=&_q= -- daftar transport map.
    POST /api/v1/netmgmt/zentyal-mail/transport/ -- {"transport_data": [{"domain":..., "target":..., "status": true|false}, ...]}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = call_flask_mail_api('GET', '/postfix', params={'command': 'transport_map'})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['domain', 'target']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        try:
            data = call_flask_mail_api('POST', '/postfix', json_body={
                'command': 'set_transport',
                'transport_data': request.data.get('transport_data', []),
            })
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailBlockSendersView(APIView):
    """
    GET  /api/v1/netmgmt/zentyal-mail/block-senders/?_page=&_limit=&_sort_by=&_order=&_q= -- daftar sender yang diblokir.
    POST /api/v1/netmgmt/zentyal-mail/block-senders/ -- {"email": "spammer@contoh.com"}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = call_flask_mail_api('GET', '/postfix', params={'command': 'blocksenders_map'})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['email']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        email = request.data.get('email', '')
        if not email:
            return Response({'error': "'email' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = call_flask_mail_api('POST', '/postfix', json_body={'command': 'set_blocksenders', 'email': email})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailImapLogsView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/imap-logs/?time=minute|hour|day&_page=&_limit=&_sort_by=&_order=&_q= -- log percobaan login IMAP GAGAL."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        time_arg = request.query_params.get('time', 'minute')
        try:
            data = call_flask_mail_api('GET', '/imaplogs', params={'time': time_arg})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['email', 'ip']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalMailSaslLogsView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/sasl-logs/?time=minute|hour|day&_page=&_limit=&_sort_by=&_order=&_q= -- log percobaan autentikasi SASL GAGAL (dikelompokkan per IP)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        time_arg = request.query_params.get('time', 'minute')
        try:
            data = call_flask_mail_api('GET', '/sasllogs', params={'time': time_arg})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['ip']
        payload = paginate_sort_filter(data.get('result', []), **list_params)
        return Response(payload, status=status.HTTP_200_OK)


class ZentyalMailIpViaEmailView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/ip-via-email/ -- pemetaan user email -> IP internal (dari log webmail/relay), TIDAK dipaginasi (biasanya sedikit baris)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = call_flask_mail_api('GET', '/ipviaemail')
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailControlView(APIView):
    """POST /api/v1/netmgmt/zentyal-mail/control/ -- {"action": "reload"|"flush"} -- kontrol service Postfix."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        action = request.data.get('action')
        if action not in ('reload', 'flush'):
            return Response({'error': "'action' wajib 'reload' atau 'flush'."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = call_flask_mail_api('POST', '/postfix', json_body={'command': action})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)
