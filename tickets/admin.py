from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Case, Count, Max, TextField, When
from django.db.models.functions import Coalesce

from .actions import resolve_tickets
from .admin_uploads import UploadPreservingAdmin
from .models import Agent, Comment, Customer, Ticket

admin.site.site_header = "Support ticket tracker"
admin.site.site_title = "Support tickets"
admin.site.index_title = "Support desk"


class AssignmentFilter(admin.SimpleListFilter):
    title = "assignment"
    parameter_name = "assignment"

    def lookups(self, request, model_admin):
        return [("mine", "Assigned to me"), ("unassigned", "Unassigned")]

    def queryset(self, request, queryset):
        if self.value() == "mine":
            return queryset.filter(assignees__user=request.user)
        if self.value() == "unassigned":
            return queryset.filter(assignees__isnull=True)
        return queryset


class CommentInline(admin.TabularInline):
    model = Comment
    fields = ("body", "attachment", "author", "created_at")
    readonly_fields = ("author", "created_at")
    extra = 1
    formfield_overrides = {TextField: {"widget": forms.Textarea(attrs={"rows": 3, "cols": 32})}}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("author")


@admin.register(Ticket)
class TicketAdmin(UploadPreservingAdmin):
    list_display = (
        "id",
        "subject",
        "customer",
        "assigned_agents",
        "status",
        "priority",
        "comment_count",
        "last_activity",
        "created_at",
    )
    list_display_links = ("id", "subject")
    list_filter = ("status", "priority", AssignmentFilter, "assignees")
    search_fields = ("id__exact", "subject", "customer__name", "customer__email")
    date_hierarchy = "created_at"
    ordering = (
        Case(
            When(status=Ticket.Status.IN_PROGRESS, then=0),
            When(status=Ticket.Status.OPEN, then=1),
            When(status=Ticket.Status.RESOLVED, then=2),
            When(status=Ticket.Status.CLOSED, then=3),
        ),
        "-priority",
        "created_at",
    )
    list_select_related = ("customer",)
    list_per_page = 50
    autocomplete_fields = ("customer", "assignees")
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "subject",
        "description",
        "customer",
        "assignees",
        "status",
        "priority",
        "created_at",
        "updated_at",
    )
    inlines = (CommentInline,)
    actions = (resolve_tickets,)

    def get_search_results(self, request, queryset, search_term):
        if search_term.isdecimal():
            return queryset.filter(pk=search_term), False
        return super().get_search_results(request, queryset, search_term)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("assignees")
            .annotate(
                comment_total=Count("comments", distinct=True),
                latest_activity=Coalesce(Max("comments__created_at"), "updated_at"),
            )
        )

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == Ticket.Status.CLOSED:
            return self.fields
        # New tickets always start open.
        return self.readonly_fields if obj else (*self.readonly_fields, "status")

    @admin.display(description="Assigned agents")
    def assigned_agents(self, obj):
        return ", ".join(str(agent) for agent in obj.assignees.all()) or "Unassigned"

    @admin.display(description="Comments", ordering="comment_total")
    def comment_count(self, obj):
        return obj.comment_total

    @admin.display(description="Last activity", ordering="latest_activity")
    def last_activity(self, obj):
        return obj.latest_activity

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if not obj.pk:
                obj.author = request.user
            obj.save()
        formset.save_m2m()


class CustomerTicketInline(admin.TabularInline):
    model = Ticket
    fields = ("subject", "status", "priority", "created_at")
    readonly_fields = fields
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "company", "created_at")
    search_fields = ("name", "email", "company")
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)
    inlines = (CustomerTicketInline,)
    ordering = ("name",)

    def get_inlines(self, request, obj=None):
        return self.inlines if obj else ()


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "user__is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    list_filter = ("user__is_active",)
    ordering = ("user__first_name", "user__last_name", "user__username")


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
        hidden = {"is_superuser", "user_permissions"}
        visible_fieldsets = []
        for title, options in fieldsets:
            visible_fields = [name for name in options["fields"] if name not in hidden]
            visible_fieldsets.append((title, {**options, "fields": visible_fields}))
        return visible_fieldsets
