"""Permission-bound, rate-limited form help for Django admin."""

import logging
import time

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .assistant import AssistantUnavailable, ask_form_question, form_metadata
from .models import Customer, Ticket

logger = logging.getLogger(__name__)

MODELS = {"ticket": Ticket, "customer": Customer}


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _consume_limit(user_id):
    """Approximate cache counters shared across workers; get/set increments are not atomic."""
    now = int(time.time())
    minute_key = f"form-help:user:{user_id}:{now // 60}"
    day_key = f"form-help:global:{now // 86400}"
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
    model_key = request.POST.get("model")
    question = request.POST.get("question", "")
    object_id = request.POST.get("object_id")
    if model_key not in MODELS:
        return _error("This form is not supported by the assistant.", 400)
    if not question.strip() or len(question) > 1000:
        return _error("Enter a question of 1 to 1,000 characters.", 400)

    model_admin = admin.site._registry[MODELS[model_key]]
    obj = None
    if object_id:
        obj = model_admin.get_object(request, object_id)
        if obj is None:
            return _error("This form was not found.", 404)
        allowed = model_admin.has_view_or_change_permission(request, obj)
    else:
        allowed = model_admin.has_add_permission(request)
    if not allowed:
        return _error("You do not have access to this form.", 403)

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        logger.warning("form assistant missing API key")
        return _error("Assistant unavailable: API key is not configured.", 503)
    if not _consume_limit(request.user.pk):
        logger.info("form assistant local rate limit")
        return _error("Assistant unavailable: request limit reached. Try again later.", 429)

    metadata = form_metadata(model_admin, request, obj)
    try:
        answer = ask_form_question(model_key, metadata, question, api_key)
    except AssistantUnavailable as exc:
        return _error(str(exc), 503)
    return JsonResponse({"answer": answer})
