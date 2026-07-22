"""
Middleware Channels: autentikasi WebSocket via JWT (SimpleJWT access
token) sbg FALLBACK dari session cookie -- dipakai frontend Next.js yang
autentikasinya cross-origin via Bearer token, TIDAK PUNYA session cookie
Django (beda dari dashboard Django sendiri, yang tetap pakai session
seperti biasa lewat AuthMiddlewareStack, TIDAK diubah/dipengaruhi
middleware ini).

Urutan di config/asgi.py PENTING:
    AuthMiddlewareStack(JWTAuthMiddleware(URLRouter(...)))
AuthMiddlewareStack jalan LEBIH DULU (isi scope['user'] dari session kalau
ada) -- JWTAuthMiddleware ini cuma AMBIL ALIH kalau user itu masih
AnonymousUser (session tidak ada/tidak valid) DAN ada `?token=` di query
string koneksi WebSocket-nya.

WebSocket API browser TIDAK BISA kirim header custom (Authorization: Bearer
...) seperti fetch() biasa -- makanya token dikirim lewat QUERY STRING URL
koneksi (ws://host/ws/iclock?token=xxx), satu-satunya cara praktis kirim
data tambahan saat membuka koneksi WebSocket dari browser.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user_from_jwt(token_str):
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    User = get_user_model()
    try:
        validated_token = AccessToken(token_str)
        user_id = validated_token['user_id']
        return User.objects.get(pk=user_id, is_active=True)
    except (TokenError, KeyError, User.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        current_user = scope.get('user')
        if current_user is None or not current_user.is_authenticated:
            query_string = scope.get('query_string', b'').decode()
            token = parse_qs(query_string).get('token', [None])[0]
            if token:
                scope['user'] = await _get_user_from_jwt(token)
        return await self.inner(scope, receive, send)
