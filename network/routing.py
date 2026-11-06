from django.urls import path

from .realtime import PaymentRealtimeConsumer, TenantRealtimeConsumer


websocket_urlpatterns = [
    path("ws/tenant/realtime/", TenantRealtimeConsumer.as_asgi()),
    path("ws/public/<str:tenant_id>/payment/<str:payment_id>/", PaymentRealtimeConsumer.as_asgi()),
]
