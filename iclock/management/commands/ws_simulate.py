"""
Simulasikan event WebSocket 'device_request'/'device_attlog' utk testing
tanpa perlu device fisik sungguhan terhubung.

Contoh:
    python manage.py ws_simulate --section device_request --sn 6422144200666
    python manage.py ws_simulate --section device_attlog --sn 6422144200666 --pin 8113009 --state I
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from iclock.ws_utils import wsinfo


class Command(BaseCommand):
    help = (
        "Simulasikan event WebSocket 'device_request' atau 'device_attlog' ke group 'iclock' "
        "(utk testing console window, update real-time Last Activity & Last Data di Active Device)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--section', default='device_request', choices=['device_request', 'device_attlog'])
        parser.add_argument('--sn', required=True, help='Serial Number Active Device')
        parser.add_argument('--devinfo', default='', help="Info tambahan device, string bebas (khusus --section=device_request)")
        parser.add_argument('--pin', default=None, help="PIN karyawan (khusus --section=device_attlog, opsional, cuma utk log)")
        parser.add_argument('--state', default='I', help="State transaksi, mis. 'I'/'O' (khusus --section=device_attlog, opsional, cuma utk log)")

    def handle(self, *args, **options):
        section = options['section']
        sn = options['sn']
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        if section == 'device_request':
            # Format PERSIS seperti yang dikirim protokol push device fisik:
            # {"sn": "...", "la": "YYYY-MM-DD HH:MM:SS", "devinfo": "..."}
            # -> di-pakai utk update tampilan kolom Last Activity secara real-time.
            message = {'sn': sn, 'la': now_str, 'devinfo': options['devinfo']}
        else:
            # 'device_attlog': ada transaksi/absensi baru dari device. Field
            # 'la' di sini dipakai LANGSUNG utk update tampilan kolom Last
            # Data secara real-time (bukan query ulang ke database) -- field
            # 'pin'/'state' cuma tambahan konteks utk console log, tidak
            # dipakai buat update tampilan apapun saat ini.
            message = {
                'sn': sn,
                'la': now_str,
                'pin': options['pin'] or '0000000',
                'state': options['state'],
            }

        self.stdout.write(f"Mengirim wsinfo('iclock', {section!r}, {message!r}) ...")
        wsinfo('iclock', section, message)
        self.stdout.write(self.style.SUCCESS(
            'Selesai. Kalau ada browser yang konek ke halaman Active Device (dengan console '
            'ditampilkan), pesan ini harusnya langsung muncul di sana.'
        ))
        if section == 'device_request':
            self.stdout.write(
                f"(Kalau SN '{sn}' ada di baris tabel Active Device yang sedang ditampilkan, "
                f"kolom Last Activity-nya juga ikut ter-update TAMPILANNYA secara real-time -- "
                f"bukan di database, cuma di layar.)"
            )
        else:
            self.stdout.write(
                f"(Kalau SN '{sn}' ada di baris tabel Active Device yang sedang ditampilkan, "
                f"kolom Last Data-nya juga ikut ter-update TAMPILANNYA secara real-time -- "
                f"bukan di database, cuma di layar.)"
            )
