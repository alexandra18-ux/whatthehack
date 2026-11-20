from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Placement, can_moderate

admin.site.site_header = "Muralium · управление"


class ModerationForm(forms.ModelForm):
    class Meta:
        model = Placement
        fields = ["status", "rejection_reason"]

    def clean(self):
        data = super().clean()
        if data.get("status") == Placement.Status.REJECTED and not data.get("rejection_reason"):
            self.add_error("rejection_reason", "Укажите причину отклонения.")
        return data


@admin.register(Placement)
class PlacementAdmin(admin.ModelAdmin):
    form = ModerationForm
    list_display = ["title", "building", "author", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "building__address", "author__username"]
    list_select_related = ["building", "author"]
    fields = [
        "title", "description", "building", "author", "materials",
        "status", "rejection_reason", "created_at", "published_at",
    ]
    readonly_fields = [
        "title", "description", "building", "author", "materials", "created_at", "published_at",
    ]

    @admin.display(description="Изображения")
    def materials(self, project):
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Фасад</a> · '
            '<a href="{}" target="_blank" rel="noopener">Эскиз</a> · '
            '<a href="{}" target="_blank" rel="noopener">Результат</a>',
            reverse("asset", args=["facade", project.facade_photo_id]),
            reverse("asset", args=["design", project.mural_design_id]),
            reverse("project_image", args=[project.pk, "result"]),
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
        if obj.status == Placement.Status.APPROVED:
            obj.published_at = obj.published_at or timezone.now()
        else:
            obj.published_at = None
        if obj.status != Placement.Status.REJECTED:
            obj.rejection_reason = ""
        super().save_model(request, obj, form, change)
