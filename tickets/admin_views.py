"""Permission-bound, rate-limited ticket assistance for Django admin."""

import logging
import time

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .assistant import AssistantUnavailable, ask_ticket_question
from .assistant_forms import TicketAssistantForm
from .models import Ticket

logger = logging.getLogger(__name__)


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _consume_limit(user_id):
    """Approximate cache counters shared across workers; get/set increments are not atomic."""
    now = int(time.time())
    minute_key = f"ticket-assistant:user:{user_id}:{now // 60}"
    day_key = f"ticket-assistant:global:{now // 86400}"
    user_count = cache.get(minute_key, 0)
    global_count = cache.get(day_key, 0)
    if user_count >= 5 or global_count >= 200:
        return False
    cache.set(minute_key, user_count + 1, timeout=60 - now % 60)
    cache.set(day_key, global_count + 1, timeout=86400 - now % 86400)
    return True


@admin.site.admin_view
@require_POST
def assistant_view(request):
    model_admin = admin.site._registry[Ticket]
    if not model_admin.has_view_permission(request):
        return _error("You do not have access to tickets.", 403)

    form = TicketAssistantForm(request.POST)
    if not form.is_valid():
        return _error(" ".join(error for errors in form.errors.values() for error in errors), 400)
    data = form.cleaned_data
    ticket = model_admin.get_object(request, data["ticket_id"])
    if ticket is None:
        return _error("This ticket was not found.", 404)
    if not model_admin.has_view_permission(request, ticket):
        return _error("You do not have access to this ticket.", 403)

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        logger.warning("ticket assistant missing API key")
        return _error("Assistant unavailable: API key is not configured.", 503)
    if not _consume_limit(request.user.pk):
        return _error("Assistant unavailable: request limit reached. Try again later.", 429)

    try:
        answer = ask_ticket_question(
            ticket, data["action"], data["question"], data["history"], api_key
        )
    except AssistantUnavailable as exc:
        return _error(str(exc), 503)
    return JsonResponse({"answer": answer})
