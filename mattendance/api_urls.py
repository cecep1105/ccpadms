from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import (
    AttendanceHistoryViewSet,
    AttendanceLogAdminViewSet,
    CheckinAPIView,
    CheckinMealAPIView,
    FaceEnrollAPIView,
    FaceProfileAdminViewSet,
    FaceStatusAPIView,
    MobileChangePasswordAPIView,
    MobileLoginAPIView,
    MobileProfileAPIView,
)

app_name = 'mattendance_api'

router = DefaultRouter()
router.register('history', AttendanceHistoryViewSet, basename='history')
router.register('admin/logs', AttendanceLogAdminViewSet, basename='admin-logs')
router.register('admin/face-profiles', FaceProfileAdminViewSet, basename='admin-face-profiles')

urlpatterns = [
    path('auth/login/', MobileLoginAPIView.as_view(), name='mobile_login'),
    path('auth/change-password/', MobileChangePasswordAPIView.as_view(), name='mobile_change_password'),
    path('profile/', MobileProfileAPIView.as_view(), name='profile'),
    path('face/status/', FaceStatusAPIView.as_view(), name='face_status'),
    path('face/enroll/', FaceEnrollAPIView.as_view(), name='face_enroll'),
    path('checkin/', CheckinAPIView.as_view(), name='checkin'),
    path('checkin/meal/', CheckinMealAPIView.as_view(), name='checkin_meal'),
] + router.urls
