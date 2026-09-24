"""Read the selected record and one level of permission-checked relationships."""

from pathlib import Path

from django.contrib import admin

from .models import Agent, Comment, Customer, Ticket


def _timestamps(obj):
    return {"created_at": obj.created_at.isoformat(), "updated_at": obj.updated_at.isoformat()}


def _customer(obj):
    return {
        "id": obj.pk,
        "name": obj.name,
        "email": obj.email,
        "company": obj.company,
        **_timestamps(obj),
    }


def _agent(obj):
    # Only directory details, never the authentication user's credentials or permissions.
    return {
        "id": obj.pk,
        "name": str(obj),
        "username": obj.user.get_username(),
        "active": obj.user.is_active,
    }


def _ticket(obj):
    return {
        "id": obj.pk,
        "subject": obj.subject,
        "description": obj.description,
        "status": obj.get_status_display(),
        "priority": obj.get_priority_display(),
        **_timestamps(obj),
    }


def _comment(obj):
    return {
        "id": obj.pk,
        "ticket_id": obj.ticket_id,
        "author": obj.author.get_username(),
        "body": obj.body,
        "attachment": Path(obj.attachment.name).name if obj.attachment else None,
        **_timestamps(obj),
    }


SERIALIZERS = {Customer: _customer, Agent: _agent, Ticket: _ticket}


def _ticket_comments(request, ticket):
    ticket_admin = admin.site._registry[Ticket]
    for inline in ticket_admin.get_inline_instances(request, ticket):
        if inline.model is Comment and inline.has_view_or_change_permission(request, ticket):
            comments = inline.get_queryset(request).filter(ticket=ticket).order_by("pk")
            return {"available": True, "records": [_comment(comment) for comment in comments]}
    return {"available": False, "records": []}


def _related(request, model, **filters):
    model_admin = admin.site._registry[model]
    if not model_admin.has_view_or_change_permission(request):
        return {"available": False, "records": []}
    queryset = model_admin.get_queryset(request).filter(**filters).order_by("pk")
    records = [
        SERIALIZERS[model](obj)
        for obj in queryset
        if model_admin.has_view_or_change_permission(request, obj)
    ]
    return {"available": True, "records": records}


def object_context(request, obj):
    if obj is None:
        return {"record": None, "related": {}}
    if isinstance(obj, Ticket):
        related = {
            "customer": _related(request, Customer, pk=obj.customer_id),
            "assignees": _related(request, Agent, tickets=obj),
            "comments": _ticket_comments(request, obj),
        }
    elif isinstance(obj, Customer):
        related = {"tickets": _related(request, Ticket, customer=obj)}
    else:  # Agent
        related = {"tickets": _related(request, Ticket, assignees=obj)}
    return {"record": SERIALIZERS[type(obj)](obj), "related": related}
