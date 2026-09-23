from django.contrib import admin
from django.urls import reverse

from tickets.models import Customer, Ticket


def test_ticket_and_customer_admin_are_registered():
    assert Ticket in admin.site._registry
    assert Customer in admin.site._registry
    assert reverse("admin:tickets_ticket_changelist") == "/admin/tickets/ticket/"
