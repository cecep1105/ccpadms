from django.urls import include, path

urlpatterns = [
    path('accounts/', include('accounts.urls')),
    path('', include('dashboard.urls')),
    path('api/v1/', include('api.urls')),
    path('api/v1/iclock/', include('iclock.api_urls')),
    path('api/v1/mattendance/', include('mattendance.api_urls')),
    path('api/v1/mclock/', include('mclock.api_urls')),
    # PENTING: path INI ('/iclock/cdata', '/iclock/getrequest', '/iclock/devicecmd')
    # HARDCODED di firmware device fisik (protokol PUSH SDK, lihat resume di
    # test/pushsdk_protocol_resume.md) -- TIDAK BOLEH diubah/dipindah, BEDA
    # dari '/admin/iclock/' (dashboard admin) & '/api/v1/iclock/' (API Nuxt) di atas.
    path('iclock/', include('iclock.pushsdk_urls')),
    path('admin/iclock/', include('iclock.urls')),
    path('admin/mclock/', include('mclock.urls')),
    path('mattendance/', include('mattendance.urls')),
]