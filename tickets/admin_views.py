"""Permission-bound, rate-limited help for Django admin forms."""

import logging
import time

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .assistant import AssistantUnavailable, ask_form_question
from .assistant_context import form_metadata
from .assistant_forms import FORM_MODELS, FormHelpForm
from .assistant_page import changed_fields, current_form_context
from .assistant_records import object_context

logger = logging.getLogger(__name__)


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
    form = FormHelpForm(request.POST)
    if not form.is_valid():
        return _error(" ".join(error for errors in form.errors.values() for error in errors), 400)
    data = form.cleaned_data
    model_admin = admin.site._registry[FORM_MODELS[data["model"]]]
    allowed = model_admin.has_view_or_change_permission(request)
    if not data["object_id"]:
        allowed = allowed or model_admin.has_add_permission(request)
    if not allowed:
        return _error("You do not have access to this form.", 403)

    obj = None
    if data["object_id"]:
        obj = model_admin.get_object(request, data["object_id"])
        if obj is None:
            return _error("This record was not found.", 404)
        if not model_admin.has_view_or_change_permission(request, obj):
            return _error("You do not have access to this form.", 403)

    metadata = form_metadata(model_admin, request, obj)
    try:
        metadata["current_form"] = current_form_context(metadata, data["page"])
        metadata["unsaved_fields"] = changed_fields(model_admin, request, obj, data["page"])
    except ValidationError as exc:
        return _error(" ".join(exc.messages), 400)

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        logger.warning("form assistant missing API key")
        return _error("Assistant unavailable: API key is not configured.", 503)
    if not _consume_limit(request.user.pk):
        return _error("Assistant unavailable: request limit reached. Try again later.", 429)

    metadata.update(object_context(request, obj))
    try:
        answer = ask_form_question(metadata, data["question"], data["history"], api_key)
    except AssistantUnavailable as exc:
        return _error(str(exc), 503)
    return JsonResponse({"answer": answer})
