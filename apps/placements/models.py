from django.conf import settings
from django.db import models


class Placement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "На модерации"
        APPROVED = "approved", "Опубликован"
        REJECTED = "rejected", "Отклонён"

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    building = models.ForeignKey("buildings.Building", on_delete=models.PROTECT)
    facade_photo = models.ForeignKey("buildings.FacadePhoto", on_delete=models.PROTECT)
    mural_design = models.ForeignKey("murals.MuralDesign", on_delete=models.PROTECT)
    title = models.CharField("Название", max_length=200)
    description = models.TextField("Описание", max_length=2000)
    corners = models.JSONField()
    result_image = models.ImageField(upload_to="results/")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField("Причина отклонения", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        permissions = [("moderate_placement", "Может модерировать заявки")]
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title


def published_placements():
    return Placement.objects.filter(
        status=Placement.Status.APPROVED, published_at__isnull=False,
    ).select_related("building", "author").order_by("-published_at", "-pk")


def can_moderate(user):
    return user.is_staff and user.has_perm("placements.moderate_placement")
