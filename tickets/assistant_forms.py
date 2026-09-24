"""Validate the chat request before reading ticket data or calling the provider."""

from django import forms


class TicketAssistantForm(forms.Form):
    ticket_id = forms.IntegerField(min_value=1)
    action = forms.ChoiceField(choices=[("summarize", "Summary"), ("draft_reply", "Reply draft")])
    question = forms.CharField(max_length=1000)
    history = forms.JSONField(required=False)

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
