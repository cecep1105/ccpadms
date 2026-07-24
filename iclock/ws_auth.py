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

import logging

logger = logging.getLogger('iclock')


@database_sync_to_async
def _get_user_from_jwt(token_str):
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    User = get_user_model()
    try:
        validated_token = AccessToken(token_str)
        user_id = validated_token['user_id']
        user = User.objects.get(pk=user_id, is_active=True)
        logger.info("WS JWTAuthMiddleware: token valid, user='%s' (id=%s)", user.username, user_id)
        return user
    except TokenError as exc:
        # PALING SERING: token EXPIRED (access token cuma hidup 30 menit
        # default -- lihat JWT_ACCESS_TOKEN_LIFETIME_MINUTES) atau
        # signature tidak cocok (SECRET_KEY beda antara saat token
        # di-generate vs saat divalidasi -- WAJIB SAMA persis, cek env
        # SECRET_KEY kalau baru ganti/rebuild container).
        logger.warning("WS JWTAuthMiddleware: token TIDAK VALID (%s): %s", type(exc).__name__, exc)
        return AnonymousUser()
    except KeyError:
        logger.warning("WS JWTAuthMiddleware: token valid tapi tidak ada klaim 'user_id' di dalamnya.")
        return AnonymousUser()
    except User.DoesNotExist:
        logger.warning("WS JWTAuthMiddleware: user_id=%s dari token tidak ditemukan/tidak aktif di database.", user_id)
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
            else:
                # PENTING: kalau baris ini yang muncul di log, artinya
                # request WEBSOCKET-nya SAMPAI ke Django (middleware ini
                # jalan), TAPI TIDAK ADA ?token= sama sekali di URL koneksi
                # -- kemungkinan besar penyebabnya di SISI FRONTEND
                # (Next.js): NEXT_PUBLIC_WS_BASE_URL salah/kosong, session
                # NextAuth belum siap (accessToken undefined) saat mencoba
                # konek, atau useIclockWsMessage/IclockWsProvider tidak
                # ke-mount di halaman itu.
                logger.warning(
                    "WS JWTAuthMiddleware: TIDAK ADA token JWT di query string (?token=) & TIDAK ADA "
                    "session cookie -- request ini akan DITOLAK sbg AnonymousUser. Cek sisi Next.js: "
                    "NEXT_PUBLIC_WS_BASE_URL & session.accessToken."
                )
        return await self.inner(scope, receive, send)