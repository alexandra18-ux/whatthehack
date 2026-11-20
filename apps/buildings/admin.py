from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from .models import Building, FacadePhoto, Panorama
from .panoramas import validate_panorama_size

admin.site.register(Building)
admin.site.register(FacadePhoto)


class PanoramaForm(forms.ModelForm):
    def clean_image(self):
        file = self.cleaned_data["image"]
        if isinstance(file, UploadedFile):
            if file.image.format not in {"JPEG", "PNG"} or file.size > 20 * 1024 * 1024:
                raise ValidationError("Загрузите панораму JPEG или PNG размером до 20 МБ.")
            validate_panorama_size(*file.image.size)
        return file


@admin.register(Panorama)
class PanoramaAdmin(admin.ModelAdmin):
    form = PanoramaForm
    list_display = ("title", "building", "is_public")
    list_filter = ("is_public",)
    search_fields = ("title", "building__address")
