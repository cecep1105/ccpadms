from django.urls import path

from .routeros_api_view import RouterOSCommandView

app_name = 'netmgmt_api'

# PENTING: RouterOSCommandView adalah APIView BIASA (bukan ViewSet), jadi
# TIDAK BISA didaftarkan ke DRF Router (`router.register(...)`) -- Router
# butuh ViewSet (perlu method as_view({method: action}) style mapping yg
# cuma dipunyai ViewSet). SEBELUMNYA ada baris `router.register(...)` di
# sini yang secara teknis SALAH (walau kebetulan tidak error krn
# `router.urls`-nya toh tidak pernah dipakai di urlpatterns) -- sudah
# dihapus, path() eksplisit di bawah ini SATU-SATUNYA & CUKUP.
urlpatterns = [
    path('routeros/<str:host>/<path:command>/', RouterOSCommandView.as_view(), name='routeros-command'),
]

