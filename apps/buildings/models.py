from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Building(models.Model):
    address = models.CharField("Адрес", max_length=220)
    latitude = models.DecimalField(
        "Широта", max_digits=9, decimal_places=6,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        "Долгота", max_digits=9, decimal_places=6,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["address", "pk"]

    def __str__(self):
        return self.address


class FacadePhoto(models.Model):
    building = models.ForeignKey(Building, related_name="facades", on_delete=models.PROTECT)
    image = models.ImageField(upload_to="facades/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    is_public = models.BooleanField("В каталоге", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.building} · фото {self.pk}"
