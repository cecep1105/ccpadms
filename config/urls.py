from django.urls import include, path

urlpatterns = [
    path('accounts/', include('accounts.urls')),
    path('', include('dashboard.urls')),
    path('api/v1/', include('api.urls')),
    path('api/v1/iclock/', include('iclock.api_urls')),
    path('api/v1/mattendance/', include('mattendance.api_urls')),
    path('api/v1/mclock/', include('mclock.api_urls')),
    path('admin/iclock/', include('iclock.urls')),
    path('admin/mclock/', include('mclock.urls')),
    path('mattendance/', include('mattendance.urls')),
]
