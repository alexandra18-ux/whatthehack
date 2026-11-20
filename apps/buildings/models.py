from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Building(models.Model):
    address = models.CharField("Адрес", max_length=220)
    osm_ref = models.CharField(max_length=24, unique=True, null=True, blank=True, editable=False)
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
    panorama = models.ForeignKey("Panorama", null=True, blank=True, on_delete=models.PROTECT)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    is_public = models.BooleanField("В каталоге", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.building} · фото {self.pk}"


class Panorama(models.Model):
    title = models.CharField("Название", max_length=180)
    building = models.ForeignKey(Building, related_name="panoramas", on_delete=models.PROTECT)
    image = models.ImageField("Панорама 360°", upload_to="panoramas/")
    initial_heading = models.FloatField("Начальный поворот в градусах", default=0)
    credit = models.CharField("Автор или источник", max_length=180, blank=True)
    source_url = models.URLField("Оригинал", blank=True)
    license_name = models.CharField("Лицензия", max_length=80, blank=True)
    license_url = models.URLField("Ссылка на лицензию", blank=True)
    is_public = models.BooleanField("Доступна в редакторе", default=False)

    def __str__(self):
        return self.title
