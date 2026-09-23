from django import forms
from django.contrib import admin
from django.db.models import Count, Max, TextField
from django.db.models.functions import Coalesce

from .actions import resolve_tickets
from .models import Agent, Comment, Customer, Ticket
from .user_admin import RestrictedUserAdmin  # noqa: F401

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


class FormHelpAdmin(admin.ModelAdmin):
    change_form_template = "admin/tickets/assistant_change_form.html"

    def render_change_form(self, request, context, *args, **kwargs):
        context["assistant_model"] = self.model._meta.model_name
        return super().render_change_form(request, context, *args, **kwargs)


@admin.register(Ticket)
class TicketAdmin(FormHelpAdmin):
    list_display = (
        "subject",
        "customer",
        "assigned_agents",
        "status",
        "priority",
        "comment_count",
        "last_activity",
        "created_at",
    )
    list_filter = ("status", "priority", AssignmentFilter, "assignees")
    search_fields = ("subject", "customer__name", "customer__email")
    date_hierarchy = "created_at"
    ordering = ("-priority", "created_at")
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

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("assignees__user")
            .annotate(
                comment_total=Count("comments", distinct=True),
                latest_activity=Coalesce(Max("comments__created_at"), "updated_at"),
            )
        )

    def get_readonly_fields(self, request, obj=None):
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

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "assignees":
            kwargs["queryset"] = Agent.objects.filter(
                user__is_active=True,
                user__groups__name__in=["Agent", "Admin"],
            ).distinct()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

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
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(FormHelpAdmin):
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
    list_display = ("user", "active")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    list_select_related = ("user",)
    list_filter = ("user__is_active",)

    @admin.display(boolean=True)
    def active(self, obj):
        return obj.user.is_active


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "created_at")
    list_select_related = ("ticket", "author")
    search_fields = ("body", "ticket__subject")
    list_filter = ("created_at",)
    autocomplete_fields = ("ticket",)
    readonly_fields = ("author", "created_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.author = request.user
        super().save_model(request, obj, form, change)
