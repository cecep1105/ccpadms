"""
API untuk dikonsumsi frontend Nuxt. Semua logic bisnis ada di
accounts/services.py — file ini hanya menjembatani HTTP <-> service.
"""
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import services
from accounts.exceptions import ServiceError

from .permissions import IsStaffRole, IsSuperUserRole
from .serializers import (
    AdminResetPasswordSerializer,
    ChangePasswordSerializer,
    CreateLocalUserSerializer,
    LoginSerializer,
    ProfileUpdateSerializer,
    UserSerializer,
    UserUpdateByAdminSerializer,
)

User = get_user_model()

ERROR_STATUS_MAP = {
    'user_not_found': status.HTTP_404_NOT_FOUND,
    'not_found': status.HTTP_404_NOT_FOUND,
    'invalid_credentials': status.HTTP_401_UNAUTHORIZED,
    'account_inactive': status.HTTP_403_FORBIDDEN,
    'no_local_fallback': status.HTTP_503_SERVICE_UNAVAILABLE,
    'permission_denied': status.HTTP_403_FORBIDDEN,
    'validation_error': status.HTTP_400_BAD_REQUEST,
    'user_already_exists': status.HTTP_409_CONFLICT,
}


def service_error_response(exc: ServiceError) -> Response:
    http_status = ERROR_STATUS_MAP.get(exc.code, status.HTTP_400_BAD_REQUEST)
    return Response({'code': exc.code, 'message': exc.message}, status=http_status)


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
class LoginView(APIView):
    """POST /api/v1/auth/login/ -> {access, refresh, user}"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.authenticate_user(
                serializer.validated_data['username'], serializer.validated_data['password'],
            )
        except ServiceError as exc:
            return service_error_response(exc)

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })


class LogoutView(APIView):
    """POST /api/v1/auth/logout/  body: {refresh}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:  # noqa: BLE001
                pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


# ---------------------------------------------------------------------------
# PROFIL (self-service)
# ---------------------------------------------------------------------------
class MeView(APIView):
    """GET/PATCH /api/v1/me/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = services.update_profile(request.user, **serializer.validated_data)
        return Response(UserSerializer(user).data)


class ChangeOwnPasswordView(APIView):
    """POST /api/v1/me/change-password/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.change_own_password(
                request.user,
                serializer.validated_data['old_password'],
                serializer.validated_data['new_password'],
            )
        except ServiceError as exc:
            return service_error_response(exc)
        return Response({'detail': 'Password berhasil diubah'})


# ---------------------------------------------------------------------------
# ADMIN: manajemen user
# ---------------------------------------------------------------------------
class UserViewSet(viewsets.ViewSet):
    """
    Admin-only. Di-mount manual di api/urls.py (bukan router) supaya
    action mapping-nya eksplisit.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]

    # Field yang boleh dipakai utk sort (?ordering=field atau ?ordering=-field
    # utk descending) -- whitelist eksplisit (BUKAN '__all__' spt viewset
    # lain) krn ViewSet ini custom/manual, tidak lewat DRF OrderingFilter.
    ORDERING_FIELDS = {'username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff', 'department', 'created_at'}

    def list(self, request):
        search = request.query_params.get('q', '')
        page = request.query_params.get('page', 1)
        page_size = int(request.query_params.get('page_size', 20))
        qs = services.list_users(search)

        ordering = request.query_params.get('ordering', '')
        field = ordering.lstrip('-')
        if field in self.ORDERING_FIELDS:
            qs = qs.order_by(ordering)

        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)
        return Response({
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'current_page': page_obj.number,
            'results': UserSerializer(page_obj.object_list, many=True).data,
        })

    def retrieve(self, request, pk=None):
        try:
            target = services.get_user_or_raise(pk)
        except ServiceError as exc:
            return service_error_response(exc)
        return Response(UserSerializer(target).data)

    def create(self, request):
        serializer = CreateLocalUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.create_local_user(request.user, **serializer.validated_data)
        except ServiceError as exc:
            return service_error_response(exc)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        serializer = UserUpdateByAdminSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.update_user_by_admin(request.user, pk, **serializer.validated_data)
        except ServiceError as exc:
            return service_error_response(exc)
        return Response(UserSerializer(user).data)

    def destroy(self, request, pk=None):
        try:
            services.delete_user(request.user, pk)
        except ServiceError as exc:
            return service_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            generated = services.reset_password(
                request.user, pk, serializer.validated_data.get('new_password') or None,
            )
        except ServiceError as exc:
            return service_error_response(exc)
        payload = {'detail': 'Password berhasil direset'}
        if generated:
            payload['generated_password'] = generated
        return Response(payload)

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        try:
            user = services.toggle_active(request.user, pk)
        except ServiceError as exc:
            return service_error_response(exc)
        return Response(UserSerializer(user).data)

    @action(
        detail=True, methods=['post'], url_path='set-staff',
        permission_classes=[IsAuthenticated, IsSuperUserRole],
    )
    def set_staff(self, request, pk=None):
        is_staff = bool(request.data.get('is_staff'))
        try:
            user = services.set_staff_role(request.user, pk, is_staff)
        except ServiceError as exc:
            return service_error_response(exc)
        return Response(UserSerializer(user).data)
