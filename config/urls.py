from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path('accounts/', include('accounts.urls')),
    path('', include('dashboard.urls')),
    path('api/v1/', include('api.urls')),
    path('api/v1/iclock/', include('iclock.api_urls')),
    path('api/v1/mattendance/', include('mattendance.api_urls')),
    path('api/v1/mclock/', include('mclock.api_urls')),
    path('api/v1/netmgmt/', include('netmgmt.api_urls')),
    path('api/v1/idcard/', include('idcard.api_urls')),
    # PENTING: path INI ('/iclock/cdata', '/iclock/getrequest', '/iclock/devicecmd')
    # HARDCODED di firmware device fisik (protokol PUSH SDK, lihat resume di
    # test/pushsdk_protocol_resume.md) -- TIDAK BOLEH diubah/dipindah, BEDA
    # dari '/admin/iclock/' (dashboard admin) & '/api/v1/iclock/' (API Nuxt) di atas.
    path('iclock/', include('iclock.pushsdk_urls')),
    path('admin/iclock/', include('iclock.urls')),
    path('admin/mclock/', include('mclock.urls')),
    path('mattendance/', include('mattendance.urls')),
]

# Serve file /media/ (upload template/foto ID Card, dll) LANGSUNG lewat
# Django -- CUMA saat DEBUG=True (development). Produksi WAJIB di-serve
# oleh web server (nginx/dst), baris ini TIDAK aktif kalau DEBUG=False
# (lihat catatan lengkap di config/settings.py::MEDIA_ROOT).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)