"""Ground admin form help in field definitions, never in saved field values."""

import json
import logging

import openai
from django import forms
from django.conf import settings
from django.contrib.admin.utils import flatten_fieldsets
from openai import OpenAI

logger = logging.getLogger(__name__)


class AssistantUnavailable(Exception):
    """A safe, user-facing provider failure category."""


def _choices(field):
    if isinstance(field, (forms.ModelChoiceField, forms.ModelMultipleChoiceField)):
        return []
    if not isinstance(field, forms.ChoiceField):
        return []
    return [(value, str(label)) for value, label in field.choices]


def _editable_field(name, field, *, read_only=False):
    return {
        "name": name,
        "type": type(field).__name__,
        "required": field.required,
        "choices": _choices(field),
        "help_text": str(field.help_text),
        "read_only": read_only,
    }


def _readonly_field(name, model):
    field = model._meta.get_field(name)
    choices = []
    if field.choices:
        choices = [(value, str(label)) for value, label in field.choices]
    return {
        "name": name,
        "type": type(field).__name__,
        "required": not field.blank,
        "choices": choices,
        "help_text": str(field.help_text),
        "read_only": True,
    }


def form_metadata(model_admin, request, obj=None):
    """Describe only fields displayed by this user's admin change/add form."""
    form_class = model_admin.get_form(request, obj, change=obj is not None)
    names = flatten_fieldsets(model_admin.get_fieldsets(request, obj))
    view_only = obj is not None and not model_admin.has_change_permission(request, obj)
    fields = []
    for name in names:
        if name in form_class.base_fields:
            fields.append(_editable_field(name, form_class.base_fields[name], read_only=view_only))
        else:
            fields.append(_readonly_field(name, model_admin.model))

    inlines = []
    for inline in model_admin.get_inline_instances(request, obj):
        formset = inline.get_formset(request, obj)
        inline_view_only = obj is not None and not inline.has_change_permission(request, obj)
        inline_fields = []
        for name in inline.get_fields(request, obj):
            if name in formset.form.base_fields:
                inline_fields.append(
                    _editable_field(
                        name, formset.form.base_fields[name], read_only=inline_view_only
                    )
                )
            else:
                inline_fields.append(_readonly_field(name, inline.model))
        inlines.append({"name": inline.model._meta.verbose_name, "fields": inline_fields})
    return {"fields": fields, "inlines": inlines}


def ask_form_question(model_name, metadata, question, api_key):
    instructions = (
        "Answer concisely in plain text without Markdown. "
        "Answer the user's question about this Django admin form. "
        "Use only the field definitions. Do not assume any saved record values or offer to "
        "change records. If the definitions do not answer the question, say so clearly."
    )
    prompt = (
        f"Form: {model_name}\n"
        f"Field definitions: {json.dumps(metadata, ensure_ascii=False)}\n"
        f"Question: {question}"
    )
    try:
        with OpenAI(api_key=api_key, timeout=10.0, max_retries=0) as client:
            response = client.responses.create(
                model=settings.OPENAI_MODEL,
                reasoning={"effort": "none"},
                store=False,
                max_output_tokens=500,
                instructions=instructions,
                input=prompt,
            )
    except openai.APITimeoutError as exc:
        logger.warning("form assistant timeout")
        raise AssistantUnavailable("Assistant unavailable: provider timeout.") from exc
    except openai.RateLimitError as exc:
        logger.warning("form assistant provider quota")
        raise AssistantUnavailable("Assistant unavailable: provider quota reached.") from exc
    except openai.APIError as exc:
        logger.warning("form assistant provider error: %s", type(exc).__name__)
        raise AssistantUnavailable("Assistant unavailable: provider error.") from exc

    if response.status != "completed" or not response.output_text.strip():
        logger.warning("form assistant unusable response: %s", response.status)
        raise AssistantUnavailable("Assistant unavailable: no complete answer was returned.")
    return response.output_text
