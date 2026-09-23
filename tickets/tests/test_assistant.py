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


def test_form_metadata_includes_readonly_fields_and_inline_without_record_values():
    from tickets.assistant import form_metadata
    from tickets.models import Comment, Ticket

    class CommentInline(admin.TabularInline):
        model = Comment
        fields = ("body", "attachment", "author", "created_at")
        readonly_fields = ("author", "created_at")

    class TicketMetadataAdmin(admin.ModelAdmin):
        fields = ("subject", "customer", "status", "priority")
        readonly_fields = ("subject",)
        inlines = [CommentInline]

    request = RequestFactory().get("/admin/tickets/ticket/7/change/")
    request.user = get_user_model()(username="staff", is_staff=True, is_superuser=True)
    model_admin = TicketMetadataAdmin(Ticket, admin.site)

    obj = Ticket(subject="secret customer body", description="private details", customer_id=123)
    metadata = form_metadata(model_admin, request, obj)

    fields = {field["name"]: field for field in metadata["fields"]}
    assert fields["subject"]["type"] == "CharField"
    assert fields["priority"]["choices"] == [(1, "Low"), (2, "Normal"), (3, "High")]
    assert "comment" in fields["status"]["help_text"].lower()
    assert fields["customer"]["choices"] == []
    inline = {field["name"]: field for field in metadata["inlines"][0]["fields"]}
    assert inline["author"]["type"] == "ForeignKey"
    assert inline["body"]["type"] == "CharField"
    assert "staff" not in str(metadata)
    assert "secret customer body" not in str(metadata)
    assert "private details" not in str(metadata)


def test_viewer_metadata_marks_visible_fields_readonly():
    from tickets.assistant import form_metadata
    from tickets.models import Customer

    class CustomerViewerAdmin(admin.ModelAdmin):
        fields = ("name", "email", "company")

        def has_change_permission(self, request, obj=None):
            return False

    request = RequestFactory().get("/admin/tickets/customer/7/change/")
    request.user = get_user_model()(username="viewer", is_staff=True)
    obj = Customer(name="Private name", email="private@example.test")

    metadata = form_metadata(CustomerViewerAdmin(Customer, admin.site), request, obj)

    assert [field["name"] for field in metadata["fields"]] == ["name", "email", "company"]
    assert all(field["read_only"] for field in metadata["fields"])
    assert "private@example.test" not in str(metadata)


def test_registered_admin_forms_supply_real_inline_and_choice_metadata():
    from tickets.assistant import form_metadata
    from tickets.models import Customer, Ticket

    request = RequestFactory().get("/admin/tickets/ticket/add/")
    request.user = get_user_model()(username="admin", is_staff=True, is_superuser=True)

    ticket_metadata = form_metadata(admin.site._registry[Ticket], request)
    ticket_fields = {field["name"]: field for field in ticket_metadata["fields"]}
    assert ticket_fields["status"]["read_only"] is True
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
    assert [field["name"] for field in customer_metadata["inlines"][0]["fields"]] == [
        "subject",
        "status",
        "priority",
        "created_at",
    ]
    assert all(field["read_only"] for field in customer_metadata["inlines"][0]["fields"])
    assert "Private name" not in str(customer_metadata)


def _stub_openai(monkeypatch, *, response=None, error=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.create.return_value = response
    client.responses.create.side_effect = error
    monkeypatch.setattr("tickets.assistant.OpenAI", Mock(return_value=client))
    return client


def test_provider_sends_only_form_metadata_and_question(monkeypatch, settings):
    from tickets.assistant import ask_form_question

    settings.OPENAI_API_KEY = "test-key"
    settings.OPENAI_MODEL = "gpt-6-luna"
    response = SimpleNamespace(status="completed", output_text="Choose High for urgent work.")
    create = Mock(return_value=response)
    client = MagicMock()
    client.responses.create = create
    client.__enter__.return_value = client
    client_class = Mock(return_value=client)
    monkeypatch.setattr("tickets.assistant.OpenAI", client_class)
    fields = [
        {
            "name": "priority",
            "type": "TypedChoiceField",
            "required": True,
            "choices": [(1, "Low"), (3, "High")],
            "help_text": "Urgency",
        }
    ]

    answer = ask_form_question("ticket", fields, "What is high?", settings.OPENAI_API_KEY)

    assert answer == "Choose High for urgent work."
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "gpt-6-luna"
    assert kwargs["reasoning"] == {"effort": "none"}
    assert kwargs["store"] is False
    assert kwargs["max_output_tokens"] == 500
    assert "Use only the field definitions" in kwargs["instructions"]
    assert "Use only the field definitions" not in kwargs["input"]
    assert "priority" in kwargs["input"]
    assert "High" in kwargs["input"]
    assert "What is high?" in kwargs["input"]
    assert "test-key" not in kwargs["input"]
    assert "secret customer body" not in kwargs["input"]
    assert client_class.call_args.kwargs == {
        "api_key": "test-key",
        "timeout": 10.0,
        "max_retries": 0,
    }
    client.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "status,output", [("incomplete", "partial"), ("completed", ""), ("completed", "   ")]
)
def test_provider_rejects_incomplete_or_empty_output(monkeypatch, settings, status, output):
    from tickets.assistant import AssistantUnavailable, ask_form_question

    settings.OPENAI_MODEL = "gpt-6-luna"
    response = SimpleNamespace(status=status, output_text=output)
    _stub_openai(monkeypatch, response=response)

    with pytest.raises(AssistantUnavailable):
        ask_form_question("ticket", [], "Help?", "test-key")


def test_provider_translates_timeout_without_leaking_exception(monkeypatch, settings):
    from tickets.assistant import AssistantUnavailable, ask_form_question

    settings.OPENAI_MODEL = "gpt-6-luna"
    _stub_openai(monkeypatch, error=openai.APITimeoutError(request=Mock()))

    with pytest.raises(AssistantUnavailable) as exc:
        ask_form_question("ticket", [], "Help?", "test-key")

    assert "timeout" in str(exc.value).lower()
    assert "test-key" not in str(exc.value)


def test_provider_translates_quota_error(monkeypatch, settings):
    from tickets.assistant import AssistantUnavailable, ask_form_question

    settings.OPENAI_MODEL = "gpt-6-luna"
    _stub_openai(
        monkeypatch,
        error=openai.RateLimitError("quota", response=Mock(status_code=429, headers={}), body=None),
    )

    with pytest.raises(AssistantUnavailable) as exc:
        ask_form_question("ticket", [], "Help?", "test-key")

    assert "quota" in str(exc.value).lower()


def test_provider_translates_connection_error(monkeypatch, settings):
    from tickets.assistant import AssistantUnavailable, ask_form_question

    settings.OPENAI_MODEL = "gpt-6-luna"
    _stub_openai(monkeypatch, error=openai.APIConnectionError(request=Mock()))

    with pytest.raises(AssistantUnavailable, match="provider error"):
        ask_form_question("ticket", [], "Help?", "test-key")


def test_provider_does_not_hide_programming_errors(monkeypatch, settings):
    from tickets.assistant import ask_form_question

    settings.OPENAI_MODEL = "gpt-6-luna"
    _stub_openai(monkeypatch, error=ValueError("bad code"))

    with pytest.raises(ValueError, match="bad code"):
        ask_form_question("ticket", [], "Help?", "test-key")


def test_anonymous_user_cannot_use_endpoint():
    from tickets.admin_views import assistant_view

    request = RequestFactory().post("/admin/form-help/", {"model": "ticket", "question": "Help?"})
    request.user = AnonymousUser()
    request._dont_enforce_csrf_checks = True
    response = assistant_view(request)

    assert response.status_code == 302


def test_endpoint_requires_csrf_token():
    from tickets.admin_views import assistant_view

    request = RequestFactory().post("/admin/form-help/", {"model": "ticket", "question": "Help?"})
    request.user = AnonymousUser()

    assert assistant_view(request).status_code == 403


def _staff_request(data, user_id=7):
    request = RequestFactory().post("/admin/form-help/", data)
    request.user = SimpleNamespace(pk=user_id, is_active=True, is_staff=True)
    request._dont_enforce_csrf_checks = True
    return request


def _permit_ticket_add(monkeypatch):
    from tickets.models import Ticket

    model_admin = Mock()
    model_admin.has_add_permission.return_value = True
    monkeypatch.setitem(admin.site._registry, Ticket, model_admin)
    monkeypatch.setattr("tickets.admin_views.form_metadata", Mock(return_value={"fields": []}))
    return model_admin


def test_endpoint_forbids_unviewable_change_form(monkeypatch, settings):
    from tickets.admin_views import assistant_view
    from tickets.models import Ticket

    settings.OPENAI_API_KEY = "test-key"
    model_admin = Mock()
    model_admin.get_object.return_value = object()
    model_admin.has_view_or_change_permission.return_value = False
    monkeypatch.setitem(admin.site._registry, Ticket, model_admin)
    provider = Mock()
    monkeypatch.setattr("tickets.admin_views.ask_form_question", provider)

    response = assistant_view(
        _staff_request({"model": "ticket", "object_id": "42", "question": "Help?"})
    )

    assert response.status_code == 403
    provider.assert_not_called()


def test_endpoint_forbids_unavailable_add_form(monkeypatch, settings):
    from tickets.admin_views import assistant_view
    from tickets.models import Ticket

    settings.OPENAI_API_KEY = "test-key"
    model_admin = Mock()
    model_admin.has_add_permission.return_value = False
    monkeypatch.setitem(admin.site._registry, Ticket, model_admin)

    response = assistant_view(_staff_request({"model": "ticket", "question": "Help?"}))
    assert response.status_code == 403


def test_endpoint_validates_model_and_question(monkeypatch, settings):
    from tickets.admin_views import assistant_view

    settings.OPENAI_API_KEY = "test-key"
    _permit_ticket_add(monkeypatch)

    assert (
        assistant_view(_staff_request({"model": "comment", "question": "Help?"})).status_code == 400
    )
    assert assistant_view(_staff_request({"model": "ticket", "question": " "})).status_code == 400
    assert (
        assistant_view(_staff_request({"model": "ticket", "question": "x" * 1001})).status_code
        == 400
    )


def test_endpoint_reports_missing_key(monkeypatch, settings):
    from tickets.admin_views import assistant_view

    settings.OPENAI_API_KEY = ""
    _permit_ticket_add(monkeypatch)
    response = assistant_view(_staff_request({"model": "ticket", "question": "Help?"}))

    assert response.status_code == 503
    assert "not configured" in json.loads(response.content)["error"]


def test_endpoint_limits_each_user_to_five_per_minute(monkeypatch, settings):
    from tickets.admin_views import assistant_view

    settings.OPENAI_API_KEY = "test-key"
    cache.clear()
    _permit_ticket_add(monkeypatch)
    provider = Mock(return_value="A safe answer")
    monkeypatch.setattr("tickets.admin_views.ask_form_question", provider)

    def request():
        return _staff_request({"model": "ticket", "question": "Help?"})

    assert [assistant_view(request()).status_code for _ in range(5)] == [200] * 5
    response = assistant_view(request())

    assert response.status_code == 429
    assert "limit" in json.loads(response.content)["error"]
    assert provider.call_count == 5


def test_endpoint_enforces_global_daily_limit(monkeypatch, settings):
    from tickets.admin_views import assistant_view

    settings.OPENAI_API_KEY = "test-key"
    cache.clear()
    _permit_ticket_add(monkeypatch)
    provider = Mock(return_value="A safe answer")
    monkeypatch.setattr("tickets.admin_views.ask_form_question", provider)
    data = {"model": "ticket", "question": "Help?"}

    statuses = [
        assistant_view(_staff_request(data, user_id=i // 5 + 1)).status_code for i in range(201)
    ]

    assert statuses == [200] * 200 + [429]
    assert provider.call_count == 200


def test_endpoint_reports_provider_unavailability(monkeypatch, settings):
    from tickets.admin_views import assistant_view
    from tickets.assistant import AssistantUnavailable

    settings.OPENAI_API_KEY = "test-key"
    cache.clear()
    _permit_ticket_add(monkeypatch)
    monkeypatch.setattr(
        "tickets.admin_views.ask_form_question",
        Mock(side_effect=AssistantUnavailable("Assistant unavailable: provider error.")),
    )

    response = assistant_view(_staff_request({"model": "ticket", "question": "Help?"}))

    assert response.status_code == 503
    assert json.loads(response.content)["error"] == "Assistant unavailable: provider error."


def test_registered_ticket_add_form_reaches_provider_with_field_definitions(monkeypatch, settings):
    from tickets.admin_views import assistant_view

    settings.OPENAI_API_KEY = "test-key"
    cache.clear()
    provider = Mock(return_value="Select a priority.")
    monkeypatch.setattr("tickets.admin_views.ask_form_question", provider)
    request = RequestFactory().post(
        "/admin/form-help/", {"model": "ticket", "question": "How do I set priority?"}
    )
    request.user = get_user_model()(username="admin", is_staff=True, is_superuser=True)
    request.user.pk = 10
    request._dont_enforce_csrf_checks = True

    response = assistant_view(request)

    assert response.status_code == 200
    assert json.loads(response.content) == {"answer": "Select a priority."}
    metadata = provider.call_args.args[1]
    assert {field["name"] for field in metadata["fields"]} >= {"subject", "priority"}
    assert metadata["inlines"][0]["name"] == "comment"


@pytest.mark.django_db
def test_viewer_can_ask_about_visible_ticket_without_sending_record_values(
    monkeypatch,
    settings,
):
    from tickets.admin_views import assistant_view
    from tickets.models import Customer, Ticket

    settings.OPENAI_API_KEY = "test-key"
    cache.clear()
    viewer = get_user_model().objects.create_user("viewer", is_staff=True)
    viewer.groups.add(Group.objects.get(name="Viewer"))
    customer = Customer.objects.create(name="Private customer", email="private@example.test")
    ticket = Ticket.objects.create(
        subject="Secret complaint", description="Sensitive ticket body", customer=customer
    )
    provider = Mock(return_value="The status describes the ticket's stage.")
    monkeypatch.setattr("tickets.admin_views.ask_form_question", provider)
    request = RequestFactory().post(
        "/admin/form-help/",
        {"model": "ticket", "object_id": str(ticket.pk), "question": "What is status?"},
    )
    request.user = viewer
    request._dont_enforce_csrf_checks = True

    response = assistant_view(request)

    assert response.status_code == 200
    metadata = provider.call_args.args[1]
    assert all(field["read_only"] for field in metadata["fields"])
    assert "Secret complaint" not in str(metadata)
    assert "Sensitive ticket body" not in str(metadata)
    assert "Private customer" not in str(metadata)
