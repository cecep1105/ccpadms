"""
Service layer.

Semua business logic ditaruh di sini (bukan di views), supaya bisa dipakai
ulang oleh:
  - dashboard/views.py  (server-rendered, buat admin & user biasa)
  - api/views.py        (JSON/REST, dikonsumsi frontend Nuxt)

Ini yang dimaksud "fungsi-fungsi yang nantinya bisa dijadikan API": tinggal
bungkus fungsi di sini dengan serializer + permission check di api/views.py.
"""
import logging
import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, models

from .exceptions import (
    AccountInactiveError,
    InvalidCredentialsError,
    NoLocalFallbackError,
    NotFoundError,
    PermissionDeniedError,
    UserAlreadyExistsError,
    UserNotFoundInLDAPError,
    ValidationErrorService,
)
from .ldap_client import LDAPClient, LDAPConnectivityError

logger = logging.getLogger('accounts')

User = get_user_model()


# ---------------------------------------------------------------------------
# AUTENTIKASI
# ---------------------------------------------------------------------------
def authenticate_user(username: str, password: str):
    """
    Alur login sesuai spesifikasi:

    0. Kalau username sudah dikenal sebagai akun LOCAL murni (auth_source='local',
       misal superuser hasil `createsuperuser` atau user yang sengaja dibuat admin
       lewat dashboard) -> autentikasi LANGSUNG ke password lokal, LDAP di-skip
       total. Akun local by definition memang tidak terdaftar di LDAP, jadi tidak
       ada gunanya dicek ke sana -- ini juga menjamin akun admin/bootstrap selalu
       bisa login walau server LDAP sedang menyala & reachable.
    1. Kalau bukan kasus di atas (username belum dikenal lokal, atau sudah pernah
       sinkron dari LDAP sebelumnya / auth_source='ldap') -> cek LDAP dulu.
       a. Koneksi LDAP sukses & username ADA di LDAP:
          - password benar  -> sinkron/buat user lokal, login pakai itu
          - password salah  -> InvalidCredentialsError
       b. Koneksi LDAP sukses & username TIDAK ADA di LDAP:
          -> UserNotFoundInLDAPError ("user belum ada")
    2. Koneksi LDAP ERROR (server down/timeout/dll):
       -> fallback cek user LOCAL. Kalau ada & password cocok -> login pakai lokal.
          Kalau tidak ada / password salah -> error yang sesuai.

    Return: instance User kalau sukses.
    Raise : salah satu subclass ServiceError kalau gagal.
    """
    if not username or not password:
        raise ValidationErrorService('Username dan password wajib diisi')

    local_only_user = User.objects.filter(
        username=username, auth_source=User.AuthSource.LOCAL,
    ).first()
    if local_only_user:
        return _authenticate_local_user(local_only_user, password)

    client = LDAPClient()
    ldap_connection_ok = True
    ldap_found = None

    try:
        ldap_found = client.find_user(username)
    except LDAPConnectivityError as exc:
        logger.warning('LDAP search connection error for user=%s: %s', username, exc)
        ldap_connection_ok = False

    if ldap_connection_ok:
        if ldap_found is None:
            raise UserNotFoundInLDAPError()

        user_dn, entry = ldap_found
        bind_ok = False
        try:
            bind_ok = client.authenticate(user_dn, password)
        except LDAPConnectivityError as exc:
            logger.warning('LDAP bind connection error for user=%s: %s', username, exc)
            ldap_connection_ok = False

        if ldap_connection_ok:
            if not bind_ok:
                raise InvalidCredentialsError()
            return _sync_local_user_from_ldap(username, entry)

    # --- Sampai sini berarti koneksi LDAP bermasalah -> fallback ke lokal ---
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        raise NoLocalFallbackError()

    return _authenticate_local_user(user, password)


def _authenticate_local_user(user, password):
    if not user.is_active:
        raise AccountInactiveError()
    if not user.has_usable_password() or not user.check_password(password):
        raise InvalidCredentialsError()
    return user


def _sync_local_user_from_ldap(username: str, entry):
    """Ambil / buat user lokal yang merepresentasikan user LDAP yang baru berhasil login."""
    from django.conf import settings

    attr_map = settings.AUTH_LDAP_USER_ATTR_MAP

    def get_attr(name):
        ldap_key = attr_map.get(name)
        if not ldap_key:
            return ''
        value = getattr(entry, ldap_key, None)
        if value is None:
            return ''
        try:
            return str(value.value) if hasattr(value, 'value') else str(value)
        except Exception:  # noqa: BLE001
            return ''

    email = get_attr('email')
    first_name = get_attr('first_name')
    last_name = get_attr('last_name')

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
            'auth_source': User.AuthSource.LDAP,
        },
    )

    if created:
        user.set_unusable_password()
        user.save()
        logger.info("User lokal baru dibuat dari LDAP: '%s'", username)
    else:
        changed = False
        if user.auth_source != User.AuthSource.LDAP:
            user.auth_source = User.AuthSource.LDAP
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if changed:
            user.save()

    if not user.is_active:
        raise AccountInactiveError()

    return user


# ---------------------------------------------------------------------------
# MANAJEMEN USER (dipakai admin dashboard & API admin)
# ---------------------------------------------------------------------------
def _require_staff(actor):
    if not (actor.is_staff or actor.is_superuser):
        raise PermissionDeniedError('Hanya admin yang dapat melakukan aksi ini')


def _require_superuser(actor):
    if not actor.is_superuser:
        raise PermissionDeniedError('Aksi ini hanya untuk super admin')


def list_users(search: str = ''):
    # Akun "mobile-only" (dibuat OTOMATIS oleh login PIN, accounts/mobile_backend.py)
    # SENGAJA dikecualikan dari daftar ini -- mereka bukan akun yang
    # dikelola admin secara manual (tidak ada gunanya muncul di
    # Manajemen User staff biasa, cuma bikin daftar penuh & membingungkan).
    # Tetap ADA di database (dibutuhkan Django utk session/auth login
    # mobile via PIN), cuma disembunyikan dari tampilan admin ini.
    qs = User.objects.select_related('EmpID').filter(is_mobile_only=False).order_by('username')
    if search:
        qs = qs.filter(
            models.Q(username__icontains=search)
            | models.Q(email__icontains=search)
            | models.Q(first_name__icontains=search)
            | models.Q(last_name__icontains=search)
        )
    return qs


def paginate_users(search: str = '', page: int = 1, page_size: int = 10):
    qs = list_users(search)
    paginator = Paginator(qs, page_size)
    return paginator.get_page(page)


def get_user_or_raise(user_id):
    user = User.objects.filter(pk=user_id).first()
    if not user:
        raise NotFoundError('User tidak ditemukan')
    return user


def create_local_user(actor, *, username, password, email='', first_name='', last_name='', is_staff=False, emp_id=None):
    """Admin bikin user LOCAL baru (bukan LDAP). `emp_id`: instance Employee (opsional) atau None."""
    _require_staff(actor)
    if is_staff:
        _require_superuser(actor)  # hanya super admin boleh membuat akun admin baru

    username = (username or '').strip()
    if not username:
        raise ValidationErrorService('Username wajib diisi')
    if User.objects.filter(username=username).exists():
        raise UserAlreadyExistsError()

    try:
        validate_password(password)
    except DjangoValidationError as exc:
        raise ValidationErrorService('; '.join(exc.messages))

    user = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        auth_source=User.AuthSource.LOCAL,
        is_staff=is_staff,
        must_change_password=True,
        EmpID=emp_id,
    )
    user.set_password(password)
    try:
        user.save()
    except IntegrityError:
        raise UserAlreadyExistsError()

    logger.info("Admin '%s' membuat user lokal baru '%s'", actor.username, username)
    return user


def update_user_by_admin(actor, target_id, **fields):
    _require_staff(actor)
    target = get_user_or_raise(target_id)
    allowed = {'email', 'first_name', 'last_name', 'phone_number', 'department', 'title', 'EmpID'}
    for key, value in fields.items():
        if key in allowed:
            setattr(target, key, value)
    target.save()
    return target


def delete_user(actor, target_id):
    _require_superuser(actor)
    target = get_user_or_raise(target_id)
    if target.pk == actor.pk:
        raise ValidationErrorService('Tidak dapat menghapus akun sendiri')
    username = target.username
    target.delete()
    logger.info("Super admin '%s' menghapus user '%s'", actor.username, username)


def reset_password(actor, target_id, new_password=None):
    """Reset password user LOCAL. User LDAP tidak bisa direset dari sini."""
    _require_staff(actor)
    target = get_user_or_raise(target_id)

    if target.auth_source == User.AuthSource.LDAP:
        raise ValidationErrorService('Password user LDAP dikelola oleh server LDAP, bukan dari aplikasi ini')

    generated_password = None
    if not new_password:
        alphabet = string.ascii_letters + string.digits + '!@#$%'
        new_password = ''.join(secrets.choice(alphabet) for _ in range(12))
        generated_password = new_password
    else:
        try:
            validate_password(new_password, user=target)
        except DjangoValidationError as exc:
            raise ValidationErrorService('; '.join(exc.messages))

    target.set_password(new_password)
    target.must_change_password = True
    target.save(update_fields=['password', 'must_change_password'])
    logger.info("Admin '%s' me-reset password user '%s'", actor.username, target.username)
    return generated_password


def toggle_active(actor, target_id):
    _require_staff(actor)
    target = get_user_or_raise(target_id)
    if target.pk == actor.pk:
        raise ValidationErrorService('Tidak dapat mengubah status akun sendiri')
    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])
    return target


def set_staff_role(actor, target_id, is_staff: bool):
    _require_superuser(actor)
    target = get_user_or_raise(target_id)
    if target.pk == actor.pk:
        raise ValidationErrorService('Tidak dapat mengubah role sendiri')
    target.is_staff = is_staff
    target.save(update_fields=['is_staff'])
    return target


# ---------------------------------------------------------------------------
# PROFIL (self-service, untuk user non-admin maupun admin)
# ---------------------------------------------------------------------------
PROFILE_EDITABLE_FIELDS = {'first_name', 'last_name', 'email', 'phone_number', 'department', 'title'}


def update_profile(user, **fields):
    for key, value in fields.items():
        if key in PROFILE_EDITABLE_FIELDS:
            setattr(user, key, value)
    user.save()
    return user


def change_own_password(user, old_password, new_password):
    if user.auth_source == User.AuthSource.LDAP:
        raise ValidationErrorService('Password dikelola oleh LDAP, tidak bisa diubah dari sini')
    if not user.check_password(old_password):
        raise ValidationErrorService('Password lama salah')
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ValidationErrorService('; '.join(exc.messages))
    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=['password', 'must_change_password'])
    return user
