import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.forms import modelform_factory

from tickets.models import Agent, Comment, Customer, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def author():
    return get_user_model().objects.create_user(username="author", password="unused")


@pytest.fixture
def customer():
    return Customer.objects.create(name="Ada", email="ada@example.com")


def make_ticket(customer, status=Ticket.Status.OPEN):
    return Ticket.objects.create(
        subject="Missing receipt", description="Please resend it", customer=customer, status=status
    )


def test_customer_email_is_unique_without_case_sensitivity(customer):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Customer.objects.create(name="Another Ada", email="ADA@example.com")


def test_agent_requires_active_user_in_agent_or_admin_group(author):
    agent = Agent(user=author)
    with pytest.raises(ValidationError):
        agent.full_clean()

    author.groups.add(Group.objects.get(name="Agent"))
    agent.full_clean()
    author.is_active = False
    author.save()
    with pytest.raises(ValidationError):
        agent.full_clean()


@pytest.mark.parametrize("data", [{}, {"user": "999999999"}])
def test_invalid_agent_user_is_a_form_error(data):
    form = modelform_factory(Agent, fields=["user"])(data=data)
    assert not form.is_valid()
    assert "user" in form.errors


def test_new_resolved_ticket_requires_persisted_comment(customer):
    ticket = Ticket(
        subject="New", description="New", customer=customer, status=Ticket.Status.RESOLVED
    )
    with pytest.raises(ValidationError, match="comment"):
        ticket.save()


def test_resolution_requires_saved_comment(customer, author):
    ticket = make_ticket(customer)
    Comment(ticket=ticket, author=author, body="Unsaved draft")
    ticket.status = Ticket.Status.RESOLVED
    with pytest.raises(ValidationError, match="comment"):
        ticket.save()

    Comment.objects.create(ticket=ticket, author=author, body="I checked the account")
    ticket.save()
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLVED


def test_closed_ticket_cannot_reopen_but_can_be_edited(customer):
    ticket = make_ticket(customer, Ticket.Status.CLOSED)
    ticket.subject = "Corrected subject"
    ticket.save()
    assert ticket.subject == "Corrected subject"

    for new_status in (Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED):
        ticket.status = new_status
        with pytest.raises(ValidationError, match="Closed"):
            ticket.save()


def test_stale_instance_cannot_reopen_closed_ticket(customer):
    ticket = make_ticket(customer)
    stale = Ticket.objects.get(pk=ticket.pk)
    ticket.status = Ticket.Status.CLOSED
    ticket.save()
    stale.subject = "Stale edit"
    with pytest.raises(ValidationError, match="Closed"):
        stale.save()
    assert Ticket.objects.get(pk=ticket.pk).subject == "Missing receipt"


def test_other_transitions_and_choice_constraints(customer):
    ticket = make_ticket(customer)
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.priority = Ticket.Priority.HIGH
    ticket.save()
    ticket.status = Ticket.Status.CLOSED
    ticket.save()
    assert ticket.priority == 3

    # PostgreSQL enforces the status constraint even when code bypasses save().
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Ticket.objects.filter(pk=ticket.pk).update(status="invalid")


@pytest.mark.parametrize(
    ("status", "has_comment", "error"),
    [
        ("open", False, "Add a comment"),
        ("open", True, None),
        ("in_progress", False, "Add a comment"),
        ("in_progress", True, None),
        ("resolved", False, None),
        ("resolved", True, None),
        ("closed", False, "Closed"),
        ("closed", True, "Closed"),
    ],
)
def test_single_and_bulk_resolution_apply_the_same_rule(
    customer, author, status, has_comment, error
):
    ticket = make_ticket(customer)
    if has_comment:
        Comment.objects.create(ticket=ticket, author=author, body="Saved")
    # Arrange the starting state directly, without going through the workflow under test.
    Ticket.objects.filter(pk=ticket.pk).update(status=status)

    edited = Ticket.objects.get(pk=ticket.pk)
    edited.status = Ticket.Status.RESOLVED
    if error:
        with pytest.raises(ValidationError, match=error):
            edited.full_clean()
    else:
        edited.full_clean()

    result = Ticket.objects.filter(pk=ticket.pk).resolve()
    assert bool(result.skipped) == bool(error)
    assert Ticket.objects.get(pk=ticket.pk).status == (status if error else "resolved")


def test_bulk_resolve_accepts_aggregate_annotated_admin_queryset(customer, author):
    ticket = make_ticket(customer)
    Comment.objects.create(ticket=ticket, author=author, body="Investigated")
    queryset = Ticket.objects.filter(pk=ticket.pk).annotate(comment_count=Count("comments"))

    result = queryset.resolve()

    assert [item.pk for item in result.resolved] == [ticket.pk]
