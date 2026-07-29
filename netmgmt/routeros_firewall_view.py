"""
Workflow SPESIFIK: berikan akses internet ke 1 device (berdasarkan MAC
address) di Mikrotik -- BUKAN endpoint generik spt routeros_api_view.py,
tapi enkapsulasi 1 alur kerja BERULANG yang biasa dikerjakan MANUAL:

  1. Tahu IP address device yang mau diberi akses (biasanya ditanya user).
  2. Cari MAC address-nya lewat DHCP lease (berdasarkan IP itu).
  3. Buat firewall filter rule BARU, dgn field2 (chain/action/protocol/dst)
     DISALIN dari rule yang PERSIS ada di posisi SEBELUM rule ber-comment
     'BLOCK-ELSE' (asumsi: rule di posisi itu SELALU jadi "template" utk
     rule per-MAC berikutnya, krn rule BARU jg selalu disisipkan tepat di
     situ, jadi rule LAMA yg sebelumnya di situ otomatis jadi rule "kedua
     terakhir" -- pola brantai/template konsisten).
  4. src-mac-address & comment DIGANTI (bukan disalin dari template) --
     comment format `<hostname dari DHCP lease>|<interface WIFI|LAN>|<nama user>`.
  5. Rule baru disisipkan (place-before) TEPAT SEBELUM rule 'BLOCK-ELSE'
     -- SELALU jadi "rule kedua terakhir" (persis sebelum catch-all block),
     mempertahankan urutan: [...rule2, rule1 (baru), BLOCK-ELSE].

Logic INTI (cari BLOCK-ELSE, copy rule sebelumnya, place-before) diadaptasi
LANGSUNG dari script Python yang SUDAH JALAN & dipakai user secara manual
(`addFwFilter()`), sekarang diotomasi lewat 1 endpoint + form di frontend.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsStaffRole
from netmgmt.routeros_api_view import MikrotikConnectionError, get_routeros_connection

BLOCK_ELSE_COMMENT = 'BLOCK-ELSE'
VALID_INTERFACES = {'WIFI', 'LAN'}

# Field HASIL BACA rule (`.get()`) yang TIDAK BOLEH ikut disalin balik saat
# `.add()` -- baik krn read-only/stats (bytes/packets/dynamic/invalid,
# terisi RouterOS sendiri, BUKAN input valid), 'id' (identitas rule LAMA,
# rule baru dapat ID sendiri), ATAU sengaja DIGANTI (src-mac-address,
# comment -- lihat docstring modul).
_EXCLUDED_TEMPLATE_FIELDS = {'id', 'bytes', 'packets', 'invalid', 'dynamic', 'src-mac-address', 'comment'}


class FirewallGrantAccessView(APIView):
    """
    POST /api/v1/netmgmt/routeros/<host>/firewall/grant-access/
    Body: {"mac_address": "AA:BB:CC:DD:EE:FF", "hostname": "laptop-budi", "interface": "WIFI"|"LAN", "username": "Budi Santoso"}

    Otomasi PENUH alur "copy rule sebelum BLOCK-ELSE" (lihat docstring modul).
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request, host=None):
        mac_address = (request.data.get('mac_address') or '').strip()
        hostname = (request.data.get('hostname') or '').strip()
        interface = (request.data.get('interface') or '').strip().upper()
        username = (request.data.get('username') or '').strip()

        if not mac_address:
            return Response({'error': "'mac_address' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if not hostname:
            return Response({'error': "'hostname' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        if interface not in VALID_INTERFACES:
            return Response({'error': "'interface' wajib 'WIFI' atau 'LAN'."}, status=status.HTTP_400_BAD_REQUEST)
        if not username:
            return Response({'error': "'username' wajib diisi."}, status=status.HTTP_400_BAD_REQUEST)
        # Comment RouterOS pakai '|' sbg separator field -- kalau salah satu
        # nilai KEBETULAN mengandung '|', format comment jadi rusak/ambigu
        # saat di-parse balik nanti (mis. ditampilkan lagi di tabel Firewall
        # Filter) -- ditolak SEJAK AWAL drpd bikin data tidak konsisten.
        if '|' in hostname or '|' in username:
            return Response({'error': "'hostname'/'username' tidak boleh mengandung karakter '|' (dipakai sbg pemisah format comment)."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            connection, api = get_routeros_connection(host)
        except MikrotikConnectionError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            resource = api.get_resource('/ip/firewall/filter')
            try:
                all_rules = resource.get()
            except Exception as exc:  # noqa: BLE001
                return Response({'error': f'Gagal membaca daftar firewall filter dari router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

            block_else_index = None
            for i, rule in enumerate(all_rules):
                if rule.get('comment') == BLOCK_ELSE_COMMENT:
                    block_else_index = i
                    break

            if block_else_index is None:
                return Response(
                    {'error': f"Rule dgn comment '{BLOCK_ELSE_COMMENT}' tidak ditemukan di router ini -- tidak bisa tentukan posisi/template rule baru."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if block_else_index == 0:
                return Response(
                    {'error': f"Rule '{BLOCK_ELSE_COMMENT}' ada di posisi PALING ATAS -- tidak ada rule sebelumnya utk dijadikan template."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            block_else_rule = all_rules[block_else_index]
            template_rule = all_rules[block_else_index - 1]

            new_rule_data = {k: v for k, v in template_rule.items() if k not in _EXCLUDED_TEMPLATE_FIELDS}
            new_rule_data['src-mac-address'] = mac_address
            new_rule_data['comment'] = f'{hostname}|{interface}|{username}'
            new_rule_data['place-before'] = block_else_rule.get('id')

            try:
                resource.add(**new_rule_data)
            except Exception as exc:  # noqa: BLE001
                return Response({'error': f'Gagal menambah rule firewall ke router: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            connection.disconnect()

        return Response({
            'success': True,
            'message': 'Rule firewall berhasil ditambahkan.',
            'comment': new_rule_data['comment'],
            'template_used': {k: template_rule.get(k) for k in ('chain', 'action', 'protocol', 'out-interface') if k in template_rule},
        }, status=status.HTTP_200_OK)
