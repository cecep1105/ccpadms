from django.urls import path

from . import views

app_name = 'mclock'

urlpatterns = [
    path('', views.mobile_attendance_home, name='mobile_attendance_home'),
    path('mobile-pool/', views.mobile_pool_list, name='mobile_pool_list'),
    path('mobile-pool/add/', views.mobile_pool_add, name='mobile_pool_add'),
    path('mobile-pool/<str:pool_id>/delete/', views.mobile_pool_delete, name='mobile_pool_delete'),
    path('mobile-pool-loc/', views.mobile_pool_loc_list, name='mobile_pool_loc_list'),
    path('mobile-pool-loc/add/', views.mobile_pool_loc_add, name='mobile_pool_loc_add'),
    path('mobile-pool-loc/<int:pk>/delete/', views.mobile_pool_loc_delete, name='mobile_pool_loc_delete'),
    path('mobile-pool-loc/<str:pool_id>/delete-all/', views.mobile_pool_loc_delete_pool, name='mobile_pool_loc_delete_pool'),
    path('pool-device-function/', views.pool_device_function_list, name='pool_device_function_list'),
    path('pool-device-function/add/', views.pool_device_function_add, name='pool_device_function_add'),
    path('pool-device-function/<int:pk>/edit/', views.pool_device_function_edit, name='pool_device_function_edit'),
    path('pool-device-function/<int:pk>/delete/', views.pool_device_function_delete, name='pool_device_function_delete'),
    path('<slug:slug>/', views.mobile_attendance_table, name='mobile_attendance_table'),
]
