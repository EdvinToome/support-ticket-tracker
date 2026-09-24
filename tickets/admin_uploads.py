"""Return validation errors without replacing a form that holds selected files."""

from django.contrib import admin
from django.core.exceptions import NON_FIELD_ERRORS
from django.http import JsonResponse


def _form_errors(form, prefix=""):
    errors = []
    for name, messages in form.errors.items():
        field = None if name == NON_FIELD_ERRORS else form[name]
        if field:
            label = f"{prefix}: {field.label}" if prefix else str(field.label)
        else:
            label = prefix or "Ticket"
        errors.append(
            {
                "field": field.id_for_label if field else None,
                "label": label,
                "messages": [str(message) for message in messages],
            }
        )
    return errors


class UploadPreservingAdmin(admin.ModelAdmin):
    class Media:
        js = ("tickets/preserve_uploads.js",)

    def render_change_form(self, request, context, *args, **kwargs):
        if request.method == "POST" and request.headers.get("Accept") == "application/json":
            errors = _form_errors(context["adminform"].form)
            for inline in context["inline_admin_formsets"]:
                label = str(inline.opts.verbose_name).capitalize()
                if messages := inline.formset.non_form_errors():
                    errors.append({"field": None, "label": label, "messages": list(messages)})
                for number, form in enumerate(inline.formset.forms, start=1):
                    errors.extend(_form_errors(form, f"{label} {number}"))
            return JsonResponse({"errors": errors}, status=400)
        return super().render_change_form(request, context, *args, **kwargs)
