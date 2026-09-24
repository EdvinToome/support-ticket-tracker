import json

import httpx
import pytest
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from openai import OpenAI

from tickets.models import Agent, Comment, Customer, Ticket


@pytest.fixture
def record_data(django_user_model):
    agent = django_user_model.objects.create_user(username="agent", first_name="Ada", is_staff=True)
    agent.groups.add(Group.objects.get(name="Agent"))
    profile = Agent.objects.create(user=agent)
    customer = Customer.objects.create(name="Northwind", email="contact@northwind.test")
    ticket = Ticket.objects.create(
        subject="Invoice discrepancy",
        description="Invoice total differs from the order.",
        customer=customer,
    )
    ticket.assignees.add(profile)
    comment = Comment.objects.create(
        ticket=ticket,
        author=agent,
        body="Checked invoice: setup fee is disputed.",
        attachment="attachments/invoice.pdf",
    )
    other_ticket = Ticket.objects.create(
        subject="Unrelated login problem",
        description="Do not include this other ticket.",
        customer=customer,
    )
    Comment.objects.create(ticket=other_ticket, author=agent, body="Unrelated private note")
    return agent, profile, customer, ticket, comment


@pytest.mark.django_db
def test_assistant_enforces_access_to_records_relations_and_page_fields(
    client, django_user_model, settings, monkeypatch, record_data
):
    settings.OPENAI_API_KEY = "test-only-key"
    cache.clear()
    agent, profile, customer, ticket, comment = record_data
    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    client.force_login(staff)
    data = {"model": "ticket", "object_id": ticket.pk, "question": "Summarize this record."}
    assert client.post("/admin/form-help/", data).status_code == 403

    staff.user_permissions.add(Permission.objects.get(codename="view_ticket"))
    captured = []
    monkeypatch.setattr(
        "tickets.admin_views.ask_form_question",
        lambda metadata, *args: captured.append(metadata) or "Summary",
    )
    assert client.post("/admin/form-help/", data).status_code == 200
    context = captured[0]
    assert context["record"]["subject"] == ticket.subject
    assert all(not relation["available"] for relation in context["related"].values())
    encoded = json.dumps(context)
    assert customer.email not in encoded
    assert comment.body not in encoded
    assert "Unrelated login problem" not in encoded

    client.force_login(agent)
    forbidden_page = {"values": {"password": ["never-send-this"]}, "errors": [], "active_field": ""}
    assert (
        client.post("/admin/form-help/", {**data, "page": json.dumps(forbidden_page)}).status_code
        == 400
    )
    assert len(captured) == 1
    other_comment = Comment.objects.exclude(ticket=ticket).get()
    forged_inline = {
        "values": {
            "comments-0-id": [str(other_comment.pk)],
            "comments-0-body": ["Edited note"],
        },
        "errors": [],
        "active_field": "comments-0-body",
    }
    assert (
        client.post("/admin/form-help/", {**data, "page": json.dumps(forged_inline)}).status_code
        == 400
    )
    assert len(captured) == 1


@pytest.mark.django_db
def test_assistant_combines_form_definitions_saved_relations_and_unsaved_inputs(
    client, django_user_model, settings, monkeypatch, record_data
):
    settings.OPENAI_API_KEY = "test-only-key"
    cache.clear()
    agent, profile, customer, ticket, comment = record_data
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "model": "gpt-6-luna",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "The description is required.",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    monkeypatch.setattr(
        "tickets.assistant.OpenAI",
        lambda **kwargs: OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        ),
    )
    page = {
        "values": {
            "subject": ["Unsaved subject"],
            "description": [""],
            "comments-0-body": ["Checked invoice: setup fee is disputed."],
            "comments-0-id": [str(comment.pk)],
        },
        "errors": ["Description: This field is required."],
        "active_field": "description",
    }
    client.force_login(agent)
    contexts = [
        {"model": "ticket", "object_id": ticket.pk, "page": json.dumps(page)},
        {"model": "customer", "object_id": customer.pk},
        {"model": "agent", "object_id": profile.pk},
        {"model": "ticket"},
    ]
    for context in contexts:
        response = client.post(
            "/admin/form-help/", {**context, "question": "Help me understand this form and record."}
        )
        assert response.status_code == 200, response.content
        assert response.json()["answer"] == "The description is required."

    viewer = django_user_model.objects.create_user(username="viewer", is_staff=True)
    viewer.groups.add(Group.objects.get(name="Viewer"))
    client.force_login(viewer)
    assert (
        client.post(
            "/admin/form-help/",
            {"model": "ticket", "object_id": ticket.pk, "question": "Can I change the status?"},
        ).status_code
        == 200
    )

    definitions = [json.loads(request["input"][0]["content"]) for request in requests]
    current = definitions[0]
    fields = {field["name"]: field for field in current["fields"]}
    assert fields["subject"]["required"] is True
    assert fields["subject"]["max_length"] == 200
    assert "Closed tickets cannot reopen" in fields["status"]["help_text"]
    assert [value for value, label in fields["status"]["choices"]] == [
        "open",
        "in_progress",
        "resolved",
        "closed",
    ]
    assert current["record"]["subject"] == "Invoice discrepancy"
    assert current["current_form"] == page
    assert current["unsaved_fields"] == ["description", "subject"]
    assert current["related"]["customer"]["records"][0]["email"] == customer.email
    assert current["related"]["assignees"]["records"][0]["name"] == "Ada"
    assert current["related"]["comments"]["records"][0]["body"] == comment.body
    assert current["related"]["comments"]["records"][0]["attachment"] == "invoice.pdf"
    assert "Unrelated login problem" not in json.dumps(current)
    assert len(definitions[1]["related"]["tickets"]["records"]) == 2
    assert len(definitions[2]["related"]["tickets"]["records"]) == 1
    assert definitions[1]["mode"] == definitions[2]["mode"] == "view"
    assert definitions[3]["record"] is None
    assert definitions[3]["related"] == {}
    new_status = next(field for field in definitions[3]["fields"] if field["name"] == "status")
    assert new_status["read_only"] is True
    assert definitions[4]["mode"] == "view"
    assert all(field["read_only"] for field in definitions[4]["fields"])
    for request in requests:
        prompt = json.dumps(request["input"])
        assert "attachments/invoice.pdf" not in prompt
        assert "input_file" not in prompt and "input_image" not in prompt
        assert agent.password not in prompt
        assert request["store"] is False
    ticket.refresh_from_db()
    comment.refresh_from_db()
    assert ticket.subject == "Invoice discrepancy"
    assert comment.body == "Checked invoice: setup fee is disputed."
