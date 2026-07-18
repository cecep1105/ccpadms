"""
Tool diagnostik untuk troubleshoot Attendance Recap yang jam-nya kosong.

Jalankan langsung di server Anda (yang konek ke MySQL asli):
    python manage.py recap_debug
    python manage.py recap_debug --pin 8113009
    python manage.py recap_debug --date 2026-07-10

Akan menampilkan beberapa transaksi mentah (TTime, State, Function) apa
adanya, termasuk TIPE PYTHON persis dari tiap field -- supaya kita bisa
pastikan apakah datanya cocok dugaan (State='0'/'1' string, TTime datetime
proper) atau ada sesuatu yang beda dari yang diasumsikan model.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from iclock.models import transaction
from iclock.views import _normalize_state, _to_local_time, _is_in_state


class Command(BaseCommand):
    help = 'Debug data mentah transaction (State/TTime) untuk troubleshoot Attendance Recap.'

    def add_arguments(self, parser):
        parser.add_argument('--pin', default=None, help='Filter ke PIN tertentu')
        parser.add_argument('--date', default=None, help='Filter ke tanggal tertentu (YYYY-MM-DD)')
        parser.add_argument('--limit', type=int, default=10, help='Jumlah baris yang ditampilkan (default 10)')

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('--- Setting terkait timezone ---'))
        self.stdout.write(f'USE_TZ          : {settings.USE_TZ}')
        self.stdout.write(f'TIME_ZONE       : {settings.TIME_ZONE}')
        self.stdout.write(f'DEVICEFUNCTION  : {getattr(settings, "DEVICEFUNCTION", "(tidak ada)")}')
        self.stdout.write(f'ATTENDANCE_IN_STATE_CODES : {getattr(settings, "ATTENDANCE_IN_STATE_CODES", ["0", "I"])}')
        self.stdout.write('')

        qs = transaction.objects.select_related('UserID').order_by('-TTime')
        if options['pin']:
            qs = qs.filter(UserID__PIN=options['pin'])
        if options['date']:
            qs = qs.filter(TTime__date=options['date'])
        qs = qs[:options['limit']]

        rows = list(qs)
        if not rows:
            self.stdout.write(self.style.ERROR('Tidak ada transaksi yang cocok dengan filter ini.'))
            return

        self.stdout.write(self.style.NOTICE(f'--- {len(rows)} transaksi terakhir (mentah, apa adanya) ---'))
        for t in rows:
            self.stdout.write('')
            self.stdout.write(f'PIN            : {t.UserID.PIN}')
            self.stdout.write(f'TTime (raw)    : {t.TTime!r}')
            self.stdout.write(f'  tipe Python  : {type(t.TTime).__name__}')
            self.stdout.write(f'  is_aware     : {timezone.is_aware(t.TTime) if t.TTime else "N/A"}')
            local = _to_local_time(t.TTime)
            self.stdout.write(f'  setelah _to_local_time(): {local!r}')
            self.stdout.write(f'State (raw)    : {t.State!r}')
            self.stdout.write(f'  tipe Python  : {type(t.State).__name__}')
            normalized = _normalize_state(t.State)
            classified = 'IN' if _is_in_state(t.State) else 'OUT'
            self.stdout.write(f'  ternormalisasi: {normalized!r} -> diklasifikasi sebagai {classified}')
            self.stdout.write(f'Function       : {t.Function!r}')

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            'Cek terutama: (1) apakah TTime is_aware konsisten dgn USE_TZ Anda, '
            '(2) apakah "setelah _to_local_time()" jamnya masuk akal (tidak geser aneh), '
            '(3) apakah klasifikasi IN/OUT sudah sesuai ekspektasi.'
        ))
