from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from .exceptions import ServiceError
from .services import authenticate_user


class LDAPOrLocalBackend(BaseBackend):
    """
    Backend tunggal yang membungkus accounts.services.authenticate_user().

    Dipakai oleh django.contrib.auth.authenticate()/login() secara umum.
    Untuk pesan error yang lebih spesifik (user belum ada / invalid
    credentials / ldap down dll), panggil accounts.services.authenticate_user()
    langsung dari view (lihat accounts/views.py & api/views.py) supaya bisa
    menangkap ServiceError-nya.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        try:
            return authenticate_user(username, password)
        except ServiceError:
            return None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None
