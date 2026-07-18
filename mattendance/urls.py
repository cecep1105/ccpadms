from django.urls import path

from . import views

app_name = 'mattendance'

urlpatterns = [
    path('login/', views.mobile_login_page, name='mobile_login_page'),
    path('login/submit/', views.mobile_login_submit, name='mobile_login_submit'),
    path('change-password/', views.mobile_change_password_page, name='mobile_change_password_page'),
    path('change-password/submit/', views.mobile_change_password_submit, name='mobile_change_password_submit'),
    path('profile/', views.mobile_profile_page, name='mobile_profile_page'),
    path('history/', views.attendance_history_page, name='attendance_history_page'),
    path('checkin/', views.checkin_test_page, name='checkin_test_page'),
    path('checkin/submit/', views.checkin_submit, name='checkin_submit'),
    path('checkin/meal/', views.checkin_meal_page, name='checkin_meal_page'),
    path('checkin/meal/submit/', views.checkin_meal_submit, name='checkin_meal_submit'),
    path('face/enroll/', views.face_enroll_page, name='face_enroll_page'),
    path('face/enroll/submit/', views.face_enroll_submit, name='face_enroll_submit'),
    path('logs/', views.attendance_log_list, name='attendance_log_list'),
    path('logs/<int:pk>/delete/', views.attendance_log_delete, name='attendance_log_delete'),
    path('face-profiles/', views.face_profile_admin_list, name='face_profile_admin_list'),
    path('face-profiles/<int:pk>/toggle-lock/', views.face_profile_toggle_lock, name='face_profile_toggle_lock'),
    path('face-profiles/<int:pk>/delete/', views.face_profile_admin_delete, name='face_profile_admin_delete'),
]
