import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# PENTING: get_asgi_application() HARUS dipanggil duluan, sebelum import
# apapun yang (secara transitif) menyentuh model Django -- ini persyaratan
# resmi Django Channels, supaya app registry Django sudah siap sebelum
# routing/consumers di-import di bawah.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

import iclock.routing  # noqa: E402
import netmgmt.routing  # noqa: E402
from iclock.ws_auth import JWTAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # AuthMiddlewareStack: populate scope['user'] dari session cookie Django
    # (dashboard Django sendiri) -- kalau TIDAK ada session valid,
    # JWTAuthMiddleware coba lagi via ?token= JWT (frontend Next.js,
    # cross-origin, tidak punya session cookie). Keduanya additive, tidak
    # saling mengganggu.
    #
    # iclock.routing & netmgmt.routing DIGABUNG jadi 1 URLRouter -- 2
    # endpoint WS terpisah (/ws/iclock & /ws/netmgmt), TAPI share middleware
    # auth yang SAMA (JWTAuthMiddleware/AuthMiddlewareStack cuma perlu
    # dipasang SEKALI, membungkus SEMUA url pattern WS, bukan per-app).
    'websocket': AuthMiddlewareStack(
        JWTAuthMiddleware(
            URLRouter(iclock.routing.websocket_urlpatterns + netmgmt.routing.websocket_urlpatterns)
        )
    ),
})
