from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(
        template_name="orders/login.html",
        extra_context={"business_name": settings.BUSINESS_NAME},
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("webhooks/whatsapp/", include("orders.whatsapp_urls")),
    path("", include("orders.urls")),
]