from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import MobilePoolLocBulkSaveAPIView, MobilePoolLocViewSet, MobilePoolViewSet, PoolDeviceFunctionViewSet

app_name = 'mclock_api'

router = DefaultRouter()
router.register('mobile-pool', MobilePoolViewSet, basename='mobile-pool')
router.register('mobile-pool-loc', MobilePoolLocViewSet, basename='mobile-pool-loc')
router.register('pool-device-function', PoolDeviceFunctionViewSet, basename='pool-device-function')

urlpatterns = [
    # WAJIB di ATAS router.urls -- kalau di bawah, DefaultRouter's
    # 'mobile-pool-loc/<pk>/' bisa "menangkap" duluan path literal
    # 'mobile-pool-loc/bulk-save/<pool_id>/' krn keduanya sama-sama diawali
    # 'mobile-pool-loc/'.
    path('mobile-pool-loc/bulk-save/<str:pool_id>/', MobilePoolLocBulkSaveAPIView.as_view(), name='mobile_pool_loc_bulk_save'),
] + router.urls