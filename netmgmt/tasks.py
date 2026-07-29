"""
Celery task utk fitur netmgmt -- dijalankan BERKALA lewat Celery Beat
(BUKAN dipanggil langsung dari view spt task face recognition di
mattendance/tasks.py) -- lihat CELERY_BEAT_SCHEDULE di config/settings.py
utk jadwalnya (`check_mailq` tiap 1 menit).

JALANKAN CELERY BEAT TERPISAH (proses BEDA dari worker biasa):
    celery -A config beat --loglevel=info

(Worker biasa TETAP perlu jalan jg spt biasa utk EKSEKUSI task yg
dijadwalkan Beat -- Beat cuma "penjadwal", TIDAK eksekusi task sendiri:
    celery -A config worker --loglevel=info --pool=solo
)
"""
import logging

from celery import shared_task

from iclock.ws_utils import wsinfo  # GENERIK (terima groupname sbg parameter), dipakai ulang dari iclock -- lihat catatan di netmgmt/consumers.py
from netmgmt.zentyal_mail_view import ZentyalMailAPIError, call_flask_mail_api

logger = logging.getLogger('netmgmt')

GROUP_NETMGMT = 'netmgmt'


@shared_task(ignore_result=True)
def check_mailq():
    """
    Cek isi mailq Zentyal (via Flask API) & broadcast ke SEMUA client
    WebSocket yang lagi buka halaman Mail Queue (group 'netmgmt',
    section='mailq') -- supaya tabel di halaman itu ter-update TANPA
    perlu refresh manual, konsisten dgn interval Celery Beat (default
    1 menit, lihat CELERY_BEAT_SCHEDULE).

    SENGAJA TIDAK raise exception ke caller (Celery Beat) -- kalau Flask
    API lagi down/network bermasalah, task ini CUKUP log warning &
    selesai TANPA error, supaya Celery Beat TETAP lanjut jadwal berikutnya
    scr normal (task yg gagal karena exception BISA bikin Celery Beat
    catat sbg failure berulang, tidak perlu utk kasus "server mail lagi
    down sesaat" yg sifatnya sementara & self-recovering).
    """
    try:
        data = call_flask_mail_api('GET', '/mailq')
    except ZentyalMailAPIError as exc:
        logger.warning('check_mailq: gagal ambil data dari Zentyal Mail API -- %s', exc)
        return

    result = data.get('result', [])
    wsinfo(GROUP_NETMGMT, 'mailq', {
        'count': len(result),
        'active_count': sum(1 for m in result if m.get('status') == 'active'),
        'deferred_count': sum(1 for m in result if m.get('status') == 'deferred'),
        'result': result,
    })
    logger.info('check_mailq: broadcast %d pesan queue ke group netmgmt.', len(result))
