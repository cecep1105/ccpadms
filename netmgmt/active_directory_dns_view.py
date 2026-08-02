"""
Manajemen DNS zone & record Active Directory (AD-integrated DNS) --
BEDA TOTAL dari users/groups (netmgmt/active_directory_view.py): data
disimpan lewat atribut LDAP `dnsRecord` dalam FORMAT BINARY PROPRIETARY
Microsoft (lihat netmgmt/dns_codec.py utk encode/decode-nya, dan
peringatan risiko di sana).

LOKASI ZONE DNS DI AD -- ADA 3 KEMUNGKINAN PARTISI (makanya fitur ini
sebut "Forest" & "non-Forest"):
  1. **Forest zone** -- `DC=ForestDnsZones,<forest-root-DN>` -- direplikasi
     ke SEMUA DNS server di SELURUH FOREST (lintas domain kalau multi-domain).
  2. **Domain zone** -- `DC=DomainDnsZones,<domain-DN>` -- direplikasi HANYA
     dalam 1 domain (default Windows 2003+ utk zone AD-integrated biasa).
  3. **Legacy zone** ("non-Forest" versi lama, Windows 2000-style) --
     `CN=MicrosoftDNS,CN=System,<domain-DN>` -- masih ada di banyak AD lama
     demi kompatibilitas, direplikasi lewat domain naming context biasa.

FILTER TAMPILAN (sesuai permintaan -- fokus ke kasus pemakaian PALING
UMUM, sembunyikan kompleksitas internal AD):
  - Zone REVERSE lookup (nama berakhiran ".in-addr.arpa"/".ip6.arpa")
    DISEMBUNYIKAN -- cuma forward zone yang ditampilkan.
  - Zone BAWAAN AD (`_msdcs.<forest-root>`, `RootDNSServers`,
    `..TrustAnchors`) DISEMBUNYIKAN -- itu infrastruktur internal AD
    sendiri (lokasi DC, DNSSEC trust anchor), BUKAN zone yang lazim
    dikelola admin sehari-hari.
  - Record TIPE selain A & CNAME DISEMBUNYIKAN dari daftar (tapi kalau
    ADA record tipe lain di suatu node, node itu TETAP UTUH -- fitur ini
    cuma tidak MENAMPILKAN/menawarkan edit tipe lain, tidak menghapus
    apa pun secara diam-diam).

DI DALAM 1 zone, tiap "nama host" (mis. "www" utk www.contoso.com) adalah
1 OBJEK LDAP TERPISAH (objectClass=dnsNode, RDN `DC=<nama>`), dan SATU
objek itu BISA PUNYA BANYAK value di atribut `dnsRecord`-nya (mis. 2 A
record utk round-robin DNS). Krn itu, 1 "record" diidentifikasi via
`node_dn` + isi bytes MENTAH-nya sendiri (dikirim bolak-balik sbg
`raw_b64`, base64) -- BUKAN cuma nama+tipe (bisa ada >1 record SAMA
nama+tipe dlm 1 node).
"""
import base64
import re

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFeaturePermission, IsStaffRole
from ldap3 import MODIFY_ADD, MODIFY_DELETE
from netmgmt.active_directory_view import _get_ad_client
from netmgmt.dns_codec import (
    DnsCodecError,
    DnsRecord,
    decode_record,
    encode_record,
)
from netmgmt.ldap_utils import LDAPManagementClient, LDAPManagementError
from netmgmt.list_utils import paginate_sort_filter, parse_list_params

_ZONE_PARTITIONS = [
    ('forest', lambda: f'DC=ForestDnsZones,{settings.AD_FOREST_BASE_DN}'),
    ('domain', lambda: f'DC=DomainDnsZones,{settings.AD_BASE_DN}'),
    ('legacy', lambda: f'CN=MicrosoftDNS,CN=System,{settings.AD_BASE_DN}'),
]

# --- Filter zone: forward-only, sembunyikan zone bawaan AD ---
_REVERSE_ZONE_PATTERN = re.compile(r'\.(in-addr|ip6)\.arpa$', re.IGNORECASE)
_AD_BUILTIN_ZONE_NAMES = {'rootdnsservers', '..trustanchors'}


def _is_visible_forward_zone(zone_name: str) -> bool:
    name_lower = (zone_name or '').lower()
    if not name_lower:
        return False
    if _REVERSE_ZONE_PATTERN.search(name_lower):
        return False  # reverse lookup zone (mis. "1.168.192.in-addr.arpa")
    if name_lower in _AD_BUILTIN_ZONE_NAMES:
        return False  # zone infrastruktur AD bawaan
    if name_lower.startswith('_msdcs.'):
        return False  # zone lokasi Domain Controller (SRV record internal AD)
    return True


# --- Filter record: cuma A & CNAME yang ditampilkan/bisa dikelola lewat fitur ini ---
_VISIBLE_RECORD_TYPES = {'A', 'CNAME'}


class ADDNSZoneListView(APIView):
    """
    GET /api/v1/netmgmt/ad/dns/zones/ -- cari zone DNS FORWARD di KETIGA
    partisi yang mungkin (forest/domain/legacy), gabungkan hasilnya --
    zone reverse-lookup & zone bawaan AD (_msdcs, dst) DISEMBUNYIKAN
    (lihat _is_visible_forward_zone).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_ad_dns')]

    def get(self, request):
        zones = []
        errors = []
        try:
            with _get_ad_client() as client:
                for partition, dn_fn in _ZONE_PARTITIONS:
                    container = f'CN=MicrosoftDNS,{dn_fn()}' if partition != 'legacy' else dn_fn()
                    try:
                        rows = client.search(container, '(objectClass=dnsZone)', attributes=['dc', 'name'])
                        for row in rows:
                            # Sama spt catatan di ADDNSRecordListView -- ldap3 bungkus
                            # nilai atribut jadi list, WAJIB dibongkar dulu.
                            dc_value = row.get('dc') or row.get('name') or ''
                            zone_name = dc_value[0] if isinstance(dc_value, list) and dc_value else dc_value
                            if not _is_visible_forward_zone(zone_name):
                                continue
                            zones.append({'dn': row.get('dn', ''), 'name': zone_name, 'partition': partition})
                    except LDAPManagementError as exc:
                        errors.append(f'{partition}: {exc}')
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'count': len(zones), 'results': zones, 'partition_errors': errors}, status=status.HTTP_200_OK)


class ADDNSRecordListView(APIView):
    """
    GET /api/v1/netmgmt/ad/dns/zones/<path:zone_dn>/records/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields=
    -- record di 1 zone, DIFILTER cuma tipe A & CNAME (lihat _VISIBLE_RECORD_TYPES).
    """
    permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_view_ad_dns')]

    def get(self, request, zone_dn=None):
        try:
            with _get_ad_client() as client:
                nodes = client.search(zone_dn, '(objectClass=dnsNode)', attributes=['dc', 'dnsRecord'])
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        records = []
        for node in nodes:
            # PENTING: ldap3 SELALU bungkus nilai atribut jadi list (bahkan
            # utk atribut single-value spt `dc`) -- SEBELUMNYA baris ini
            # pakai node.get('dc', '@') LANGSUNG tanpa bongkar list, jadi
            # `node_name` jadi ['mixed'] bukan 'mixed' (ketahuan pas
            # testing, bandingkan pola yg SAMA dgn _attr() helper di
            # netmgmt/active_directory_view.py yg SUDAH benar).
            dc_value = node.get('dc', '@')
            node_name = dc_value[0] if isinstance(dc_value, list) and dc_value else (dc_value or '@')
            raw_values = node.get('dnsRecord') or []
            if not isinstance(raw_values, list):
                raw_values = [raw_values]
            for raw in raw_values:
                raw_bytes = bytes(raw) if not isinstance(raw, bytes) else raw
                try:
                    decoded = decode_record(raw_bytes)
                except DnsCodecError:
                    continue  # record rusak/format asing -- lewati drpd crash seluruh list
                if decoded.type_name not in _VISIBLE_RECORD_TYPES:
                    continue  # sesuai permintaan -- cuma A & CNAME yang ditampilkan
                records.append({
                    'node_dn': node.get('dn', ''),
                    'name': node_name,
                    'type': decoded.type_name,
                    'ttl_seconds': decoded.ttl_seconds,
                    'data': decoded.data,
                    'raw_b64': base64.b64encode(raw_bytes).decode('ascii'),
                    'editable': True,  # A & CNAME KEDUANYA didukung tulis penuh (lihat dns_codec.py::SUPPORTED_WRITE_TYPES)
                })

        params = parse_list_params(request)
        payload = paginate_sort_filter(records, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ADDNSRecordActionView(APIView):
    """
    POST /api/v1/netmgmt/ad/dns/records/
    Body tambah:  {"action": "add", "zone_dn": "...", "name": "www", "type": "A"|"CNAME", "data": {...}, "ttl_seconds": 3600}
    Body edit:    {"action": "edit", "node_dn": "...", "old_raw_b64": "...", "type": "A"|"CNAME", "data": {...}, "ttl_seconds": 3600}
    Body hapus:   {"action": "delete", "node_dn": "...", "old_raw_b64": "..."}

    Sesuai permintaan, endpoint ini HANYA terima tipe A & CNAME (biar pun
    dns_codec.py sendiri MENDUKUNG lebih banyak tipe -- pembatasan ini
    SENGAJA di level view, bukan di codec, supaya codec tetap generik
    kalau nanti perlu dibuka lagi ke tipe lain).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request):
        action = request.data.get('action')
        if action not in ('add', 'edit', 'delete'):
            return Response({'error': "'action' wajib 'add', 'edit', atau 'delete'."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if action == 'add':
                return self._add(request)
            if action == 'edit':
                return self._edit(request)
            return self._delete(request)
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except DnsCodecError as exc:
            return Response({'error': f'Data record tidak valid: {exc}'}, status=status.HTTP_400_BAD_REQUEST)
        except KeyError as exc:
            return Response({'error': f'Field data wajib diisi: {exc}'}, status=status.HTTP_400_BAD_REQUEST)

    def _build_record(self, request) -> DnsRecord:
        type_name = request.data.get('type')
        if type_name not in _VISIBLE_RECORD_TYPES:
            raise DnsCodecError(f"Tipe '{type_name}' tidak didukung -- fitur ini hanya menerima A & CNAME.")
        return DnsRecord(
            type_name=type_name,
            data=request.data.get('data') or {},
            ttl_seconds=int(request.data.get('ttl_seconds', 3600)),
        )

    def _add(self, request):
        zone_dn = request.data.get('zone_dn')
        name = request.data.get('name')
        if not zone_dn or not name:
            return Response({'error': "'zone_dn' dan 'name' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)

        record = self._build_record(request)
        encoded = encode_record(record)
        node_dn = f'DC={LDAPManagementClient.escape(name)},{zone_dn}'

        with _get_ad_client() as client:
            existing = client.search(zone_dn, f'(&(objectClass=dnsNode)(dc={LDAPManagementClient.escape(name)}))', attributes=['dc'])
            if existing:
                client.modify_raw_attribute(existing[0]['dn'], 'dnsRecord', encoded, MODIFY_ADD)
            else:
                client.add_entry(node_dn, ['top', 'dnsNode'], {'dnsRecord': [encoded]})

        return Response({'success': True, 'message': 'Record berhasil ditambahkan.'}, status=status.HTTP_200_OK)

    def _edit(self, request):
        node_dn = request.data.get('node_dn')
        old_raw_b64 = request.data.get('old_raw_b64')
        if not node_dn or not old_raw_b64:
            return Response({'error': "'node_dn' dan 'old_raw_b64' wajib diisi utk edit."}, status=status.HTTP_400_BAD_REQUEST)

        record = self._build_record(request)
        new_encoded = encode_record(record)
        old_encoded = base64.b64decode(old_raw_b64)

        with _get_ad_client() as client:
            client.replace_raw_attribute_value(node_dn, 'dnsRecord', old_encoded, new_encoded)

        return Response({'success': True, 'message': 'Record berhasil diperbarui.'}, status=status.HTTP_200_OK)

    def _delete(self, request):
        node_dn = request.data.get('node_dn')
        old_raw_b64 = request.data.get('old_raw_b64')
        if not node_dn or not old_raw_b64:
            return Response({'error': "'node_dn' dan 'old_raw_b64' wajib diisi utk hapus."}, status=status.HTTP_400_BAD_REQUEST)

        old_encoded = base64.b64decode(old_raw_b64)
        with _get_ad_client() as client:
            client.modify_raw_attribute(node_dn, 'dnsRecord', old_encoded, MODIFY_DELETE)

        return Response({'success': True, 'message': 'Record berhasil dihapus.'}, status=status.HTTP_200_OK)
