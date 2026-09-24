import pytest
from django.core.exceptions import ValidationError

from tickets.models import Comment, Customer, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket():
    customer = Customer.objects.create(name="Ada", email="ada@example.test")
    return Ticket.objects.create(subject="Missing receipt", description="Issue", customer=customer)


def test_new_ticket_cannot_start_resolved(ticket):
    new_ticket = Ticket(
        subject="New", description="Issue", customer=ticket.customer, status=Ticket.Status.RESOLVED
    )
    with pytest.raises(ValidationError, match="Add a comment"):
        new_ticket.save()


def test_resolution_requires_a_saved_comment(ticket, django_user_model):
    author = django_user_model.objects.create_user(username="agent")
    comment = Comment(ticket=ticket, author=author, body="Investigated")
    ticket.status = Ticket.Status.RESOLVED
    with pytest.raises(ValidationError, match="Add a comment"):
        ticket.save()

    comment.save()
    ticket.save()
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLVED


def test_closed_ticket_cannot_reopen_or_change_details(ticket):
    ticket.status = Ticket.Status.CLOSED
    ticket.save()

    ticket.status = Ticket.Status.OPEN
    with pytest.raises(ValidationError, match="Closed tickets cannot be reopened"):
        ticket.save()

    ticket.status = Ticket.Status.CLOSED
    ticket.subject = "Changed after closure"
    with pytest.raises(ValidationError, match="Closed ticket details"):
        ticket.save()


def test_stale_edit_cannot_reopen_a_ticket_closed_by_someone_else(ticket):
    stale = Ticket.objects.get(pk=ticket.pk)
    ticket.status = Ticket.Status.CLOSED
    ticket.save()

    stale.subject = "Updated from an old form"
    with pytest.raises(ValidationError, match="Closed tickets cannot be reopened"):
        stale.save()
