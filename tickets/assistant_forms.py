"""Validate the requested form context and chat messages."""

from django import forms

from .models import Agent, Comment, Customer, Ticket

FORM_MODELS = {model._meta.model_name: model for model in (Ticket, Customer, Agent, Comment)}


class FormHelpForm(forms.Form):
    model = forms.ChoiceField(
        choices=[(name, model._meta.verbose_name) for name, model in FORM_MODELS.items()]
    )
    object_id = forms.IntegerField(min_value=1, required=False)
    question = forms.CharField(max_length=1000)
    history = forms.JSONField(required=False)
    page = forms.JSONField(required=False)

    def clean_page(self):
        page = self.cleaned_data["page"]
        if page is None:
            return None
        if not isinstance(page, dict) or set(page) != {"values", "errors", "active_field"}:
            raise forms.ValidationError("Invalid form snapshot.")
        if not isinstance(page["values"], dict) or not all(
            isinstance(name, str)
            and isinstance(values, list)
            and all(isinstance(value, str) for value in values)
            for name, values in page["values"].items()
        ):
            raise forms.ValidationError("Invalid form values.")
        if (
            not isinstance(page["errors"], list)
            or not all(isinstance(error, str) for error in page["errors"])
            or not isinstance(page["active_field"], str)
        ):
            raise forms.ValidationError("Invalid form errors or focused field.")
        return page

    def clean_history(self):
        history = self.cleaned_data["history"]
        if history is None:
            return []
        if not isinstance(history, list) or len(history) > 6:
            raise forms.ValidationError("Send at most six previous messages.")
        for message in history:
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")
                or not isinstance(message["content"], str)
                or not 1 <= len(message["content"]) <= 4000
            ):
                raise forms.ValidationError("Invalid conversation message.")
        return history
