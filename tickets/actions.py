from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction


@admin.action(description="Resolve selected tickets", permissions=["change"])
def resolve_tickets(modeladmin, request, queryset):
    with transaction.atomic():
        result = queryset.resolve()
        LogEntry.objects.log_actions(
            user_id=request.user.pk,
            queryset=result.resolved,
            action_flag=CHANGE,
            change_message=[{"changed": {"fields": ["status"]}}],
        )
    skipped_count = sum(len(tickets) for tickets in result.skipped.values())
    modeladmin.message_user(
        request,
        f"{len(result.resolved)} resolved, {len(result.unchanged)} unchanged, "
        f"{skipped_count} skipped.",
        messages.WARNING if skipped_count else messages.SUCCESS,
    )
    for reason, tickets in result.skipped.items():
        ticket_ids = ", ".join(str(ticket.pk) for ticket in tickets[:10])
        suffix = f" (and {len(tickets) - 10} more)" if len(tickets) > 10 else ""
        modeladmin.message_user(
            request, f"Tickets {ticket_ids}{suffix}: {reason}", messages.WARNING
        )
