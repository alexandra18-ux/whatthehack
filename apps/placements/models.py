from django.conf import settings
from django.db import models
from django.db.models import Avg, Count, OuterRef, Subquery


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


class Rating(models.Model):
    placement = models.ForeignKey(Placement, on_delete=models.CASCADE, related_name="ratings")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["placement", "author"], name="one_rating_per_author"),
            models.CheckConstraint(condition=models.Q(score__range=(1, 5)), name="rating_score_1_to_5"),
        ]


class Comment(models.Model):
    placement = models.ForeignKey(Placement, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.CharField(max_length=800)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["placement", "-created_at", "-id"])]


class CommentLike(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="likes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["comment", "author"], name="one_like_per_comment_author"),
        ]


def with_ratings(queryset, viewer):
    queryset = queryset.annotate(rating_average=Avg("ratings__score"), rating_count=Count("ratings"))
    if viewer.is_authenticated:
        scores = Rating.objects.filter(placement=OuterRef("pk"), author=viewer).values("score")
        queryset = queryset.annotate(viewer_score=Subquery(scores))
    return queryset


def published_placements():
    return Placement.objects.filter(
        status=Placement.Status.APPROVED, published_at__isnull=False,
    ).select_related("building", "author__profile").order_by("-published_at", "-pk")


def author_rating(author):
    return (
        published_placements().filter(author=author).order_by()
        .annotate(work_average=Avg("ratings__score"))
        .aggregate(average=Avg("work_average"), rated_works=Count("work_average"))
    )


def can_moderate(user):
    return user.is_staff and user.has_perm("placements.moderate_placement")
