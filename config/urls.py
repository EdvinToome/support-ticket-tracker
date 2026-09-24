from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from tickets.admin_views import assistant_view

from .views import healthz

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("healthz", healthz, name="healthz"),
    path("admin/assistant/", assistant_view, name="admin_ticket_assistant"),
    path("admin/", admin.site.urls),
]
handler500 = "config.views.server_error"
