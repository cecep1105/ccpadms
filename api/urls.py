from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import ChangeOwnPasswordView, LoginView, LogoutView, MeView, UserViewSet

app_name = 'api'

user_list = UserViewSet.as_view({'get': 'list', 'post': 'create'})
user_detail = UserViewSet.as_view({'get': 'retrieve', 'patch': 'update', 'put': 'update', 'delete': 'destroy'})
user_reset_password = UserViewSet.as_view({'post': 'reset_password'})
user_toggle_active = UserViewSet.as_view({'post': 'toggle_active'})
user_set_staff = UserViewSet.as_view({'post': 'set_staff'})

urlpatterns = [
    # Auth
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),

    # Profil (self-service)
    path('me/', MeView.as_view(), name='me'),
    path('me/change-password/', ChangeOwnPasswordView.as_view(), name='change_password'),

    # Manajemen user (admin only)
    path('users/', user_list, name='user_list'),
    path('users/<int:pk>/', user_detail, name='user_detail'),
    path('users/<int:pk>/reset-password/', user_reset_password, name='user_reset_password'),
    path('users/<int:pk>/toggle-active/', user_toggle_active, name='user_toggle_active'),
    path('users/<int:pk>/set-staff/', user_set_staff, name='user_set_staff'),
]