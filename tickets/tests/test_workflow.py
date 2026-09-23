import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count

from tickets.models import Agent, Comment, Customer, Ticket, transition_error


@pytest.fixture
def author(db):
    return get_user_model().objects.create_user(username="author", password="unused")


@pytest.fixture
def customer(db):
    return Customer.objects.create(name="Ada", email="ada@example.com")


def make_ticket(customer, status=Ticket.Status.OPEN):
    return Ticket.objects.create(
        subject="Missing receipt", description="Please resend it", customer=customer, status=status
    )


@pytest.mark.django_db
def test_customer_email_is_unique_without_case_sensitivity(customer):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Customer.objects.create(name="Another Ada", email="ADA@example.com")


@pytest.mark.django_db
def test_agent_requires_active_user_in_agent_or_admin_group(author):
    from django.contrib.auth.models import Group

    agent = Agent(user=author)
    with pytest.raises(ValidationError):
        agent.full_clean()

    group, _ = Group.objects.get_or_create(name="Agent")
    author.groups.add(group)
    agent.full_clean()
    author.is_active = False
    author.save()
    with pytest.raises(ValidationError):
        agent.full_clean()


@pytest.mark.django_db
def test_new_resolved_ticket_requires_persisted_comment(customer):
    ticket = Ticket(
        subject="New", description="New", customer=customer, status=Ticket.Status.RESOLVED
    )
    with pytest.raises(ValidationError, match="comment"):
        ticket.save()


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_closed_ticket_cannot_reopen_but_can_be_edited(customer):
    ticket = make_ticket(customer, Ticket.Status.CLOSED)
    ticket.subject = "Corrected subject"
    ticket.save()
    assert ticket.subject == "Corrected subject"

    for new_status in (Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED):
        ticket.status = new_status
        with pytest.raises(ValidationError, match="Closed"):
            ticket.save()


@pytest.mark.django_db
def test_stale_instance_cannot_reopen_closed_ticket(customer):
    ticket = make_ticket(customer)
    stale = Ticket.objects.get(pk=ticket.pk)
    ticket.status = Ticket.Status.CLOSED
    ticket.save()
    stale.subject = "Stale edit"
    with pytest.raises(ValidationError, match="Closed"):
        stale.save()
    assert Ticket.objects.get(pk=ticket.pk).subject == "Missing receipt"


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_bulk_resolve_returns_partial_success(customer, author):
    ready = make_ticket(customer)
    Comment.objects.create(ticket=ready, author=author, body="Investigated")
    already = make_ticket(customer)
    Comment.objects.create(ticket=already, author=author, body="Already fixed")
    already.status = Ticket.Status.RESOLVED
    already.save()
    closed = make_ticket(customer, Ticket.Status.CLOSED)
    empty = make_ticket(customer)

    result = Ticket.objects.filter(pk__in=[ready.pk, already.pk, closed.pk, empty.pk]).resolve()

    assert [ticket.pk for ticket in result.resolved] == [ready.pk]
    assert [ticket.pk for ticket in result.unchanged] == [already.pk]
    assert {
        reason: [ticket.pk for ticket in tickets] for reason, tickets in result.skipped.items()
    } == {
        "Closed tickets cannot be reopened.": [closed.pk],
        "Add a comment before resolving this ticket.": [empty.pk],
    }
    assert Ticket.objects.get(pk=ready.pk).status == Ticket.Status.RESOLVED
    assert Ticket.objects.get(pk=closed.pk).status == Ticket.Status.CLOSED


@pytest.mark.django_db
def test_bulk_resolve_accepts_aggregate_annotated_admin_queryset(customer, author):
    ticket = make_ticket(customer)
    Comment.objects.create(ticket=ticket, author=author, body="Investigated")
    queryset = Ticket.objects.filter(pk=ticket.pk).annotate(comment_count=Count("comments"))

    result = queryset.resolve()

    assert [item.pk for item in result.resolved] == [ticket.pk]


@pytest.mark.django_db
def test_bulk_and_single_ticket_use_same_transition_rule(customer, author):
    for status in Ticket.Status.values:
        for has_comment in (False, True):
            ticket = make_ticket(customer)
            if has_comment:
                Comment.objects.create(ticket=ticket, author=author, body="Saved")
            if status != Ticket.Status.OPEN:
                # Set up existing states without calling the workflow path under test.
                Ticket.objects.filter(pk=ticket.pk).update(status=status)
            error = transition_error(status, Ticket.Status.RESOLVED, has_comment)
            ticket = Ticket.objects.get(pk=ticket.pk)
            ticket.status = Ticket.Status.RESOLVED
            if error:
                with pytest.raises(ValidationError, match=error.split(".")[0]):
                    ticket.full_clean()
            else:
                ticket.full_clean()

            result = Ticket.objects.filter(pk=ticket.pk).resolve()
            if status == Ticket.Status.RESOLVED:
                assert [item.pk for item in result.unchanged] == [ticket.pk]
            elif error:
                assert [item.pk for item in result.skipped[error]] == [ticket.pk]
            else:
                assert [item.pk for item in result.resolved] == [ticket.pk]
