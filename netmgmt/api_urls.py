from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .routeros_api_view import RouterOSCommandView

app_name = 'netmon_api'

router = SimpleRouter()
router.register(r'routeros', RouterOSCommandView, basename='routeros')

urlpatterns = [
    path('routeros/<str:host>/<path:command>/', RouterOSCommandView.as_view(), name='routeros-command'),
]

