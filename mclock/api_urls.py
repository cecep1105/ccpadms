from rest_framework.routers import DefaultRouter

from .api_views import MobilePoolLocViewSet, MobilePoolViewSet, PoolDeviceFunctionViewSet

app_name = 'mclock_api'

router = DefaultRouter()
router.register('mobile-pool', MobilePoolViewSet, basename='mobile-pool')
router.register('mobile-pool-loc', MobilePoolLocViewSet, basename='mobile-pool-loc')
router.register('pool-device-function', PoolDeviceFunctionViewSet, basename='pool-device-function')

urlpatterns = router.urls
