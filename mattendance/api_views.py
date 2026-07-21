"""
API untuk app 'mattendance', dikonsumsi frontend Nuxt (termasuk kemungkinan
app mobile). Logic inti (geofence, QR, kode fungsi, task Celery face
recognition) REUSE fungsi yang SAMA dgn dashboard web (mattendance/
geofence.py, qr_utils.py, function_utils.py, tasks.py) -- endpoint di sini
cuma menjembatani HTTP <-> fungsi-fungsi itu, pola sama dgn iclock/api_views.py.

Login mobile (PIN Employee) BEDA dari login JWT biasa (api/views.py::LoginView,
yg pakai username/password) -- endpoint terpisah di sini krn backend-nya beda
(accounts.mobile_backend.EmployeeMobileBackend, kwargs pin/mobile_password).
"""
from celery.exceptions import TimeoutError as CeleryTimeoutError
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.mobile_backend import mobile_password_needs_change
from api.permissions import IsStaffRole

from .function_utils import determine_function_code
from .geofence import find_all_matching_pools_by_polygon, find_matching_pool_by_polygon
from .models import AttendanceLog, FaceProfile
from .qr_utils import get_poolcode_from_qr
from .services import maybe_consolidate_to_iclock
from .serializers import (
    AttendanceLogSerializer,
    CheckinMealSerializer,
    CheckinSerializer,
    FaceEnrollSerializer,
    FaceProfileAdminSerializer,
    MobileChangePasswordSerializer,
    MobileLoginSerializer,
)
from .tasks import extract_face_encoding_task, verify_face_task

FACE_TASK_TIMEOUT_SECONDS = 15


def _get_employee_or_none(user):
    return user.EmpID if user.EmpID_id else None


def _get_display_name(user) -> str:
    if user.EmpID_id and user.EmpID.EName:
        return user.EmpID.EName.strip()
    return user.get_full_name() or user.username


class MobilePasswordUpToDate(BasePermission):
    """
    Setara `accounts.middleware.MobileAccessMiddleware` versi web, TAPI utk
    API (stateless/JWT, tidak ada session) -- dicek ULANG di SETIAP request
    ke endpoint yang butuh password sudah bukan default lagi (checkin, meal,
    enrollment). Endpoint auth/profil/ganti-password sendiri TIDAK memakai
    permission ini (harus tetap bisa diakses walau password masih default,
    supaya user bisa menggantinya).
    """
    message = 'Password Anda masih default -- wajib diganti dulu (POST /auth/change-password/) sebelum melanjutkan.'

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not getattr(user, 'is_mobile_only', False):
            return True  # tidak relevan sama sekali utk user reguler (staff/LDAP/local)
        emp = _get_employee_or_none(user)
        if emp is None:
            return True  # akan ditolak validasi lain (butuh EmpID), bukan urusan permission ini
        return not mobile_password_needs_change(emp)


# ---------------------------------------------------------------------------
# AUTH (login PIN Employee)
# ---------------------------------------------------------------------------
class MobileLoginAPIView(APIView):
    """
    POST /api/v1/mattendance/auth/login/  body: {pin, mobile_password}
    -> {access, refresh, must_change_password, display_name}

    BEDA dari /api/v1/auth/login/ (LoginView di api/views.py, username/
    password akun biasa) -- ini pakai PIN Employee, backend terpisah
    (EmployeeMobileBackend), otomatis buat/pakai shadow User "mobile-only"
    kalau belum ada (lihat accounts/mobile_backend.py).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MobileLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request,
            pin=serializer.validated_data['pin'],
            mobile_password=serializer.validated_data['mobile_password'],
        )
        if user is None:
            return Response({'code': 'invalid_credentials', 'message': 'PIN atau password salah.'}, status=status.HTTP_401_UNAUTHORIZED)

        emp = _get_employee_or_none(user)
        must_change = mobile_password_needs_change(emp) if emp else False

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'must_change_password': must_change,
            'display_name': _get_display_name(user),
            'pin': emp.PIN if emp else None,
        })


class MobileChangePasswordAPIView(APIView):
    """
    POST /api/v1/mattendance/auth/change-password/  body: {new_password, confirm_password}
    HANYA relevan utk user mobile-only. WAJIB tidak kosong & tidak sama
    dgn password default (settings.MOBILE_DEFAULT_PASSWORD).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not getattr(request.user, 'is_mobile_only', False):
            return Response({'code': 'not_applicable', 'message': 'Endpoint ini hanya utk akun mobile-only.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = MobileChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['new_password']
        confirm_password = serializer.validated_data['confirm_password']
        default_password = getattr(settings, 'MOBILE_DEFAULT_PASSWORD', '123456')

        if not new_password:
            return Response({'code': 'validation_error', 'message': 'Password baru wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_password == default_password:
            return Response({'code': 'validation_error', 'message': f"Password baru tidak boleh sama dengan password default ('{default_password}')."}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != confirm_password:
            return Response({'code': 'validation_error', 'message': 'Konfirmasi password tidak cocok.'}, status=status.HTTP_400_BAD_REQUEST)

        emp = _get_employee_or_none(request.user)
        if emp is None:
            return Response({'code': 'not_found', 'message': 'Akun ini tidak terkait data Employee manapun.'}, status=status.HTTP_400_BAD_REQUEST)

        emp.mpassword = make_password(new_password)
        emp.save(update_fields=['mpassword'])
        return Response({'detail': 'Password berhasil diganti.'})


# ---------------------------------------------------------------------------
# PROFIL & STATUS WAJAH
# ---------------------------------------------------------------------------
class MobileProfileAPIView(APIView):
    """GET /api/v1/mattendance/profile/ -- info ringkas Employee terkait user login."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _get_employee_or_none(request.user)
        return Response({
            'display_name': _get_display_name(request.user),
            'pin': emp.PIN if emp else None,
            'is_mobile_only': request.user.is_mobile_only,
            'has_employee_link': emp is not None,
        })


class FaceStatusAPIView(APIView):
    """GET /api/v1/mattendance/face/status/ -- has_face_profile & is_locked, utk gating UI client."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _get_employee_or_none(request.user)
        profile = FaceProfile.objects.filter(employee=emp).first() if emp else None
        return Response({
            'has_face_profile': profile is not None,
            'is_locked': profile.is_locked if profile else False,
            'enrolled_at': profile.enrolled_at if profile else None,
        })


# ---------------------------------------------------------------------------
# ENROLLMENT WAJAH
# ---------------------------------------------------------------------------
class FaceEnrollAPIView(APIView):
    """
    POST /api/v1/mattendance/face/enroll/  body: {face_image}
    Sama persis logic-nya dgn mattendance/views.py::face_enroll_submit
    (termasuk "sekali seumur hidup" is_locked, PREVENT_DUPLICATE_FACE) --
    cuma beda cara terima input (JSON body via serializer) & format respons
    (DRF Response, bukan JsonResponse).
    """
    permission_classes = [IsAuthenticated, MobilePasswordUpToDate]

    def post(self, request):
        emp = _get_employee_or_none(request.user)
        if emp is None:
            return Response({'code': 'no_employee', 'message': 'Akun ini tidak terkait data Employee manapun -- enrollment wajah tidak berlaku.'}, status=status.HTTP_400_BAD_REQUEST)

        existing_profile = FaceProfile.objects.filter(employee=emp).first()
        if existing_profile and existing_profile.is_locked:
            return Response({'code': 'locked', 'message': 'Wajah Anda sudah terdaftar & terkunci -- hubungi admin untuk mendaftar ulang.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = FaceEnrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        face_image_data = serializer.validated_data['face_image']

        existing_encodings = None
        if settings.PREVENT_DUPLICATE_FACE:
            existing_encodings = list(FaceProfile.objects.exclude(employee=emp).values('employee_id', 'encoding'))
            existing_encodings = [{'employee_id': e['employee_id'], 'encoding': e['encoding']} for e in existing_encodings]

        try:
            result = extract_face_encoding_task.delay(
                face_image_data, existing_encodings=existing_encodings,
            ).get(timeout=FACE_TASK_TIMEOUT_SECONDS)
        except CeleryTimeoutError:
            return Response({'code': 'timeout', 'message': 'Proses pendaftaran wajah memakan waktu terlalu lama -- coba lagi.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:  # noqa: BLE001
            return Response({'code': 'worker_error', 'message': f'Gagal memproses wajah: {exc}'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not result['success']:
            return Response({'code': 'processing_error', 'message': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        if result.get('duplicate_employee_id'):
            return Response({'code': 'duplicate_face', 'message': 'Wajah ini sudah terdaftar untuk employee lain -- pendaftaran ditolak.'}, status=status.HTTP_409_CONFLICT)

        _profile, created = FaceProfile.objects.update_or_create(
            employee=emp,
            defaults={'encoding': result['encoding'], 'is_locked': True},
        )
        action = 'didaftarkan' if created else 'diperbarui'
        return Response({'detail': f'Wajah berhasil {action} & terkunci.'}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# CHECK-IN/OUT & CHECK/MEAL
# ---------------------------------------------------------------------------
class CheckinAPIView(APIView):
    """
    POST /api/v1/mattendance/checkin/  body: {latitude, longitude, check_type, face_image}
    Sama persis logic-nya dgn mattendance/views.py::checkin_submit.
    """
    permission_classes = [IsAuthenticated, MobilePasswordUpToDate]

    def post(self, request):
        serializer = CheckinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        emp = _get_employee_or_none(request.user)
        face_profile = FaceProfile.objects.filter(employee=emp).first() if emp else None
        if face_profile is None:
            return Response({'code': 'needs_enrollment', 'message': 'Anda belum mendaftarkan wajah.'}, status=status.HTTP_400_BAD_REQUEST)

        pool = find_matching_pool_by_polygon(data['latitude'], data['longitude'])
        if pool is None:
            return Response({'code': 'location_not_matched', 'message': 'Lokasi Anda tidak berada di dalam area (polygon) pool manapun -- TIDAK dicatat.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = verify_face_task.delay(data['face_image'], face_profile.encoding).get(timeout=FACE_TASK_TIMEOUT_SECONDS)
        except CeleryTimeoutError:
            return Response({'code': 'timeout', 'message': 'Proses verifikasi wajah memakan waktu terlalu lama -- coba lagi.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:  # noqa: BLE001
            return Response({'code': 'worker_error', 'message': f'Gagal memproses wajah: {exc}'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not result['success']:
            return Response({'code': 'processing_error', 'message': f"Verifikasi wajah gagal: {result['error']}"}, status=status.HTTP_400_BAD_REQUEST)

        if not result['matched']:
            return Response({
                'code': 'face_not_matched',
                'message': f"Wajah tidak cocok dengan yang terdaftar (jarak {result['distance']:.3f}) -- TIDAK dicatat.",
            }, status=status.HTTP_400_BAD_REQUEST)

        function_code = determine_function_code(emp.PIN if emp else None, pool)
        log = AttendanceLog.objects.create(
            user=request.user,
            PoolID=pool,
            check_type=data['check_type'],
            latitude=data['latitude'],
            longitude=data['longitude'],
            distance_meters=None,
            location_verified=True,
            face_verified=True,
            face_distance=result['distance'],
            Function=f'{function_code}-{pool.PoolID}' if function_code else None,
        )
        maybe_consolidate_to_iclock(log)
        label = 'Check-in' if data['check_type'] == AttendanceLog.CheckType.IN else 'Check-out'
        return Response({
            'detail': f'{label} berhasil di {pool.PoolName or pool.PoolID}.',
            'log': AttendanceLogSerializer(log).data,
        }, status=status.HTTP_201_CREATED)


class CheckinMealAPIView(APIView):
    """
    POST /api/v1/mattendance/checkin/meal/  body: {latitude, longitude, qr_content}
    Sama persis logic-nya dgn mattendance/views.py::checkin_meal_submit.
    """
    permission_classes = [IsAuthenticated, MobilePasswordUpToDate]

    def post(self, request):
        serializer = CheckinMealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        poolcode = get_poolcode_from_qr(data['qr_content'])
        if poolcode is None:
            return Response({'code': 'qr_not_recognized', 'message': f"QR code '{data['qr_content']}' tidak dikenali/tidak terdaftar."}, status=status.HTTP_400_BAD_REQUEST)

        candidates = find_all_matching_pools_by_polygon(data['latitude'], data['longitude'])
        registered_poolcodes = set(getattr(settings, 'QRDEVICE', {}).keys())
        candidates = [p for p in candidates if p.PoolCode in registered_poolcodes]

        if not candidates:
            return Response({'code': 'location_not_matched', 'message': 'Lokasi Anda tidak berada di area kantin manapun yang terdaftar.'}, status=status.HTTP_400_BAD_REQUEST)

        matched_pool = next((p for p in candidates if p.PoolCode == poolcode), None)
        if matched_pool is None:
            return Response({'code': 'qr_location_mismatch', 'message': f"Lokasi GPS Anda tidak cocok dengan QR yang di-scan (PoolCode '{poolcode}')."}, status=status.HTTP_400_BAD_REQUEST)

        emp = _get_employee_or_none(request.user)
        function_code = determine_function_code(emp.PIN if emp else None, matched_pool)
        log = AttendanceLog.objects.create(
            user=request.user,
            PoolID=matched_pool,
            check_type=AttendanceLog.CheckType.MEAL,
            latitude=data['latitude'],
            longitude=data['longitude'],
            distance_meters=None,
            location_verified=True,
            face_verified=False,
            qr_content=data['qr_content'],
            Function=f'{function_code}-{matched_pool.PoolID}' if function_code else None,
        )
        maybe_consolidate_to_iclock(log)
        return Response({
            'detail': f'Check/Meal berhasil di {matched_pool.PoolName or matched_pool.PoolID}.',
            'log': AttendanceLogSerializer(log).data,
        }, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# RIWAYAT (milik sendiri)
# ---------------------------------------------------------------------------
class AttendanceHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/mattendance/history/ -- riwayat check-in/out/meal MILIK USER YANG LOGIN SENDIRI."""
    permission_classes = [IsAuthenticated]
    serializer_class = AttendanceLogSerializer

    def get_queryset(self):
        return AttendanceLog.objects.filter(user=self.request.user).select_related('PoolID').order_by('-timestamp')


# ---------------------------------------------------------------------------
# ADMIN (staff-only)
# ---------------------------------------------------------------------------
class AttendanceLogAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """GET/DELETE /api/v1/mattendance/admin/logs/ -- SEMUA user, staff-only."""
    permission_classes = [IsAuthenticated, IsStaffRole]
    serializer_class = AttendanceLogSerializer
    queryset = AttendanceLog.objects.select_related('user', 'PoolID').all()

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('q')
        if search:
            qs = qs.filter(user__username__icontains=search)
        return qs

    def destroy(self, request, pk=None):
        log = self.get_object()
        log.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FaceProfileAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET/DELETE /api/v1/mattendance/admin/face-profiles/ + POST .../toggle-lock/
    Staff-only. "Pengambilan wajah hanya dilakukan sekali" -- admin bisa
    buka kunci/hapus dari sini.
    """
    permission_classes = [IsAuthenticated, IsStaffRole]
    serializer_class = FaceProfileAdminSerializer
    queryset = FaceProfile.objects.select_related('employee').order_by('-updated_at')

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('q')
        if search:
            qs = qs.filter(employee__PIN__icontains=search)
        return qs

    def destroy(self, request, pk=None):
        profile = self.get_object()
        profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='toggle-lock')
    def toggle_lock(self, request, pk=None):
        profile = self.get_object()
        profile.is_locked = not profile.is_locked
        profile.save(update_fields=['is_locked'])
        return Response(FaceProfileAdminSerializer(profile).data)