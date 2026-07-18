from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('home/', views.user_home, name='user_home'),

    path('admin/', views.admin_home, name='admin_home'),
    path('admin/users/', views.user_list, name='user_list'),
    path('admin/users/create/', views.user_create, name='user_create'),
    path('admin/users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('admin/users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
    path('admin/users/<int:user_id>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),
    path('admin/users/<int:user_id>/reset-password/', views.user_reset_password, name='user_reset_password'),
    path('admin/users/<int:user_id>/set-staff/', views.user_set_staff, name='user_set_staff'),
    path('admin/users/<int:user_id>/permissions/', views.user_manage_permissions, name='user_manage_permissions'),

    path('profile/', views.profile, name='profile'),
    path('profile/change-password/', views.profile_change_password, name='profile_change_password'),
]
