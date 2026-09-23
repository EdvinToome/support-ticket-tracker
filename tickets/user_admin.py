from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

admin.site.unregister(User)


@admin.register(User)
class RestrictedUserAdmin(UserAdmin):
    """Group admins manage ordinary users without gaining superuser privileges."""

    readonly_fields = ("last_login", "date_joined")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset if request.user.is_superuser else queryset.filter(is_superuser=False)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets
        return [
            (
                title,
                {
                    **options,
                    "fields": tuple(
                        name
                        for name in options["fields"]
                        if name not in {"is_superuser", "user_permissions"}
                    ),
                },
            )
            for title, options in fieldsets
        ]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        field = super().formfield_for_manytomany(db_field, request, **kwargs)
        if db_field.name == "groups" and not request.user.is_superuser:
            field.queryset = field.queryset.filter(name__in=["Admin", "Agent", "Viewer"])
        return field
