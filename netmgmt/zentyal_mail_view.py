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
"""
import requests
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_zentyal_mail_token


class ZentyalMailAPIError(Exception):
    """Gagal komunikasi ke Flask API Zentyal Mail (network/auth/format response)."""


def _call_flask_api(method: str, path: str, params: dict | None = None, json_body: dict | None = None):
    """
    Helper GENERIK panggil 1 endpoint Flask -- semua Resource class di
    bawah cuma bungkus tipis di atas ini, beda-beda path/params/method saja.
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
    GET  /api/v1/netmgmt/zentyal-mail/queue/ -- daftar mail queue + imaplogs.
    POST /api/v1/netmgmt/zentyal-mail/queue/ -- {"command": "DELETE"|"REQUEUE"|"DELQFROMSENDER", "qids": [...], "sender": "..."}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = _call_flask_api('GET', '/mailq')
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        try:
            data = _call_flask_api('POST', '/mailq', json_body=request.data)
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailTodayLogView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/today-log/ -- ringkasan mail hari ini (qid, sender, ukuran, dst)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = _call_flask_api('GET', '/postfix', params={'command': 'today_log'})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailDetailLogView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/detail-log/?qid=... -- baris log lengkap 1 queue ID."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        qid = request.query_params.get('qid', '')
        if not qid:
            return Response({'error': "Parameter 'qid' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = _call_flask_api('GET', '/postfix', params={'command': 'detail_log', 'qid': qid})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailQHeaderView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/qheader/?qid=... -- header mentah 1 pesan di queue (postcat -h)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        qid = request.query_params.get('qid', '')
        if not qid:
            return Response({'error': "Parameter 'qid' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = _call_flask_api('GET', '/postfix', params={'command': 'qheader', 'qid': qid})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailLogView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/log/?date_from=&date_to= -- histori mail dari DB Zentyal (rentang tanggal, default hari ini)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        params = {}
        if request.query_params.get('date_from'):
            params['date_from'] = request.query_params['date_from']
        if request.query_params.get('date_to'):
            params['date_to'] = request.query_params['date_to']
        try:
            data = _call_flask_api('GET', '/postfix', params=dict(params, command='mail_log'))
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailTransportView(APIView):
    """
    GET  /api/v1/netmgmt/zentyal-mail/transport/ -- daftar transport map.
    POST /api/v1/netmgmt/zentyal-mail/transport/ -- {"transport_data": [{"domain":..., "target":..., "status": true|false}, ...]}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = _call_flask_api('GET', '/postfix', params={'command': 'transport_map'})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        try:
            data = _call_flask_api('POST', '/postfix', json_body={
                'command': 'set_transport',
                'transport_data': request.data.get('transport_data', []),
            })
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailBlockSendersView(APIView):
    """
    GET  /api/v1/netmgmt/zentyal-mail/block-senders/ -- daftar sender yang diblokir.
    POST /api/v1/netmgmt/zentyal-mail/block-senders/ -- {"email": "spammer@contoh.com"}
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = _call_flask_api('GET', '/postfix', params={'command': 'blocksenders_map'})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        email = request.data.get('email', '')
        if not email:
            return Response({'error': "'email' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = _call_flask_api('POST', '/postfix', json_body={'command': 'set_blocksenders', 'email': email})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailImapLogsView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/imap-logs/?time=minute|hour|day -- log percobaan login IMAP GAGAL."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        time_arg = request.query_params.get('time', 'minute')
        try:
            data = _call_flask_api('GET', '/imaplogs', params={'time': time_arg})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailSaslLogsView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/sasl-logs/?time=minute|hour|day -- log percobaan autentikasi SASL GAGAL (dikelompokkan per IP)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        time_arg = request.query_params.get('time', 'minute')
        try:
            data = _call_flask_api('GET', '/sasllogs', params={'time': time_arg})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)


class ZentyalMailIpViaEmailView(APIView):
    """GET /api/v1/netmgmt/zentyal-mail/ip-via-email/ -- pemetaan user email -> IP internal (dari log webmail/relay)."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        try:
            data = _call_flask_api('GET', '/ipviaemail')
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
            data = _call_flask_api('POST', '/postfix', json_body={'command': action})
        except ZentyalMailAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data, status=status.HTTP_200_OK)
