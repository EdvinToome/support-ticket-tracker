"""Describe visible admin fields without reading record values or relationship choices."""

from django import forms
from django.contrib.admin.utils import flatten_fieldsets


def _editable_field(name, field, view_only):
    read_only = view_only or field.disabled
    choices = []
    if isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
        choices = [(value, str(label)) for value, label in field.choices]
    return {
        "name": name,
        "label": str(field.label),
        "type": type(field).__name__,
        "required": field.required and not read_only,
        "read_only": read_only,
        "max_length": getattr(field, "max_length", None),
        "choices": choices,
        "help_text": str(field.help_text),
    }


def _readonly_field(name, model):
    field = model._meta.get_field(name)
    return {
        "name": name,
        "label": str(field.verbose_name),
        "type": type(field).__name__,
        "required": False,
        "read_only": True,
        "max_length": field.max_length,
        "choices": [(value, str(label)) for value, label in field.choices] if field.choices else [],
        "help_text": str(field.help_text),
    }


def _describe(names, form_class, model, view_only):
    # Admin read-only fields are excluded from the ModelForm.
    return [
        _editable_field(name, form_class.base_fields[name], view_only)
        if name in form_class.base_fields
        else _readonly_field(name, model)
        for name in names
    ]


def form_metadata(model_admin, request, obj=None):
    can_edit = (
        model_admin.has_add_permission(request)
        if obj is None
        else model_admin.has_change_permission(request, obj)
    )
    mode = "add" if obj is None else "change"
    fields = _describe(
        flatten_fieldsets(model_admin.get_fieldsets(request, obj)),
        model_admin.get_form(request, obj, change=obj is not None),
        model_admin.model,
        view_only=not can_edit,
    )
    inlines = []
    for inline in model_admin.get_inline_instances(request, obj):
        can_edit_inline = (
            inline.has_add_permission(request, obj)
            if obj is None
            else inline.has_change_permission(request, obj)
        )
        formset = inline.get_formset(request, obj)
        inline_fields = _describe(
            inline.get_fields(request, obj),
            formset.form,
            inline.model,
            view_only=not can_edit_inline,
        )
        inlines.append(
            {
                "name": str(inline.model._meta.verbose_name),
                "prefix": formset.get_default_prefix(),
                "can_delete": inline.can_delete and inline.has_delete_permission(request, obj),
                "fields": inline_fields,
            }
        )
    return {
        "model": str(model_admin.model._meta.verbose_name),
        "mode": mode if can_edit else "view",
        "fields": fields,
        "inlines": inlines,
    }
