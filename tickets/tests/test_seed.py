from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Exists, OuterRef

from tickets.models import Agent, Comment, Customer, Ticket

SMALL_SEED = {
    "customers": 5,
    "agents": 3,
    "tickets": 12,
    "comments": 24,
    "attachments": 2,
}


def seed(**options):
    return call_command("seed_demo", stdout=StringIO(), **(SMALL_SEED | options))


@pytest.mark.django_db
def test_seed_creates_relationships_workflow_and_files():
    Group.objects.get_or_create(name="Agent")

    seed()

    assert Customer.objects.count() == 5
    assert Agent.objects.count() == 3
    assert Ticket.objects.count() == 12
    assert Comment.objects.count() == 24
    assert Comment.objects.exclude(attachment="").count() == 2
    users = get_user_model().objects.filter(username__startswith="seed-agent-")
    assert users.count() == 3
    assert all(
        user.is_active and user.is_staff and not user.has_usable_password() for user in users
    )
    assert all(user.groups.filter(name="Agent").exists() for user in users)
    assert all(user.email.endswith("@example.test") for user in users)

    missing_comment = Ticket.objects.filter(status=Ticket.Status.RESOLVED).exclude(
        Exists(Comment.objects.filter(ticket_id=OuterRef("pk")))
    )
    assert not missing_comment.exists()
    assert Ticket.objects.filter(status=Ticket.Status.OPEN, comments__isnull=True).exists()
    assert Ticket.objects.filter(assignees__isnull=True).exists()
    assert Ticket.objects.filter(assignees__isnull=False).exists()
    assert Ticket.objects.filter(assignees__isnull=False).distinct().count() > 0

    for comment in Comment.objects.exclude(attachment=""):
        with comment.attachment.open("rb") as file:
            assert file.read(8).startswith((b"%PDF-", b"\x89PNG\r\n\x1a\n"))


@pytest.mark.django_db
def test_repeat_without_reset_fails_and_reset_preserves_role_login(
    django_capture_on_commit_callbacks,
):
    Group.objects.get_or_create(name="Agent")
    role_login = get_user_model().objects.create_user(username="review-agent", password="secret")
    seed()
    get_user_model().objects.create_user(username="seed-unused", password="unused")
    old_file = Comment.objects.exclude(attachment="").first().attachment
    old_name = old_file.name
    assert old_file.storage.exists(old_name)
    Customer.objects.create(name="Existing customer", email="existing@example.test")

    with pytest.raises(CommandError, match="--reset"):
        seed()

    with django_capture_on_commit_callbacks(execute=True):
        seed(reset=True, customers=2, agents=1, tickets=3, comments=3, attachments=0)

    assert Customer.objects.count() == 2
    assert Agent.objects.count() == 1
    assert Ticket.objects.count() == 3
    assert Comment.objects.count() == 3
    assert not old_file.storage.exists(old_name)
    assert get_user_model().objects.filter(pk=role_login.pk).exists()
    assert get_user_model().objects.filter(username__startswith="seed-agent-").count() == 1
    assert not get_user_model().objects.filter(username="seed-unused").exists()


@pytest.mark.django_db
def test_seed_is_reproducible_after_reset():
    Group.objects.get_or_create(name="Agent")
    seed(attachments=0)

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

    first = snapshot()
    seed(reset=True, attachments=0)
    assert snapshot() == first
