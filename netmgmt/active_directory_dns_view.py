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

Endpoint `ADDNSZoneListView` CARI KETIGANYA sekaligus (bukan asumsi 1
lokasi tetap), tiap hasil ditandai `partition` biar admin tahu asalnya.

DI DALAM 1 zone, tiap "nama host" (mis. "www" utk www.contoso.com) adalah
1 OBJEK LDAP TERPISAH (objectClass=dnsNode, RDN `DC=<nama>`), dan SATU
objek itu BISA PUNYA BANYAK value di atribut `dnsRecord`-nya (mis. 2 A
record utk round-robin DNS). Krn itu, 1 "record" diidentifikasi via
`node_dn` + isi bytes MENTAH-nya sendiri (dikirim bolak-balik sbg
`raw_b64`, base64) -- BUKAN cuma nama+tipe (bisa ada >1 record SAMA
nama+tipe dlm 1 node).
"""
import base64

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from ldap3 import MODIFY_ADD, MODIFY_DELETE
from netmgmt.active_directory_view import _get_ad_client
from netmgmt.dns_codec import (
    DNS_TYPE_NAMES,
    SUPPORTED_WRITE_TYPES,
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


def _zone_container_dn(partition: str) -> str:
    for name, dn_fn in _ZONE_PARTITIONS:
        if name == partition:
            return f'CN=MicrosoftDNS,{dn_fn()}' if partition != 'legacy' else dn_fn()
    raise LDAPManagementError(f"Partisi zone '{partition}' tidak dikenal.")


class ADDNSZoneListView(APIView):
    """
    GET /api/v1/netmgmt/ad/dns/zones/ -- cari zone DNS di KETIGA partisi
    yang mungkin (forest/domain/legacy), gabungkan hasilnya.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

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
                            zones.append({
                                'dn': row.get('dn', ''),
                                'name': row.get('dc') or row.get('name') or '',
                                'partition': partition,
                            })
                    except LDAPManagementError as exc:
                        # Partisi ini mungkin MEMANG tidak ada (mis. tidak semua AD
                        # punya ForestDnsZones) -- catat tapi JANGAN gagalkan semuanya.
                        errors.append(f'{partition}: {exc}')
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'count': len(zones), 'results': zones, 'partition_errors': errors}, status=status.HTTP_200_OK)


class ADDNSRecordListView(APIView):
    """GET /api/v1/netmgmt/ad/dns/zones/<path:zone_dn>/records/?_page=&_limit=&_sort_by=&_order=&_q=&_search_fields= -- semua record di 1 zone."""
    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request, zone_dn=None):
        try:
            with _get_ad_client() as client:
                nodes = client.search(zone_dn, '(objectClass=dnsNode)', attributes=['dc', 'dnsRecord'])
        except LDAPManagementError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        records = []
        for node in nodes:
            node_name = node.get('dc', '@')
            raw_values = node.get('dnsRecord') or []
            if not isinstance(raw_values, list):
                raw_values = [raw_values]
            for raw in raw_values:
                raw_bytes = bytes(raw) if not isinstance(raw, bytes) else raw
                try:
                    decoded = decode_record(raw_bytes)
                except DnsCodecError:
                    continue  # record rusak/format asing yg tidak bisa di-parse -- lewati drpd crash seluruh list
                records.append({
                    'node_dn': node.get('dn', ''),
                    'name': node_name,
                    'type': decoded.type_name,
                    'ttl_seconds': decoded.ttl_seconds,
                    'data': decoded.data,
                    'raw_b64': base64.b64encode(raw_bytes).decode('ascii'),
                    'editable': decoded.type_name in {DNS_TYPE_NAMES[t] for t in SUPPORTED_WRITE_TYPES},
                })

        params = parse_list_params(request)
        payload = paginate_sort_filter(records, **params)
        return Response(payload, status=status.HTTP_200_OK)


class ADDNSRecordActionView(APIView):
    """
    POST /api/v1/netmgmt/ad/dns/records/
    Body tambah:  {"action": "add", "zone_dn": "...", "name": "www", "type": "A", "data": {"address": "1.2.3.4"}, "ttl_seconds": 3600}
    Body edit:    {"action": "edit", "node_dn": "...", "old_raw_b64": "...", "type": "A", "data": {...}, "ttl_seconds": 3600}
    Body hapus:   {"action": "delete", "node_dn": "...", "old_raw_b64": "..."}
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
        if type_name not in {DNS_TYPE_NAMES[t] for t in SUPPORTED_WRITE_TYPES}:
            raise DnsCodecError(f"Tipe '{type_name}' tidak didukung utk ditulis (lihat netmgmt/dns_codec.py::SUPPORTED_WRITE_TYPES).")
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
                # Node SUDAH ADA (mis. mau tambah A record ke-2 utk round-robin) -- tambah value BARU ke dnsRecord yg sudah ada, JANGAN timpa.
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
            # LDAP tidak punya "replace 1 value dari banyak value" langsung --
            # hapus value LAMA + tambah value BARU, 2 operasi dlm 1 modify() (atomic).
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
            # CATATAN: kalau ini record TERAKHIR di node itu, entry dnsNode akan
            # KOSONG (tanpa value dnsRecord apa pun) tapi TETAP ADA -- sengaja
            # TIDAK auto-hapus node-nya (lebih aman, hindari hapus entry LDAP
            # tanpa sengaja kalau ada atribut lain yg tidak kita ketahui masih dipakai).

        return Response({'success': True, 'message': 'Record berhasil dihapus.'}, status=status.HTTP_200_OK)
