import json

from django import forms
from django.core.exceptions import ValidationError

from apps.buildings.models import FacadePhoto
from apps.murals.models import MuralDesign

from .services.perspective import read_image, validate_corners


class PlacementForm(forms.Form):
    title = forms.CharField(max_length=200, label="Название")
    description = forms.CharField(
        max_length=2000, label="Описание", widget=forms.Textarea(attrs={"rows": 3}),
    )
    facade = forms.ModelChoiceField(
        queryset=FacadePhoto.objects.none(), required=False, label="Готовый фасад",
        empty_label="Выберите фотографию",
    )
    design = forms.ModelChoiceField(
        queryset=MuralDesign.objects.none(), required=False, label="Готовый эскиз",
        empty_label="Выберите эскиз",
    )
    facade_file = forms.FileField(required=False, label="Своё фото фасада")
    mural_file = forms.FileField(required=False, label="Свой эскиз")
    corners = forms.CharField(max_length=512, widget=forms.HiddenInput)

    def __init__(self, *args, building, preview=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["facade"].queryset = building.facades.filter(is_public=True).order_by("pk")
        self.fields["design"].queryset = building.designs.filter(is_public=True).order_by("pk")
        for name in ("facade_file", "mural_file"):
            self.fields[name].widget.attrs["accept"] = "image/jpeg,image/png"
        if preview:
            del self.fields["title"]
            del self.fields["description"]
        else:
            self.fields["corners"].widget.attrs["id"] = "placement-corners"

    def clean_corners(self):
        try:
            corners = json.loads(self.cleaned_data["corners"])
        except (ValueError, RecursionError) as error:
            raise ValidationError("Не удалось прочитать координаты углов.") from error
        validate_corners(corners)
        return corners

    def clean(self):
        data = super().clean()
        for choice, upload, image, transparent in (
            ("facade", "facade_file", "facade_image", False),
            ("design", "mural_file", "mural_image", True),
        ):
            file = data.get(upload)
            asset = data.get(choice)
            if upload in self.errors or choice in self.errors:
                continue
            if not (file or asset):
                self.add_error(upload, "Выберите изображение из каталога или загрузите файл.")
                continue
            try:
                if file:
                    data[image] = read_image(file, transparent=transparent)
                else:
                    with asset.image.open("rb") as stored:
                        data[image] = read_image(stored, transparent=transparent)
            except OSError:
                self.add_error(upload, "Изображение недоступно. Выберите другой файл.")
            except ValidationError as error:
                self.add_error(upload, error)
        return data
