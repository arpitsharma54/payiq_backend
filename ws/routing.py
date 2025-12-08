from django.urls import path
from ws.consumer import TaskStatusConsumer

websocket_urlpatterns = [
    path("ws/status/", TaskStatusConsumer.as_asgi()),
]