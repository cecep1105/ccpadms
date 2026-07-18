"""
Exception khusus untuk service layer (accounts/services.py).

Dipakai bersama oleh dashboard (views.py, server-rendered) dan api (views.py,
JSON) supaya pesan error & kode error konsisten di kedua channel.
"""


class ServiceError(Exception):
    code = 'error'
    message = 'Terjadi kesalahan'

    def __init__(self, message: str | None = None, code: str | None = None):
        if message:
            self.message = message
        if code:
            self.code = code
        super().__init__(self.message)


class UserNotFoundInLDAPError(ServiceError):
    """Koneksi LDAP sukses, tapi username tidak ditemukan di direktori."""
    code = 'user_not_found'
    message = 'User belum ada'


class InvalidCredentialsError(ServiceError):
    code = 'invalid_credentials'
    message = 'Username atau password salah'


class NoLocalFallbackError(ServiceError):
    """Koneksi LDAP bermasalah, dan tidak ada user lokal sebagai fallback."""
    code = 'no_local_fallback'
    message = 'Koneksi LDAP sedang bermasalah dan user lokal tidak ditemukan. Hubungi administrator.'


class AccountInactiveError(ServiceError):
    code = 'account_inactive'
    message = 'Akun Anda dinonaktifkan. Hubungi administrator.'


class PermissionDeniedError(ServiceError):
    code = 'permission_denied'
    message = 'Anda tidak memiliki izin untuk melakukan aksi ini'


class ValidationErrorService(ServiceError):
    code = 'validation_error'
    message = 'Data tidak valid'


class UserAlreadyExistsError(ServiceError):
    code = 'user_already_exists'
    message = 'Username sudah digunakan'


class NotFoundError(ServiceError):
    code = 'not_found'
    message = 'Data tidak ditemukan'
