"""
WebSocket consumer untuk endpoint /ws/iclock.

Dipakai buat "console window" real-time di halaman Active Device -- browser
(client dashboard yang sudah login) konek ke sini utk NERIMA event yang
di-broadcast lewat wsinfo() (lihat iclock/ws_utils.py), mis. saat device
fisik melakukan request (heartbeat/polling, section='request') atau ada
event check-in/out (section='attlog').

Consumer ini didesain one-way (server -> client) khusus utk kebutuhan
console log; client tidak perlu (dan saat ini tidak diharapkan) mengirim
apapun ke consumer ini.
"""
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger('iclock')

GROUP_ICLOCK = 'iclock'


class IclockConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        # Guest (belum login) ditolak -- cuma user dashboard yang sudah
        # login (session cookie sama dengan dashboard, lewat AuthMiddlewareStack
        # di config/asgi.py) yang boleh konek & join group 'iclock'.
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(GROUP_ICLOCK, self.channel_name)
        await self.accept()
        logger.info("WS iclock: user '%s' terhubung (channel=%s)", user.username, self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_ICLOCK, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # One-way (server -> client) -- pesan dari client sengaja diabaikan.
        pass

    # Dipanggil channel layer saat ada group_send dengan {'type': 'iclock.message', ...}
    # (lihat wsinfo() di iclock/ws_utils.py). Django Channels otomatis translate
    # 'iclock.message' -> nama method 'iclock_message' (titik jadi underscore).
    async def iclock_message(self, event):
        await self.send(text_data=json.dumps({
            'section': event.get('section'),
            'message': event.get('message'),
        }))
