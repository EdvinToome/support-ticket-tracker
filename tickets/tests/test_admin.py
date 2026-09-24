import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tickets.models import Agent, Comment, Customer, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer():
    return Customer.objects.create(name="Demo customer", email="customer@example.test")


@pytest.fixture
def agent_user(client):
    user = User.objects.create_user(username="triage", is_staff=True)
    user.groups.add(Group.objects.get(name="Agent"))
    client.force_login(user)
    return user


def test_bulk_action_reports_partial_success_and_logs_changes(client, agent_user, customer):
    eligible = Ticket.objects.create(subject="Eligible", description="Issue", customer=customer)
    Comment.objects.create(ticket=eligible, author=agent_user, body="Investigated")
    empty = Ticket.objects.create(subject="Empty", description="Issue", customer=customer)
    closed = Ticket.objects.create(subject="Closed", description="Issue", customer=customer)
    closed.status = Ticket.Status.CLOSED
    closed.save()
    resolved = Ticket.objects.create(subject="Resolved", description="Issue", customer=customer)
    Comment.objects.create(ticket=resolved, author=agent_user, body="Fixed")
    resolved.status = Ticket.Status.RESOLVED
    resolved.save()
    response = client.post(
        reverse("admin:tickets_ticket_changelist"),
        {
            "action": "resolve_tickets",
            "_selected_action": [eligible.pk, empty.pk, closed.pk, resolved.pk],
        },
        follow=True,
    )
    assert response.status_code == 200
    eligible.refresh_from_db()
    empty.refresh_from_db()
    closed.refresh_from_db()
    assert eligible.status == Ticket.Status.RESOLVED
    assert empty.status == Ticket.Status.OPEN
    assert closed.status == Ticket.Status.CLOSED
    assert LogEntry.objects.filter(action_flag=CHANGE, object_id=str(eligible.pk)).count() == 1
    assert LogEntry.objects.count() == 1
    assert b"1 resolved" in response.content
    assert b"1 unchanged" in response.content
    assert b"2 skipped" in response.content


def test_viewer_cannot_resolve_with_forged_post(client, customer):
    viewer = User.objects.create_user(username="reader", is_staff=True)
    viewer.groups.add(Group.objects.get(name="Viewer"))
    ticket = Ticket.objects.create(subject="Issue", description="Details", customer=customer)
    Comment.objects.create(ticket=ticket, author=viewer, body="Details")
    client.force_login(viewer)
    response = client.post(
        reverse("admin:tickets_ticket_changelist"),
        {
            "action": "resolve_tickets",
            "_selected_action": [ticket.pk],
        },
    )
    ticket.refresh_from_db()
    # The action is not offered to Viewers, so the POST just re-renders the list.
    assert response.status_code == 200
    assert ticket.status == Ticket.Status.OPEN
    assert not LogEntry.objects.exists()


def test_agent_can_add_but_cannot_change_customer(client, agent_user, customer):
    add_url = reverse("admin:tickets_customer_add")
    assert client.get(add_url).status_code == 200
    response = client.post(add_url, {"name": "New", "email": "new@example.test", "company": ""})
    assert response.status_code == 302
    assert Customer.objects.filter(email="new@example.test").exists()
    change_url = reverse("admin:tickets_customer_change", args=[customer.pk])
    assert client.get(change_url).status_code == 200
    assert client.post(change_url, {"name": "Tampered", "email": customer.email}).status_code == 403
    customer.refresh_from_db()
    assert customer.name == "Demo customer"


def test_duplicate_customer_email_is_a_readable_form_error(client, agent_user, customer):
    response = client.post(
        reverse("admin:tickets_customer_add"),
        {"name": "Copy", "email": customer.email.upper(), "company": ""},
    )
    assert response.status_code == 200
    assert "already exists" in str(response.context["adminform"].form.non_field_errors())


def test_ticket_list_queries_do_not_grow_with_agents(client, agent_user, customer):
    Ticket.objects.create(subject="Issue", description="Details", customer=customer)
    agent_group = Group.objects.get(name="Agent")

    def list_queries():
        with CaptureQueriesContext(connection) as queries:
            client.get(reverse("admin:tickets_ticket_changelist"))
        return len(queries)

    def add_agents(count):
        for _ in range(count):
            user = User.objects.create_user(username=f"agent-{Agent.objects.count()}")
            user.groups.add(agent_group)
            Agent.objects.create(user=user)

    add_agents(1)
    baseline = list_queries()
    add_agents(5)
    assert list_queries() == baseline


def test_ticket_search_matches_id_and_text(client, agent_user, customer):
    ticket = Ticket.objects.create(subject="Refund", description="Details", customer=customer)
    Ticket.objects.create(subject="Other", description="Details", customer=customer)
    url = reverse("admin:tickets_ticket_changelist")
    for term in (str(ticket.pk), "refund"):
        rows = list(client.get(url, {"q": term}).context["cl"].result_list)
        assert [row.pk for row in rows] == [ticket.pk]


def test_triage_counts_and_assignment_filter(client, agent_user, customer):
    roster = Agent.objects.create(user=agent_user)
    second_user = User.objects.create_user(username="other", is_staff=True)
    second_user.groups.add(Group.objects.get(name="Agent"))
    second = Agent.objects.create(user=second_user)
    ticket = Ticket.objects.create(subject="Shared issue", description="Details", customer=customer)
    ticket.assignees.add(roster, second)
    Comment.objects.create(ticket=ticket, author=agent_user, body="One")
    Comment.objects.create(ticket=ticket, author=agent_user, body="Two")
    Ticket.objects.create(subject="Unassigned", description="Details", customer=customer)
    response = client.get(reverse("admin:tickets_ticket_changelist"), {"assignment": "mine"})
    rows = list(response.context["cl"].result_list)
    assert len(rows) == 1
    assert rows[0].comment_total == 2


def test_new_ticket_status_and_comment_author_cannot_be_forged(client, agent_user, customer):
    other = User.objects.create_user(username="forged")
    response = client.post(
        reverse("admin:tickets_ticket_add"),
        {
            "subject": "New",
            "description": "Details",
            "customer": customer.pk,
            "status": "closed",
            "priority": 2,
            "comments-TOTAL_FORMS": 1,
            "comments-INITIAL_FORMS": 0,
            "comments-MIN_NUM_FORMS": 0,
            "comments-MAX_NUM_FORMS": 1000,
            "comments-0-body": "Initial investigation",
            "comments-0-author": other.pk,
        },
    )
    assert response.status_code == 302
    ticket = Ticket.objects.get(subject="New")
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.comments.get().author == agent_user
