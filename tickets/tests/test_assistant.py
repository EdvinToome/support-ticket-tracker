import json

import httpx
import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from openai import OpenAI

from tickets.models import Comment, Customer, Ticket


@pytest.mark.django_db
def test_assistant_requires_ticket_permission(client, django_user_model):
    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    client.force_login(staff)

    response = client.post(
        "/admin/assistant/",
        {"ticket_id": 1, "action": "summarize", "question": "Summarize this ticket."},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_assistant_grounds_both_actions_in_selected_ticket_without_writing_records(
    client, django_user_model, settings, monkeypatch
):
    settings.OPENAI_API_KEY = "test-only-key"
    cache.clear()
    agent = django_user_model.objects.create_user(username="agent", is_staff=True)
    agent.groups.add(Group.objects.get(name="Agent"))
    client.force_login(agent)
    customer = Customer.objects.create(name="Ada", email="private@example.test")
    ticket = Ticket.objects.create(
        subject="Duplicate invoice", description="Charged twice for one order.", customer=customer
    )
    Comment.objects.create(ticket=ticket, author=agent, body="Duplicate charge confirmed.")
    Ticket.objects.create(subject="Unrelated private issue", description="Other", customer=customer)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
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
                                "text": "A duplicate charge was confirmed.",
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
    for action in ("summarize", "draft_reply"):
        response = client.post(
            "/admin/assistant/",
            {
                "ticket_id": ticket.pk,
                "action": action,
                "question": "Keep it short.",
                "history": "[]",
            },
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "A duplicate charge was confirmed."

    for request in requests:
        context = request["input"][0]["content"]
        assert "Charged twice for one order." in context
        assert "Duplicate charge confirmed." in context
        assert "Unrelated private issue" not in context
        assert "private@example.test" not in context
        assert request["store"] is False
    assert requests[0]["instructions"] != requests[1]["instructions"]
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.OPEN
    assert list(ticket.comments.values_list("body", flat=True)) == ["Duplicate charge confirmed."]
