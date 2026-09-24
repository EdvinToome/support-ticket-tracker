from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Exists, OuterRef
from django.db.models.functions import Lower
from django.utils import timezone

from .base_models import TimestampedModel
from .validators import attachment_path, validate_attachment


def transition_error(old: str | None, new: str, has_comment: bool) -> str | None:
    """Return the workflow error, or None when the transition is allowed."""
    if old == "closed" and new != "closed":
        return "Closed tickets cannot be reopened."
    if new == "resolved" and old != "resolved" and not has_comment:
        return "Add a comment before resolving this ticket."
    return None


class Customer(TimestampedModel):
    name = models.CharField(max_length=200, help_text="Customer's name.")
    email = models.EmailField(help_text="Customer email addresses must be unique, ignoring case.")
    company = models.CharField(max_length=200, blank=True, help_text="Optional company name.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="customer_email_ci_unique",
                violation_error_message="A customer with this email address already exists.",
            )
        ]

    def __str__(self) -> str:
        return self.name


class AgentManager(models.Manager):
    def get_queryset(self):
        # __str__ reads the user, so every agent list needs it joined.
        return super().get_queryset().select_related("user")


class Agent(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    objects = AgentManager()

    def clean(self) -> None:
        if self.user_id is None:
            return
        if (
            not self.user.is_active
            or not self.user.groups.filter(name__in=["Agent", "Admin"]).exists()
        ):
            raise ValidationError({"user": "Choose an active user in the Agent or Admin group."})

    def __str__(self) -> str:
        return self.user.get_full_name() or self.user.get_username()


@dataclass
class ResolveResult:
    resolved: list[Ticket] = field(default_factory=list)
    unchanged: list[Ticket] = field(default_factory=list)
    skipped: dict[str, list[Ticket]] = field(default_factory=dict)


class TicketQuerySet(models.QuerySet):
    def resolve(self) -> ResolveResult:
        """Resolve eligible selected tickets and report every unchanged or skipped row."""
        result = ResolveResult()
        with transaction.atomic():
            # Re-select by pk: PostgreSQL cannot lock the admin's aggregate-annotated queryset.
            locked = (
                Ticket.objects.filter(pk__in=list(self.values_list("pk", flat=True)))
                .annotate(_has_comment=Exists(Comment.objects.filter(ticket_id=OuterRef("pk"))))
                .select_for_update()
                .order_by("pk")
            )
            for ticket in locked:
                if ticket.status == Ticket.Status.RESOLVED:
                    result.unchanged.append(ticket)
                    continue
                error = transition_error(ticket.status, Ticket.Status.RESOLVED, ticket._has_comment)
                if error:
                    result.skipped.setdefault(error, []).append(ticket)
                else:
                    ticket.status = Ticket.Status.RESOLVED
                    result.resolved.append(ticket)

            Ticket.objects.filter(pk__in=[ticket.pk for ticket in result.resolved]).update(
                status=Ticket.Status.RESOLVED, updated_at=timezone.now()
            )
        return result


class Ticket(TimestampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        NORMAL = 2, "Normal"
        HIGH = 3, "High"

    subject = models.CharField(max_length=200, help_text="Short summary of the support request.")
    description = models.TextField(help_text="Describe the issue and what help is needed.")
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="tickets",
        help_text="Customer who made this request.",
    )
    assignees = models.ManyToManyField(
        Agent,
        related_name="tickets",
        blank=True,
        help_text="Assign agents, or leave blank for the unassigned queue.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        help_text=(
            "Save the first comment with Save and continue editing, then set Resolved. "
            "Closed tickets cannot reopen."
        ),
    )
    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices,
        default=Priority.NORMAL,
        help_text="Low, Normal, or High urgency; High sorts first.",
    )

    objects = TicketQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["open", "in_progress", "resolved", "closed"]),
                name="ticket_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__in=[1, 2, 3]), name="ticket_valid_priority"
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="ticket_queue_index")]

    def clean(self) -> None:
        old_status = (
            Ticket.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if self.pk
            else None
        )
        has_comment = (
            self.status == Ticket.Status.RESOLVED
            and self.pk is not None
            and Comment.objects.filter(ticket_id=self.pk).exists()
        )
        error = transition_error(old_status, self.status, has_comment)
        if error:
            raise ValidationError({"status": error})

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.subject


class Comment(TimestampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField(help_text="Record the support update before resolving the ticket.")
    attachment = models.FileField(
        upload_to=attachment_path,
        validators=[validate_attachment],
        blank=True,
        help_text="Optional PDF, PNG, or JPEG file, up to 3 MiB.",
    )

    def __str__(self) -> str:
        return f"Comment on {self.ticket}"
