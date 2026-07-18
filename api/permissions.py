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
