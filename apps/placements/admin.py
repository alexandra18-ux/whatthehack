from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .moderation import ModerationForm, prepare_decision, record_decision
from .models import Placement, can_moderate

admin.site.site_header = "Murrralium · управление"


class ModerationStatusFilter(admin.SimpleListFilter):
    title = "Статус"
    parameter_name = "moderation_status"

    def lookups(self, request, model_admin):
        return [
            (Placement.Status.APPROVED, Placement.Status.APPROVED.label),
            (Placement.Status.REJECTED, Placement.Status.REJECTED.label),
            (Placement.Status.REVISION, Placement.Status.REVISION.label),
            ("all", "Все заявки"),
        ]

    def choices(self, changelist):
        pending, *other_choices = super().choices(changelist)
        yield {**pending, "display": Placement.Status.PENDING.label}
        yield from other_choices

    def queryset(self, request, queryset):
        status = self.value()
        if status == "all":
            return queryset
        if status not in Placement.Status.values:
            status = Placement.Status.PENDING
        return queryset.filter(status=status)


@admin.register(Placement)
class PlacementAdmin(admin.ModelAdmin):
    form = ModerationForm
    list_display = ["title", "building", "author", "status", "created_at"]
    list_filter = [ModerationStatusFilter]
    search_fields = ["title", "building__address", "author__username"]
    list_select_related = ["building", "author"]
    fields = [
        "title", "description", "building", "author", "materials",
        "status", "rejection_reason", "revision_notes", "created_at", "published_at",
    ]
    readonly_fields = [
        "title", "description", "building", "author", "materials", "created_at", "published_at",
    ]

    def get_ordering(self, request):
        status = request.GET.get(ModerationStatusFilter.parameter_name)
        if status in {None, Placement.Status.PENDING}:
            return ("created_at", "pk")
        return super().get_ordering(request)

    @admin.display(description="Изображения")
    def materials(self, project):
        result_url = reverse("project_image", args=[project.pk, "result"])
        if project.is_existing_graffiti:
            return format_html('<a href="{}" target="_blank" rel="noopener">Фото граффити</a>', result_url)
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Фасад</a> · '
            '<a href="{}" target="_blank" rel="noopener">Эскиз</a> · '
            '<a href="{}" target="_blank" rel="noopener">Результат</a>',
            reverse("asset", args=["facade", project.facade_photo_id]),
            reverse("asset", args=["design", project.mural_design_id]),
            result_url,
        )

    def has_module_permission(self, request):
        return can_moderate(request.user)

    def has_view_permission(self, request, obj=None):
        return can_moderate(request.user)

    def has_change_permission(self, request, obj=None):
        return can_moderate(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        previous = Placement.objects.select_for_update().get(pk=obj.pk)
        prepare_decision(obj)
        super().save_model(request, obj, form, change)
        if any(getattr(obj, field) != getattr(previous, field) for field in ModerationForm.Meta.fields):
            record_decision(obj, request.user)
