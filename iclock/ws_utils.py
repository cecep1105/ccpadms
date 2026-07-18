"""
Helper buat broadcast message ke WebSocket client lewat Django Channels
group -- dipakai oleh kode mana pun (view, service, management command,
atau proses komunikasi device fisik yang terpisah di luar scaffold ini)
untuk kirim event real-time ke "console window" & update tampilan LastActivity
secara live di halaman Active Device.

Contoh pemakaian:
    from iclock.ws_utils import wsinfo
    wsinfo('iclock', 'request', {'sn': '6422144200666', 'la': '2026-07-14 09:57:16', 'devinfo': ''})
    wsinfo('iclock', 'attlog', {'sn': '6422144200666', 'pin': '8113009', 'state': 'I'})

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
    'attlog') supaya client (JS) tahu cara menampilkan/menangani event ini.

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
            'type': 'iclock.message',
            'section': section,
            'message': message,
        })
    except Exception as exc:  # noqa: BLE001
        # Redis mungkin belum jalan / connection error -- jangan sampai
        # nge-crash proses pemanggil cuma gara-gara broadcast WS gagal.
        logger.warning("wsinfo: gagal broadcast ke group %r (section=%r) -> %s", groupname, section, exc)
