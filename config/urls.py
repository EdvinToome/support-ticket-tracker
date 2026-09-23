from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from .views import healthz

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("healthz", healthz, name="healthz"),
    path("admin/", admin.site.urls),
]
handler500 = "config.views.server_error"
