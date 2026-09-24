from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Exists, OuterRef

from tickets.models import Agent, Comment, Customer, Ticket

pytestmark = pytest.mark.django_db

SMALL_SEED = {"customers": 5, "agents": 3, "tickets": 12, "comments": 24, "attachments": 2}


def seed(**options):
    return call_command("seed_demo", stdout=StringIO(), **(SMALL_SEED | options))


def test_seed_creates_valid_workflow_data_and_files():
    seed()

    assert Customer.objects.count() == 5
    assert Ticket.objects.count() == 12
    assert Comment.objects.count() == 24
    users = get_user_model().objects.filter(username__startswith="seed-agent-")
    assert users.count() == Agent.objects.count() == 3
    assert all(user.groups.filter(name="Agent").exists() for user in users)
    assert not any(user.has_usable_password() for user in users)

    # bulk_create bypasses Ticket.save(), so check the workflow invariant directly.
    assert not Ticket.objects.filter(status=Ticket.Status.RESOLVED).exclude(
        Exists(Comment.objects.filter(ticket_id=OuterRef("pk")))
    )
    attachments = Comment.objects.exclude(attachment="")
    assert attachments.count() == 2
    for comment in attachments:
        with comment.attachment.open("rb") as file:
            assert file.read(8).startswith((b"%PDF-", b"\x89PNG\r\n\x1a\n"))


def test_repeat_needs_reset_and_reset_keeps_reviewer_logins(django_capture_on_commit_callbacks):
    reviewer = get_user_model().objects.create_user(username="review-agent", password="secret")
    reviewer.groups.add(Group.objects.get(name="Agent"))
    reviewer_profile = Agent.objects.create(user=reviewer)
    seed()
    old_file = Comment.objects.exclude(attachment="").first().attachment

    with pytest.raises(CommandError, match="--reset"):
        seed()

    with django_capture_on_commit_callbacks(execute=True):
        seed(reset=True, customers=2, agents=1, tickets=3, comments=3, attachments=0)

    assert Ticket.objects.count() == 3
    assert not old_file.storage.exists(old_file.name)
    assert Agent.objects.filter(pk=reviewer_profile.pk).exists()
    assert get_user_model().objects.filter(username__startswith="seed-agent-").count() == 1


def test_failed_reset_keeps_existing_rows_and_attachments(django_capture_on_commit_callbacks):
    seed()
    ticket_ids = list(Ticket.objects.values_list("pk", flat=True))
    attachment = Comment.objects.exclude(attachment="").first().attachment

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(CommandError, match="too small"):
            seed(reset=True, tickets=100, comments=0, attachments=0)

    assert list(Ticket.objects.values_list("pk", flat=True)) == ticket_ids
    assert attachment.storage.exists(attachment.name)


def test_seed_is_reproducible_after_reset():
    def snapshot():
        return list(
            Ticket.objects.order_by("pk").values_list(
                "customer__email",
                "subject",
                "description",
                "status",
                "priority",
                "created_at",
                "updated_at",
            )
        )

    seed(attachments=0)
    first = snapshot()
    seed(reset=True, attachments=0)
    assert snapshot() == first
