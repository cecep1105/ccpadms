"""
Helper buat broadcast message ke WebSocket client lewat Django Channels
group -- dipakai oleh kode mana pun (view, service, management command,
Celery task, atau proses komunikasi device fisik yang terpisah di luar
scaffold ini) untuk kirim event real-time ke client yang konek ke group
WebSocket terkait (mis. "console window" iClock, ATAU update tabel Mail
Queue di netmgmt -- lihat netmgmt/tasks.py::check_mailq).

Contoh pemakaian:
    from iclock.ws_utils import wsinfo
    wsinfo('iclock', 'request', {'sn': '6422144200666', 'la': '2026-07-14 09:57:16', 'devinfo': ''})
    wsinfo('iclock', 'attlog', {'sn': '6422144200666', 'pin': '8113009', 'state': 'I'})
    wsinfo('netmgmt', 'mailq', {'count': 5, 'result': [...]})

PENTING (koreksi dari versi sebelumnya): fungsi ini TIDAK menyentuh database
sama sekali. Field LastActivity di database `iclock` sudah otomatis
ter-update oleh proses/protokol push device yang terpisah (di luar scaffold
ini, dikelola sendiri oleh Anda) -- wsinfo() di sini murni membroadcast
pesan ke browser yang lagi buka halaman Active Device, supaya TAMPILANNYA
(bukan datanya) terasa real-time tanpa perlu refresh halaman. Update
tampilan LastActivity di kolom tabel dilakukan lewat JS di
templates/iclock/active_device_list.html, berdasarkan pesan yang diterima
di sini -- bukan lewat query ulang ke database.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger('iclock')

GROUP_ICLOCK = 'iclock'


def wsinfo(groupname, section, message):
    """
    Broadcast `message` (dict, harus JSON-serializable) ke semua WebSocket
    client yang join di `groupname`, dengan label `section` (mis. 'request',
    'attlog', 'mailq') supaya client (JS) tahu cara menampilkan/menangani
    event ini.

    Kalau channel layer belum terkonfigurasi atau Redis lagi bermasalah,
    fungsi ini diam-diam mencatat warning ke log dan TIDAK raise exception --
    supaya proses pemanggil (mis. endpoint yang dipanggil device fisik)
    tidak ikut gagal cuma gara-gara sisi WebSocket/Redis-nya bermasalah.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("wsinfo: channel layer belum terkonfigurasi, broadcast section=%r dilewati.", section)
        return

    try:
        async_to_sync(channel_layer.group_send)(groupname, {
            # PENTING -- SEBELUMNYA baris ini hardcode 'iclock.message',
            # BUKAN diturunkan dari `groupname` -- akibatnya broadcast ke
            # group LAIN (mis. 'netmgmt') TETAP mencoba panggil handler
            # `iclock_message` (yang cuma ada di IclockConsumer), consumer
            # group lain (mis. NetmgmtConsumer, cuma py `netmgmt_message`)
            # jadi ValueError "No handler for message type iclock.message"
            # -- KETAHUAN 2x lewat testing & laporan produksi langsung
            # (koneksi /ws/netmgmt putus-nyambung PERSIS tiap kali
            # check_mailq() jalan & panggil wsinfo(), krn exception ini
            # bikin consumer CRASH tengah jalan). Sekarang `type`
            # DITURUNKAN dari `groupname` (Channels ganti titik jadi
            # underscore utk cari nama method consumer) -- groupname=
            # 'iclock' -> handler `iclock_message` (PERILAKU SAMA PERSIS
            # spt sebelumnya utk caller lama, tidak berubah), groupname=
            # 'netmgmt' -> handler `netmgmt_message` (BARU, benar).
            'type': f'{groupname}.message',
            'section': section,
            'message': message,
        })
    except Exception as exc:  # noqa: BLE001
        # Redis mungkin belum jalan / connection error -- jangan sampai
        # nge-crash proses pemanggil cuma gara-gara broadcast WS gagal.
        logger.warning("wsinfo: gagal broadcast ke group %r (section=%r) -> %s", groupname, section, exc)