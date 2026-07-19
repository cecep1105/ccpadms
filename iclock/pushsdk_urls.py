from django.urls import path

from . import pushsdk_views

app_name = 'iclock_pushsdk'

urlpatterns = [
    path('cdata', pushsdk_views.cdata, name='cdata'),
    path('getrequest', pushsdk_views.getrequest, name='getrequest'),
    path('devicecmd', pushsdk_views.devicecmd, name='devicecmd'),
]