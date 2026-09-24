import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from tickets.models import Comment, Customer, Ticket


@pytest.mark.django_db
def test_bulk_action_resolves_only_eligible_tickets_and_reports_the_result(
    client, django_user_model
):
    agent = django_user_model.objects.create_user(username="agent", is_staff=True)
    agent.groups.add(Group.objects.get(name="Agent"))
    client.force_login(agent)
    customer = Customer.objects.create(name="Ada", email="ada@example.test")
    eligible, empty, closed, resolved = Ticket.objects.bulk_create(
        [
            Ticket(subject=subject, description="Issue", customer=customer, status=status)
            for subject, status in [
                ("Eligible", "open"),
                ("No comment", "open"),
                ("Closed", "closed"),
                ("Already resolved", "resolved"),
            ]
        ]
    )
    Comment.objects.bulk_create(
        [
            Comment(ticket=ticket, author=agent, body="Investigated")
            for ticket in (eligible, resolved)
        ]
    )

    response = client.post(
        reverse("admin:tickets_ticket_changelist"),
        {
            "action": "resolve_tickets",
            "_selected_action": [eligible.pk, empty.pk, closed.pk, resolved.pk],
        },
        follow=True,
    )

    assert dict(Ticket.objects.values_list("pk", "status")) == {
        eligible.pk: "resolved",
        empty.pk: "open",
        closed.pk: "closed",
        resolved.pk: "resolved",
    }
    assert list(LogEntry.objects.values_list("object_id", "action_flag")) == [
        (str(eligible.pk), CHANGE)
    ]
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert "1 resolved, 1 unchanged, 2 skipped." in messages
