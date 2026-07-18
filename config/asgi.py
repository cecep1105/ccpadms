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

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # AuthMiddlewareStack: populate scope['user'] dari session cookie Django
    # yang sama dipakai dashboard -- jadi client browser yang belum login
    # (guest) otomatis ke-anggap AnonymousUser, ditolak di consumer.
    'websocket': AuthMiddlewareStack(
        URLRouter(iclock.routing.websocket_urlpatterns)
    ),
})
