from rest_framework.permissions import BasePermission


class IsStaffRole(BasePermission):
    """Izinkan is_staff atau is_superuser (setara akses dashboard admin)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class IsSuperUserRole(BasePermission):
    """Khusus aksi sensitif: hapus user, ubah role admin."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


def HasFeaturePermission(*perm_codenames):
    """
    Factory kelas permission DRF -- padanan
    `accounts.permissions.permission_or_staff_required` (dipakai view
    dashboard Django) versi API: izinkan staff/superuser SEPERTI BIASA,
    TAPI juga buka akses utk user non-staff yang SUDAH DIBERI IZIN
    eksplisit (lewat halaman "Kelola Izin User" dashboard Django, model
    dummy `iclock.FeaturePermission`) via salah satu permission di
    `perm_codenames` (mis. 'iclock.can_transfer_finger').

    Contoh: permission_classes = [IsAuthenticated, HasFeaturePermission('iclock.can_transfer_finger')]
    """

    class _HasFeaturePermission(BasePermission):
        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            return bool(user.is_staff or user.is_superuser or any(user.has_perm(p) for p in perm_codenames))

    return _HasFeaturePermission
