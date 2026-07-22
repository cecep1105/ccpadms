from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import (
    ActiveDeviceViewSet,
    AttendanceRecapAPIView,
    AttendanceRecapEmployeeCardAPIView,
    DepartmentViewSet,
    DeviceCommandViewSet,
    DeviceFunctionChoicesAPIView,
    DeviceLogViewSet,
    EmployeeSearchAPIView,
    EmployeeViewSet,
    FingerprintTemplateViewSet,
    OperationLogViewSet,
    RegisteredDeviceViewSet,
    TransactionViewSet,
)

app_name = 'iclock_api'

router = DefaultRouter()
router.register('department', DepartmentViewSet, basename='department')
router.register('active-device', ActiveDeviceViewSet, basename='active-device')
router.register('registered-device', RegisteredDeviceViewSet, basename='registered-device')
router.register('device-user', EmployeeViewSet, basename='device-user')
router.register('fingerprint-template', FingerprintTemplateViewSet, basename='fingerprint-template')
router.register('transaction', TransactionViewSet, basename='transaction')
router.register('operation-log', OperationLogViewSet, basename='operation-log')
router.register('device-log', DeviceLogViewSet, basename='device-log')
router.register('device-command', DeviceCommandViewSet, basename='device-command')

urlpatterns = [
    path('attendance-recap/', AttendanceRecapAPIView.as_view(), name='attendance_recap'),
    path('attendance-recap/<str:pin>/card/', AttendanceRecapEmployeeCardAPIView.as_view(), name='attendance_recap_card'),
    path('employee-search/', EmployeeSearchAPIView.as_view(), name='employee_search'),
    path('device-function-choices/', DeviceFunctionChoicesAPIView.as_view(), name='device_function_choices'),
] + router.urls
