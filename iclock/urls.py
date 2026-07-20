from django.urls import path

from . import views

app_name = 'iclock'

urlpatterns = [
    # Department / Pool (model: department)
    path('department/', views.department_list, name='department_list'),
    path('department/add/', views.department_add, name='department_add'),
    path('department/<int:pk>/edit/', views.department_edit, name='department_edit'),
    path('department/<int:pk>/delete/', views.department_delete, name='department_delete'),

    # Active Device (model: iclock) -- SN adalah primary key (string)
    path('active-device/', views.active_device_list, name='active_device_list'),
    path('active-device/add/', views.active_device_add, name='active_device_add'),
    path('active-device/<str:sn>/edit/', views.active_device_edit, name='active_device_edit'),
    path('active-device/<str:sn>/delete/', views.active_device_delete, name='active_device_delete'),
    path('active-device/<str:sn>/users/', views.active_device_show_users, name='active_device_show_users'),
    path('active-device/<str:sn>/backup-fingerprints/',
         views.active_device_backup_fingerprints, name='active_device_backup_fingerprints'),
    path('active-device/<str:sn>/reboot/', views.active_device_reboot, name='active_device_reboot'),
    path('active-device/<str:sn>/sync-time/', views.active_device_sync_time, name='active_device_sync_time'),
    path('active-device/<str:sn>/network-params/',
         views.active_device_set_network_params, name='active_device_set_network_params'),
    path('active-device/<str:sn>/generic-param/',
         views.active_device_generic_param, name='active_device_generic_param'),
    path('active-device/<str:sn>/users/<str:user_id>/toggle-privilege/',
         views.active_device_user_toggle_privilege, name='active_device_user_toggle_privilege'),
    path('active-device/<str:sn>/users/<str:user_id>/delete/',
         views.active_device_user_delete, name='active_device_user_delete'),
    path('active-device/<str:sn>/users/<str:user_id>/transfer-finger/',
         views.active_device_user_transfer_finger, name='active_device_user_transfer_finger'),
    path('ajax/devices-by-pool/', views.ajax_devices_by_pool, name='ajax_devices_by_pool'),

    # Registered Device (model: RegisteredDevice)
    path('registered-device/', views.registered_device_list, name='registered_device_list'),
    path('registered-device/add/', views.registered_device_add, name='registered_device_add'),
    path('registered-device/<int:pk>/edit/', views.registered_device_edit, name='registered_device_edit'),
    path('registered-device/<int:pk>/delete/', views.registered_device_delete, name='registered_device_delete'),

    # Device User (model: employee)
    path('device-user/', views.device_user_list, name='device_user_list'),
    path('device-user/add/', views.device_user_add, name='device_user_add'),
    path('device-user/<int:pk>/edit/', views.device_user_edit, name='device_user_edit'),
    path('device-user/<int:pk>/delete/', views.device_user_delete, name='device_user_delete'),
    path('device-user/<int:pk>/toggle-privilege/', views.device_user_toggle_privilege, name='device_user_toggle_privilege'),
    path('device-user/<int:pk>/transfer-finger/', views.device_user_transfer_finger, name='device_user_transfer_finger'),

    # Fingerprint Template (model: fptemp)
    path('fingerprint-template/', views.fingerprint_template_list, name='fingerprint_template_list'),
    path('fingerprint-template/add/', views.fingerprint_template_add, name='fingerprint_template_add'),
    path('fingerprint-template/<int:pk>/edit/', views.fingerprint_template_edit, name='fingerprint_template_edit'),
    path('fingerprint-template/<int:pk>/delete/', views.fingerprint_template_delete, name='fingerprint_template_delete'),

    # Transaction / Log Absensi (model: transaction)
    path('transaction/', views.transaction_list, name='transaction_list'),
    path('transaction/add/', views.transaction_add, name='transaction_add'),
    path('transaction/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),

    # Operation Log (model: oplog)
    path('operation-log/', views.operation_log_list, name='operation_log_list'),
    path('operation-log/add/', views.operation_log_add, name='operation_log_add'),
    path('operation-log/<int:pk>/edit/', views.operation_log_edit, name='operation_log_edit'),
    path('operation-log/<int:pk>/delete/', views.operation_log_delete, name='operation_log_delete'),

    # Device Log (model: devlog)
    path('device-log/', views.device_log_list, name='device_log_list'),
    path('device-log/add/', views.device_log_add, name='device_log_add'),
    path('device-log/<int:pk>/edit/', views.device_log_edit, name='device_log_edit'),
    path('device-log/<int:pk>/delete/', views.device_log_delete, name='device_log_delete'),

    # Device Command (model: devcmds)
    path('device-command/', views.device_command_list, name='device_command_list'),
    path('device-command/add/', views.device_command_add, name='device_command_add'),
    path('device-command/<int:pk>/edit/', views.device_command_edit, name='device_command_edit'),
    path('device-command/<int:pk>/delete/', views.device_command_delete, name='device_command_delete'),

    # Attendance Recap / Rekap Kehadiran
    path('attendance-recap/', views.attendance_recap, name='attendance_recap'),
    path('attendance-recap/employee/<str:pin>/', views.attendance_recap_employee_card, name='attendance_recap_employee_card'),
    path('ajax/employee-search/', views.ajax_employee_search, name='ajax_employee_search'),
]