import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import openai
import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.cache import cache
from django.test import RequestFactory

from tickets.admin_views import assistant_view
from tickets.assistant import AssistantUnavailable, ask_form_question, form_metadata
from tickets.models import Customer, Ticket


@pytest.fixture(autouse=True)
def empty_rate_limits():
    cache.clear()


@pytest.fixture
def fixed_clock(monkeypatch):
    """Keep rate-limit windows from rolling over mid-test."""
    monkeypatch.setattr("tickets.admin_views.time.time", lambda: 1_800_000_000.0)


@pytest.fixture
def provider(monkeypatch, settings):
    settings.OPENAI_API_KEY = "test-key"
    stub = Mock(return_value="A safe answer")
    monkeypatch.setattr("tickets.admin_views.ask_form_question", stub)
    return stub


def ask(user, **data):
    request = RequestFactory().post("/admin/form-help/", {"model": "ticket", **data})
    request.user = user
    request._dont_enforce_csrf_checks = True
    return assistant_view(request)


def superuser(pk=10):
    user = get_user_model()(username=f"admin{pk}", is_staff=True, is_superuser=True)
    user.pk = pk
    return user


def stub_openai(monkeypatch, *, response=None, error=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.create.return_value = response
    client.responses.create.side_effect = error
    monkeypatch.setattr("tickets.assistant.OpenAI", Mock(return_value=client))
    return client


def test_registered_admin_forms_supply_real_choice_and_inline_metadata():
    request = RequestFactory().get("/admin/tickets/ticket/add/")
    request.user = superuser()

    ticket_metadata = form_metadata(admin.site._registry[Ticket], request)
    ticket_fields = {field["name"]: field for field in ticket_metadata["fields"]}
    assert ticket_fields["status"]["read_only"] is True
    assert "comment" in ticket_fields["status"]["help_text"].lower()
    assert ticket_fields["priority"]["choices"] == [(1, "Low"), (2, "Normal"), (3, "High")]
    assert ticket_fields["assignees"]["choices"] == []
    assert [field["name"] for field in ticket_metadata["inlines"][0]["fields"]] == [
        "body",
        "attachment",
        "author",
        "created_at",
    ]

    customer_metadata = form_metadata(
        admin.site._registry[Customer], request, Customer(name="Private name")
    )
    assert all(field["read_only"] for field in customer_metadata["inlines"][0]["fields"])
    assert "Private name" not in str(customer_metadata)


def test_prompt_carries_field_definitions_and_question_only(monkeypatch):
    client = stub_openai(
        monkeypatch, response=SimpleNamespace(status="completed", output_text="Pick High.")
    )
    fields = {"fields": [{"name": "priority", "choices": [(3, "High")], "help_text": "Urgency"}]}

    answer = ask_form_question("ticket", fields, "What is high?", "test-key")

    assert answer == "Pick High."
    kwargs = client.responses.create.call_args.kwargs
    assert "Use only the field definitions" in kwargs["instructions"]
    assert "priority" in kwargs["input"] and "Urgency" in kwargs["input"]
    assert "What is high?" in kwargs["input"]
    assert "test-key" not in kwargs["input"]


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (SimpleNamespace(status="incomplete", output_text="partial"), None, "no complete answer"),
        (SimpleNamespace(status="completed", output_text="  "), None, "no complete answer"),
        (None, openai.APITimeoutError(request=Mock()), "timeout"),
        (
            None,
            openai.RateLimitError("quota", response=Mock(status_code=429, headers={}), body=None),
            "quota",
        ),
        (None, openai.APIConnectionError(request=Mock()), "provider error"),
    ],
)
def test_provider_failures_become_assistant_unavailable(monkeypatch, response, error, message):
    stub_openai(monkeypatch, response=response, error=error)
    with pytest.raises(AssistantUnavailable, match=message):
        ask_form_question("ticket", {}, "Help?", "test-key")


def test_endpoint_requires_csrf_and_staff_login():
    request = RequestFactory().post("/admin/form-help/", {"model": "ticket", "question": "Help?"})
    request.user = AnonymousUser()
    assert assistant_view(request).status_code == 403

    assert ask(AnonymousUser(), question="Help?").status_code == 302


def test_endpoint_validates_model_and_question(provider):
    user = superuser()
    assert ask(user, model="comment", question="Help?").status_code == 400
    assert ask(user, question=" ").status_code == 400
    assert ask(user, question="x" * 1001).status_code == 400
    provider.assert_not_called()


@pytest.mark.django_db
def test_endpoint_denies_forms_the_user_cannot_open(provider):
    customer = Customer.objects.create(name="Customer", email="customer@example.test")
    ticket = Ticket.objects.create(subject="Issue", description="Details", customer=customer)
    viewer = get_user_model().objects.create_user("viewer", is_staff=True)
    viewer.groups.add(Group.objects.get(name="Viewer"))
    ungrouped = get_user_model().objects.create_user("ungrouped", is_staff=True)

    assert ask(viewer, question="Help?").status_code == 403  # no add permission
    assert ask(ungrouped, object_id=str(ticket.pk), question="Help?").status_code == 403
    provider.assert_not_called()


@pytest.mark.django_db
def test_viewer_can_ask_about_visible_ticket_without_sending_record_values(provider):
    viewer = get_user_model().objects.create_user("viewer", is_staff=True)
    viewer.groups.add(Group.objects.get(name="Viewer"))
    customer = Customer.objects.create(name="Private customer", email="private@example.test")
    ticket = Ticket.objects.create(
        subject="Secret complaint", description="Sensitive ticket body", customer=customer
    )

    response = ask(viewer, object_id=str(ticket.pk), question="What is status?")

    assert response.status_code == 200
    metadata = provider.call_args.args[1]
    assert all(field["read_only"] for field in metadata["fields"])
    for value in ("Secret complaint", "Sensitive ticket body", "Private customer"):
        assert value not in str(metadata)


def test_endpoint_reports_missing_key(provider, settings):
    settings.OPENAI_API_KEY = ""
    response = ask(superuser(), question="Help?")
    assert response.status_code == 503
    assert "not configured" in json.loads(response.content)["error"]


def test_endpoint_reports_provider_unavailability(provider):
    provider.side_effect = AssistantUnavailable("Assistant unavailable: provider error.")
    response = ask(superuser(), question="Help?")
    assert response.status_code == 503
    assert json.loads(response.content)["error"] == "Assistant unavailable: provider error."


def test_endpoint_limits_each_user_to_five_per_minute(provider, fixed_clock):
    statuses = [ask(superuser(), question="Help?").status_code for _ in range(6)]
    assert statuses == [200] * 5 + [429]
    assert ask(superuser(pk=11), question="Help?").status_code == 200


def test_endpoint_enforces_global_daily_limit(provider, fixed_clock):
    statuses = [ask(superuser(pk=i // 5), question="Help?").status_code for i in range(201)]
    assert statuses == [200] * 200 + [429]
    assert provider.call_count == 200
