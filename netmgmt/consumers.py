"""
WebSocket consumer untuk endpoint /ws/netmgmt.

Dipakai buat update real-time halaman netmgmt (mis. Mail Queue -- lihat
netmgmt/tasks.py::check_mailq, dijadwalkan Celery Beat tiap 1 menit,
broadcast isi mailq terbaru dgn section='mailq') -- browser (client
dashboard yang sudah login) konek ke sini utk NERIMA event, TIDAK perlu
refresh halaman manual.

STRUKTUR PERSIS SAMA dgn iclock/consumers.py::IclockConsumer (BUKAN
duplikasi tanpa alasan -- 2 use-case ini sengaja dipisah GROUP-nya
supaya broadcast iClock (device fisik, volume tinggi) TIDAK bercampur
dgn broadcast netmgmt (mailq dkk, volume rendah) ke client yang cuma
butuh salah satu, biar client tidak perlu terima & filter event yang
tidak relevan dgn halaman yang lagi dibuka).
"""
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger('netmgmt')

GROUP_NETMGMT = 'netmgmt'


class NetmgmtConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            logger.warning(
                "WS netmgmt: koneksi DITOLAK (user tidak terautentikasi -- "
                "cek token JWT di query string ?token= atau session cookie). "
                "query_string=%s",
                self.scope.get('query_string', b'').decode(errors='replace'),
            )
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(GROUP_NETMGMT, self.channel_name)
        await self.accept()
        logger.info("WS netmgmt: user '%s' terhubung (channel=%s)", user.username, self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_NETMGMT, self.channel_name)
        logger.info("WS netmgmt: koneksi terputus (channel=%s, close_code=%s)", self.channel_name, close_code)

    async def receive(self, text_data=None, bytes_data=None):
        # One-way (server -> client) -- pesan dari client sengaja diabaikan.
        pass

    # Dipanggil channel layer saat ada group_send dengan {'type': 'netmgmt.message', ...}
    # (lihat wsinfo() di iclock/ws_utils.py -- fungsi GENERIK, dipakai ulang
    # dari sini juga, bukan cuma iclock, lihat netmgmt/tasks.py). Django
    # Channels otomatis translate 'netmgmt.message' -> nama method
    # 'netmgmt_message' (titik jadi underscore).
    async def netmgmt_message(self, event):
        await self.send(text_data=json.dumps({
            'section': event.get('section'),
            'message': event.get('message'),
        }))
