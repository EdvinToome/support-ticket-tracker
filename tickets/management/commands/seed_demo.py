"""Create a fixed, realistic support queue for a live Django admin review."""

from datetime import datetime, timedelta, timezone
from functools import partial
from io import BytesIO
from random import Random

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef
from faker import Faker
from PIL import Image, ImageDraw

from tickets.models import Agent, Comment, Customer, Ticket
from tickets.validators import validate_attachment

SEED = 20260923
REFERENCE_DATE = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
SCENARIOS = (
    ("Cannot sign in", "the sign-in link returns to the login page"),
    ("Invoice copy needed", "the latest invoice is missing from the account"),
    ("Payment confirmation missing", "a completed payment is not shown in billing"),
    ("Update contact details", "the saved contact details are out of date"),
    ("Download is unavailable", "the account download returns an error"),
    ("Incorrect invoice amount", "the billed amount differs from the agreed price"),
    ("Request access for a teammate", "a teammate cannot join the account"),
    ("Account settings question", "the required setting is difficult to find"),
    ("Order status request", "the order has no recent status update"),
    ("Duplicate charge reported", "two charges appear for the same order"),
    ("Profile information is wrong", "the profile shows outdated information"),
    ("Confirm cancellation", "the cancellation has not been confirmed"),
)
COMMENT_UPDATES = (
    'Checked {account} records for the "{subject}" request and recorded the next step.',
    'Asked {customer} for details about the "{subject}" request.',
    'Shared an update with {customer} about the "{subject}" request.',
    'Reviewed {account} records for "{subject}" and followed up.',
    'Confirmed the outcome of the "{subject}" request with {customer}.',
)


def _reset_demo() -> None:
    old_files = list(Comment.objects.exclude(attachment="").values_list("attachment", flat=True))
    Comment.objects.all().delete()
    Ticket.objects.all().delete()
    Customer.objects.all().delete()
    Agent.objects.all().delete()
    get_user_model().objects.filter(username__startswith="seed-").delete()
    for name in old_files:
        transaction.on_commit(partial(default_storage.delete, name))


def _has_existing_data() -> bool:
    return (
        Customer.objects.exists()
        or Agent.objects.exists()
        or Ticket.objects.exists()
        or Comment.objects.exists()
        or get_user_model().objects.filter(username__startswith="seed-").exists()
    )


def _make_customers(count: int, rng: Random, fake: Faker) -> list[Customer]:
    customers = []
    dates = []
    for index in range(count):
        dates.append(REFERENCE_DATE - timedelta(days=rng.randint(200, 540)))
        customers.append(
            Customer(
                name=fake.name(),
                email=f"seed-customer-{index + 1:04d}@example.test",
                company=fake.company() if rng.random() < 0.4 else "",
            )
        )
    Customer.objects.bulk_create(customers, batch_size=500)
    for customer, created_at in zip(customers, dates, strict=True):
        customer.created_at = created_at
    Customer.objects.bulk_update(customers, ["created_at"], batch_size=500)
    return customers


def _make_agents(count: int, group: Group, fake: Faker) -> list[Agent]:
    user_model = get_user_model()
    users = []
    for index in range(count):
        user = user_model(
            username=f"seed-agent-{index + 1:03d}",
            email=f"seed-agent-{index + 1:03d}@example.test",
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            date_joined=REFERENCE_DATE - timedelta(days=365 - index),
            is_active=True,
            is_staff=True,
        )
        user.set_unusable_password()
        users.append(user)
    user_model.objects.bulk_create(users, batch_size=500)
    group.user_set.add(*users)
    agents = Agent.objects.bulk_create([Agent(user=user) for user in users], batch_size=500)
    return agents


def _ticket_date(rng: Random) -> datetime:
    return REFERENCE_DATE - timedelta(
        days=rng.randrange(180), hours=rng.randrange(24), minutes=rng.randrange(60)
    )


def _make_tickets(
    count: int, customers: list[Customer], agents: list[Agent], rng: Random
) -> list[Ticket]:
    tickets = []
    dates = []
    for index in range(count):
        customer = rng.choice(customers)
        subject, issue = rng.choice(SCENARIOS)
        status = (
            Ticket.Status.OPEN
            if index == 0
            else rng.choices(Ticket.Status.values, weights=[45, 25, 20, 10])[0]
        )
        created_at = _ticket_date(rng)
        updated_at = min(REFERENCE_DATE, created_at + timedelta(hours=rng.randint(1, 72)))
        dates.append((created_at, updated_at))
        context = f"at {customer.company}" if customer.company else "on a personal account"
        description = f"{customer.name} {context} reports that {issue}. Please investigate."
        tickets.append(
            Ticket(
                subject=subject,
                description=description,
                customer=customer,
                status=status,
                priority=rng.choices(Ticket.Priority.values, weights=[25, 55, 20])[0],
            )
        )
    Ticket.objects.bulk_create(tickets, batch_size=500)
    for ticket, (created_at, updated_at) in zip(tickets, dates, strict=True):
        ticket.created_at = created_at
        ticket.updated_at = updated_at

    assignments = []
    through = Ticket.assignees.through
    for index, ticket in enumerate(tickets):
        if index == 0 or rng.random() < 0.15:
            continue
        selected = rng.sample(agents, k=2 if len(agents) >= 2 and rng.random() < 0.1 else 1)
        assignments.extend(through(ticket_id=ticket.pk, agent_id=agent.pk) for agent in selected)
    through.objects.bulk_create(assignments, batch_size=500)
    return tickets


def _make_comments(
    count: int, tickets: list[Ticket], agents: list[Agent], rng: Random
) -> list[Comment]:
    if not count:
        return []
    required = [ticket for ticket in tickets if ticket.status == Ticket.Status.RESOLVED]
    if len(required) > count:
        raise CommandError("The comment count is too small for the resolved tickets.")

    eligible = tickets[1:] if len(tickets) > 1 else tickets
    weights = {
        Ticket.Status.OPEN: 1,
        Ticket.Status.IN_PROGRESS: 3,
        Ticket.Status.RESOLVED: 4,
        Ticket.Status.CLOSED: 4,
    }
    remaining = rng.choices(
        eligible, weights=[weights[ticket.status] for ticket in eligible], k=count - len(required)
    )
    comments = []
    dates = []
    for ticket in [*required, *remaining]:
        author = rng.choice(agents).user
        seconds = int((REFERENCE_DATE - ticket.created_at).total_seconds())
        created_at = ticket.created_at + timedelta(seconds=rng.randrange(seconds + 1))
        ticket.updated_at = max(ticket.updated_at, created_at)
        dates.append(created_at)
        comments.append(
            Comment(
                ticket=ticket,
                author=author,
                body=rng.choice(COMMENT_UPDATES).format(
                    account=ticket.customer.company or "the personal account",
                    customer=ticket.customer.name,
                    subject=ticket.subject.lower(),
                ),
            )
        )
    Comment.objects.bulk_create(comments, batch_size=500)
    for comment, created_at in zip(comments, dates, strict=True):
        comment.created_at = created_at
    return comments


def _sample_attachment(image_format: str) -> bytes:
    image = Image.new("RGB", (320, 96), "white")
    ImageDraw.Draw(image).text((16, 36), "Synthetic support attachment", fill="black")
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _make_attachments(comments: list[Comment], count: int, rng: Random) -> None:
    if not count:
        return
    pdf = _sample_attachment("PDF")
    png = _sample_attachment("PNG")
    for index, comment in enumerate(rng.sample(comments, count)):
        extension, data = ("pdf", pdf) if index % 2 == 0 else ("png", png)
        name = f"seed-attachment-{index + 1:03d}.{extension}"
        content = ContentFile(data, name=name)
        validate_attachment(content)
        comment.attachment.save(name, content, save=True)


def _assert_seed_counts(counts: dict[str, int]) -> None:
    actual = {
        "customers": Customer.objects.count(),
        "agents": Agent.objects.count(),
        "tickets": Ticket.objects.count(),
        "comments": Comment.objects.count(),
        "attachments": Comment.objects.exclude(attachment="").count(),
    }
    if actual != counts:
        raise CommandError(f"Seed counts differ from requested counts: {actual}.")
    missing_comment = Ticket.objects.filter(status=Ticket.Status.RESOLVED).exclude(
        Exists(Comment.objects.filter(ticket_id=OuterRef("pk")))
    )
    if missing_comment.exists():
        raise CommandError("A resolved ticket has no saved comment.")


class Command(BaseCommand):
    help = "Create reproducible synthetic support data; --reset deletes existing demo domain data."

    def add_arguments(self, parser):
        for name, default in (
            ("customers", 200),
            ("agents", 20),
            ("tickets", 2000),
            ("comments", 6000),
            ("attachments", 50),
        ):
            parser.add_argument(f"--{name}", type=int, default=default)
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **options):
        counts = {
            name: options[name]
            for name in ("customers", "agents", "tickets", "comments", "attachments")
        }
        if any(value < 0 for value in counts.values()):
            raise CommandError("Seed counts cannot be negative.")
        if counts["tickets"] and not counts["customers"]:
            raise CommandError("Tickets require at least one customer.")
        if (counts["tickets"] or counts["comments"]) and not counts["agents"]:
            raise CommandError("Tickets and comments require at least one agent.")
        if counts["comments"] and not counts["tickets"]:
            raise CommandError("Comments require tickets.")
        if counts["attachments"] > counts["comments"]:
            raise CommandError("Attachments cannot exceed comments.")

        rng = Random(SEED)
        fake = Faker("en_US")
        fake.seed_instance(SEED)
        with transaction.atomic():
            group = Group.objects.get(name="Agent")
            if options["reset"]:
                _reset_demo()
            elif _has_existing_data():
                raise CommandError("Domain data already exists. Use --reset to replace it.")

            customers = _make_customers(counts["customers"], rng, fake)
            agents = _make_agents(counts["agents"], group, fake)
            tickets = _make_tickets(counts["tickets"], customers, agents, rng)
            comments = _make_comments(counts["comments"], tickets, agents, rng)
            Ticket.objects.bulk_update(tickets, ["created_at", "updated_at"], batch_size=500)
            Comment.objects.bulk_update(comments, ["created_at"], batch_size=500)
            _make_attachments(comments, counts["attachments"], rng)
            _assert_seed_counts(counts)

        self.stdout.write(self.style.SUCCESS(f"Seeded {counts}."))
