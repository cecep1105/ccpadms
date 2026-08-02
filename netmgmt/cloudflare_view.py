"""
Manajemen DNS Cloudflare (zone/domain + record: tambah/edit/hapus) --
API v4 Cloudflare (`https://api.cloudflare.com/client/v4`), autentikasi
via API Token (Bearer) -- BUKAN Global API Key lama (Token lebih aman,
scope-nya bisa dibatasi per-zone di dashboard Cloudflare).

Pola SAMA dgn netmgmt/zentyal_mail_view.py (Flask, HTTP+JSON polos ke
API eksternal) -- helper generik `call_cloudflare_api()` dipakai semua
view di bawah, BUKAN endpoint per-resource terpisah.

PAGINATION/SORT/SEARCH: Cloudflare API SEBENARNYA punya pagination
sendiri (`page`/`per_page` query param), TAPI supaya KONSISTEN dgn
konvensi netmgmt lain (Mikrotik/AD/Zentyal LDAP/Zentyal Mail, semua
pakai _page/_limit/_sort_by/_order/_q via netmgmt/list_utils.py) &
supaya frontend bisa reuse komponen RouterOS* yang sama, ambil SEMUA
hasil dari Cloudflare (per_page maksimal, lihat _fetch_all_pages()),
lalu pagination/sort/filter dikerjakan ULANG di sini.
"""
import requests
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from netmgmt.crypto_utils import NetmgmtCryptoError, decrypt_cloudflare_token
from netmgmt.list_utils import paginate_sort_filter, parse_list_params

CLOUDFLARE_API_BASE = 'https://api.cloudflare.com/client/v4'
# Tipe record yang didukung utk tambah/edit -- Cloudflare sendiri
# dukung lebih banyak (SRV/CAA/dst), TAPI ini set paling umum dipakai
# admin sehari-hari, gampang ditambah nanti kalau perlu tipe lain.
SUPPORTED_RECORD_TYPES = {'A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS'}
# Tipe yang PUNYA opsi "proxied" (ikon awan oranye Cloudflare, lalu
# lintas dirutekan lewat Cloudflare CDN/proteksi) -- CUMA berlaku utk
# record yang menunjuk ke ALAMAT/HOST (A/AAAA/CNAME), TIDAK utk MX/TXT/NS.
PROXIABLE_RECORD_TYPES = {'A', 'AAAA', 'CNAME'}


class HasCloudflarePermission(BasePermission):
    """
    Staff/superuser SELALU lolos. User non-staff dgn izin granular
    'can_view_cloudflare' BOLEH GET (lihat zone/record) & POST action
    'add'/'edit', TAPI DITOLAK utk action 'delete' -- sesuai batasan yg
    disepakati (portal BISA tambah/edit DNS record, TIDAK BISA hapus).
    CloudflareDnsRecordActionView SATU CLASS menangani KETIGA aksi (beda
    dari Mikrotik Netwatch yg sengaja endpoint delete-nya TIDAK ADA sama
    sekali) -- jadi pengecekan `action`-nya WAJIB di sini, permission
    CLASS-LEVEL biasa tidak bisa lihat isi body request.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_staff or user.is_superuser:
            return True
        if not user.has_perm('iclock.can_view_cloudflare'):
            return False
        if request.method == 'POST' and request.data.get('action') == 'delete':
            return False
        return True


class CloudflareAPIError(Exception):
    """Gagal komunikasi ke API Cloudflare (network/auth/format response/error dari Cloudflare sendiri)."""


def call_cloudflare_api(method: str, path: str, params: dict | None = None, json_body: dict | None = None):
    """
    Helper GENERIK panggil 1 endpoint Cloudflare API v4 -- semua view di
    bawah cuma bungkus tipis di atas ini.
    """
    if not settings.CLOUDFLARE_API_TOKEN_ENCRYPTED:
        raise CloudflareAPIError(
            'Token API Cloudflare belum diisi (CLOUDFLARE_API_TOKEN_ENCRYPTED di .env) -- lihat '
            'netmgmt/crypto_utils.py & management command generate_cloudflare_key/encrypt_cloudflare_token.'
        )
    try:
        token = decrypt_cloudflare_token(settings.CLOUDFLARE_API_TOKEN_ENCRYPTED)
    except NetmgmtCryptoError as exc:
        raise CloudflareAPIError(str(exc)) from exc

    url = CLOUDFLARE_API_BASE + path
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    try:
        resp = requests.request(method, url, params=params, json=json_body, headers=headers, timeout=settings.CLOUDFLARE_API_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise CloudflareAPIError(f'Gagal terhubung ke API Cloudflare: {exc}') from exc

    if resp.status_code == 401 or resp.status_code == 403:
        raise CloudflareAPIError('Token API Cloudflare ditolak (401/403) -- kemungkinan token salah/kedaluwarsa/tidak punya scope yang cukup.')

    try:
        data = resp.json()
    except ValueError as exc:
        raise CloudflareAPIError(f'Respons Cloudflare bukan JSON valid: {exc}') from exc

    # Cloudflare SELALU balas {"success": bool, "errors": [...], "result": ...}
    # -- BEDA dari HTTP status code semata (kadang success:false TAPI status 200).
    if not data.get('success', False):
        errors = data.get('errors') or []
        messages = '; '.join(e.get('message', str(e)) for e in errors) or f'HTTP {resp.status_code}'
        raise CloudflareAPIError(f'Cloudflare menolak request: {messages}')

    return data


def _fetch_all_pages(path: str, params: dict | None = None) -> list:
    """
    Cloudflare API sendiri PAGINATED (per_page maks 100/halaman) -- ambil
    SEMUA halaman dulu (loop sampai habis) sebelum pagination/sort/filter
    KITA SENDIRI diterapkan (lihat catatan docstring modul).
    """
    all_results = []
    page = 1
    while True:
        page_params = dict(params or {}, page=page, per_page=100)
        data = call_cloudflare_api('GET', path, params=page_params)
        results = data.get('result') or []
        all_results.extend(results)
        result_info = data.get('result_info') or {}
        total_pages = result_info.get('total_pages', 1)
        if page >= total_pages or not results:
            break
        page += 1
    return all_results


class CloudflareZoneListView(APIView):
    """GET /api/v1/netmgmt/cloudflare/zones/?_page=&_limit=&_sort_by=&_order=&_q= -- daftar domain (zone) yang bisa diakses token ini."""
    permission_classes = [IsAuthenticated, HasCloudflarePermission]

    def get(self, request):
        try:
            zones = _fetch_all_pages('/zones')
        except CloudflareAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        simplified = [{'id': z['id'], 'name': z['name'], 'status': z.get('status', ''), 'paused': z.get('paused', False)} for z in zones]

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['name']
        payload = paginate_sort_filter(simplified, **list_params)
        return Response(payload, status=status.HTTP_200_OK)


class CloudflareDnsRecordListView(APIView):
    """GET /api/v1/netmgmt/cloudflare/zones/<zone_id>/records/?_page=&_limit=&_sort_by=&_order=&_q= -- daftar DNS record 1 zone."""
    permission_classes = [IsAuthenticated, HasCloudflarePermission]

    def get(self, request, zone_id=None):
        try:
            records = _fetch_all_pages(f'/zones/{zone_id}/dns_records')
        except CloudflareAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        simplified = [{
            'id': r['id'],
            'type': r.get('type', ''),
            'name': r.get('name', ''),
            'content': r.get('content', ''),
            'ttl': r.get('ttl', 1),
            'proxied': r.get('proxied', False),
            'proxiable': r.get('proxiable', False),
            'priority': r.get('priority'),
        } for r in records]

        list_params = parse_list_params(request)
        if not list_params['search_fields']:
            list_params['search_fields'] = ['name', 'content', 'type']
        payload = paginate_sort_filter(simplified, **list_params)
        return Response(payload, status=status.HTTP_200_OK)


class CloudflareDnsRecordActionView(APIView):
    """
    POST /api/v1/netmgmt/cloudflare/zones/<zone_id>/records/action/
    Body tambah: {"action": "add", "type": "A", "name": "www", "content": "1.2.3.4", "ttl": 3600, "proxied": false}
    Body edit:   {"action": "edit", "record_id": "...", "type": "A", "name": "www", "content": "1.2.3.4", "ttl": 3600, "proxied": false}
    Body hapus:  {"action": "delete", "record_id": "..."}

    Izin granular portal (can_view_cloudflare) BOLEH add/edit, DITOLAK
    utk delete -- lihat HasCloudflarePermission di atas.
    """
    permission_classes = [IsAuthenticated, HasCloudflarePermission]

    def post(self, request, zone_id=None):
        action = request.data.get('action')
        if action not in ('add', 'edit', 'delete'):
            return Response({'error': "'action' wajib 'add', 'edit', atau 'delete'."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if action == 'add':
                return self._add(request, zone_id)
            if action == 'edit':
                return self._edit(request, zone_id)
            return self._delete(request, zone_id)
        except CloudflareAPIError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def _build_record_body(self, request) -> dict:
        record_type = request.data.get('type')
        if record_type not in SUPPORTED_RECORD_TYPES:
            raise ValueError(f"Tipe '{record_type}' tidak didukung -- pilih salah satu dari {sorted(SUPPORTED_RECORD_TYPES)}.")
        name = request.data.get('name')
        content = request.data.get('content')
        if not name or not content:
            raise ValueError("'name' dan 'content' wajib diisi.")

        body = {
            'type': record_type,
            'name': name,
            'content': content,
            'ttl': int(request.data.get('ttl', 1)),  # 1 = "Auto" di Cloudflare (otomatis, biasanya 300s kalau proxied)
        }
        if record_type in PROXIABLE_RECORD_TYPES:
            body['proxied'] = bool(request.data.get('proxied', False))
        if record_type == 'MX':
            priority = request.data.get('priority')
            if priority is None:
                raise ValueError("'priority' wajib diisi utk record MX.")
            body['priority'] = int(priority)
        return body

    def _add(self, request, zone_id):
        try:
            body = self._build_record_body(request)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        call_cloudflare_api('POST', f'/zones/{zone_id}/dns_records', json_body=body)
        return Response({'success': True, 'message': 'Record berhasil ditambahkan.'}, status=status.HTTP_200_OK)

    def _edit(self, request, zone_id):
        record_id = request.data.get('record_id')
        if not record_id:
            return Response({'error': "'record_id' wajib diisi utk edit."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            body = self._build_record_body(request)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        call_cloudflare_api('PUT', f'/zones/{zone_id}/dns_records/{record_id}', json_body=body)
        return Response({'success': True, 'message': 'Record berhasil diperbarui.'}, status=status.HTTP_200_OK)

    def _delete(self, request, zone_id):
        record_id = request.data.get('record_id')
        if not record_id:
            return Response({'error': "'record_id' wajib diisi utk hapus."}, status=status.HTTP_400_BAD_REQUEST)

        call_cloudflare_api('DELETE', f'/zones/{zone_id}/dns_records/{record_id}')
        return Response({'success': True, 'message': 'Record berhasil dihapus.'}, status=status.HTTP_200_OK)
