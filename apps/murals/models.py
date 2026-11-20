from django.conf import settings
from django.db import models


class MuralDesign(models.Model):
    title = models.CharField("Название", max_length=200)
    image = models.ImageField(upload_to="designs/")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    buildings = models.ManyToManyField("buildings.Building", related_name="designs")
    is_public = models.BooleanField("В каталоге", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
