from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/iclock$', consumers.IclockConsumer.as_asgi()),
]
