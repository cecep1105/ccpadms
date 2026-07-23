from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import RouterOSCommandView

app_name = 'netmon_api'

router = SimpleRouter()
# The trailing `(?P<command>.*)` captures everything (including nested commands like interface/print) into a variable
router.register(r'routeros', RouterOSCommandView, basename='routeros')

urlpatterns = [
    path('mikrotik/<str:host>/<path:command>/', RouterOSCommandView.as_view(), name='routeros-command'),
]

