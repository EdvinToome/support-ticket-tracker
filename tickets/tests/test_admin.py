from io import BytesIO

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

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


@pytest.fixture
def agent_ticket(client, django_user_model):
    user = django_user_model.objects.create_user(username="agent", is_staff=True)
    user.groups.add(Group.objects.get(name="Agent"))
    client.force_login(user)
    customer = Customer.objects.create(name="Ada", email="ada@example.test")
    ticket = Ticket.objects.create(
        subject="Invoice", description="Check the amount", customer=customer
    )
    return user, ticket


@pytest.mark.django_db
def test_closed_ticket_locks_details_but_accepts_comments(client, agent_ticket):
    user, ticket = agent_ticket
    ticket.status = Ticket.Status.CLOSED
    ticket.save()
    url = reverse("admin:tickets_ticket_change", args=[ticket.pk])
    response = client.get(url)
    assert not response.context["adminform"].form.fields
    assert b"/admin/tickets/comment/" not in response.content
    assert client.get("/admin/tickets/comment/").status_code == 404
    response = client.post(
        url,
        {
            "subject": "Tampered title",
            "status": "open",
            "priority": "3",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "1000",
            "comments-0-body": "Customer followed up after closure.",
            "_continue": "Save",
        },
    )
    assert response.status_code == 302
    ticket.refresh_from_db()
    assert ticket.subject == "Invoice"
    assert ticket.status == Ticket.Status.CLOSED
    assert ticket.priority == Ticket.Priority.NORMAL
    assert ticket.comments.get().body == "Customer followed up after closure."


@pytest.mark.django_db
def test_upload_validation_returns_errors_then_retry_saves_attachment(client, agent_ticket):
    user, ticket = agent_ticket
    image = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    payload = image.getvalue()
    data = {
        "subject": ticket.subject,
        "description": ticket.description,
        "customer": ticket.customer_id,
        "status": "resolved",
        "priority": "2",
        "comments-TOTAL_FORMS": "1",
        "comments-INITIAL_FORMS": "0",
        "comments-MIN_NUM_FORMS": "0",
        "comments-MAX_NUM_FORMS": "1000",
        "comments-0-body": "Evidence attached.",
        "_continue": "Save",
    }
    url = reverse("admin:tickets_ticket_change", args=[ticket.pk])
    response = client.post(
        url,
        {
            **data,
            "comments-0-attachment": SimpleUploadedFile("evidence.png", payload, "image/png"),
        },
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "field": "id_status",
            "label": "Status",
            "messages": ["Add a comment before resolving this ticket."],
        }
    ]
    assert not ticket.comments.exists()
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.OPEN

    response = client.post(
        url,
        {
            **data,
            "status": "open",
            "comments-0-attachment": SimpleUploadedFile("evidence.png", payload, "image/png"),
        },
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 302
    comment = ticket.comments.get()
    assert comment.body == "Evidence attached."
    with comment.attachment.open("rb") as saved:
        assert saved.read() == payload
