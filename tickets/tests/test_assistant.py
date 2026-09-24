import json

import httpx
import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from openai import OpenAI

from tickets.models import Agent, Comment, Customer, Ticket


@pytest.mark.django_db
def test_form_help_requires_model_permission(client, django_user_model):
    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    client.force_login(staff)
    response = client.post(
        "/admin/form-help/", {"model": "ticket", "question": "What does status mean?"}
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_form_help_uses_visible_definitions_without_record_values(
    client, django_user_model, settings, monkeypatch
):
    settings.OPENAI_API_KEY = "test-only-key"
    cache.clear()
    agent = django_user_model.objects.create_user(
        username="agent", first_name="Private agent name", is_staff=True
    )
    agent.groups.add(Group.objects.get(name="Agent"))
    profile = Agent.objects.create(user=agent)
    customer = Customer.objects.create(name="Private customer", email="private@example.test")
    ticket = Ticket.objects.create(
        subject="Private ticket subject", description="Private ticket details", customer=customer
    )
    comment = Comment.objects.create(
        ticket=ticket,
        author=agent,
        body="Private comment",
        attachment="attachments/private.pdf",
    )
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
                                "text": "Save a comment before resolving.",
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
    client.force_login(agent)
    contexts = [
        {"model": "ticket", "object_id": ticket.pk},
        {"model": "customer", "object_id": customer.pk},
        {"model": "agent", "object_id": profile.pk},
        {"model": "comment", "object_id": comment.pk},
        {"model": "ticket"},
    ]
    for context in contexts:
        response = client.post(
            "/admin/form-help/", {**context, "question": "How do I fill this out?"}
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "Save a comment before resolving."

    viewer = django_user_model.objects.create_user(username="viewer", is_staff=True)
    viewer.groups.add(Group.objects.get(name="Viewer"))
    client.force_login(viewer)
    response = client.post(
        "/admin/form-help/",
        {"model": "ticket", "object_id": ticket.pk, "question": "Can I change the status?"},
    )
    assert response.status_code == 200

    definitions = [json.loads(request["input"][0]["content"]) for request in requests]
    ticket_fields = {field["name"]: field for field in definitions[0]["fields"]}
    assert ticket_fields["subject"]["required"] is True
    assert ticket_fields["subject"]["max_length"] == 200
    assert ticket_fields["status"]["read_only"] is False
    assert "Closed tickets cannot reopen" in ticket_fields["status"]["help_text"]
    assert [value for value, label in ticket_fields["status"]["choices"]] == [
        "open",
        "in_progress",
        "resolved",
        "closed",
    ]
    attachment = next(
        field for field in definitions[0]["inlines"][0]["fields"] if field["name"] == "attachment"
    )
    assert "3 MiB" in attachment["help_text"]
    assert definitions[1]["mode"] == "view"
    assert definitions[2]["mode"] == "view"
    assert definitions[3]["mode"] == "change"
    new_status = next(field for field in definitions[4]["fields"] if field["name"] == "status")
    assert new_status["read_only"] is True
    assert definitions[5]["mode"] == "view"
    assert all(field["read_only"] for field in definitions[5]["fields"])

    for request in requests:
        prompt = json.dumps(request["input"])
        for private_value in (
            "Private agent name",
            "Private customer",
            "private@example.test",
            "Private ticket subject",
            "Private ticket details",
            "Private comment",
            "attachments/private.pdf",
        ):
            assert private_value not in prompt
        assert isinstance(request["input"][0]["content"], str)
        assert request["store"] is False
