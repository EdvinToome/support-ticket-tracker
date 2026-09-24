"""Accept a browser snapshot only for fields exposed by this admin form."""

import re

from django.core.exceptions import ValidationError
from django.http import QueryDict


def _input_names(fields):
    names = set()
    for field in fields:
        if not field["read_only"]:
            names.add(field["name"])
            if field["type"] == "FileField":
                names.add(f"{field['name']}-clear")
    return names


def current_form_context(metadata, page):
    if page is None:
        return None
    names = _input_names(metadata["fields"])
    inline_patterns = []
    for inline in metadata["inlines"]:
        fields = _input_names(inline["fields"])
        if fields:
            fields.add("id")
        if inline["can_delete"]:
            fields.add("DELETE")
        if fields:
            choices = "|".join(re.escape(name) for name in fields)
            inline_patterns.append(rf"{re.escape(inline['prefix'])}-\d+-({choices})")

    requested = set(page["values"])
    if page["active_field"]:
        requested.add(page["active_field"])
    for name in requested:
        if name not in names and not any(
            re.fullmatch(pattern, name) for pattern in inline_patterns
        ):
            raise ValidationError("The page contains a field that is not editable in this form.")
    return page


def changed_fields(model_admin, request, obj, page):
    if page is None:
        return []
    data = QueryDict(mutable=True)
    for name, values in page["values"].items():
        data.setlist(name, values)

    def changed(form):
        return {
            form.add_prefix(name)
            for name in form.changed_data
            if form.add_prefix(name) in page["values"]
        }

    form_class = model_admin.get_form(request, obj, change=obj is not None)
    names = changed(form_class(data=data, instance=obj))
    for inline in model_admin.get_inline_instances(request, obj):
        formset = inline.get_formset(request, obj)
        prefix = formset.get_default_prefix()
        rows = {
            match.group(1)
            for name in page["values"]
            if (match := re.fullmatch(rf"({re.escape(prefix)}-\d+)-.+", name))
        }
        if not rows:
            continue
        instances = (
            {
                str(record.pk): record
                for record in inline.get_queryset(request).filter(**{formset.fk.name: obj})
            }
            if obj is not None
            else {}
        )
        for row in rows:
            record_id = data.get(f"{row}-id")
            if record_id and record_id not in instances:
                raise ValidationError("An inline row does not belong to this record.")
            names.update(
                changed(formset.form(data=data, instance=instances.get(record_id), prefix=row))
            )

    # Files are represented by names, never uploaded to this endpoint. DELETE is a formset control.
    names.update(
        name
        for name, values in page["values"].items()
        if values and (name.endswith("attachment") or name.endswith("-DELETE"))
    )
    return sorted(names)
