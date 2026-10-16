from django.urls import path

from .views import whatsapp_webhook

urlpatterns = [path("", whatsapp_webhook, name="whatsapp-webhook")]