import json

from django import forms
from django.core.exceptions import ValidationError

from apps.buildings.models import FacadePhoto
from apps.murals.models import MuralDesign

from .models import Placement
from .services.perspective import read_image, validate_corners
from .text_moderation import validate_public_text


class PlacementDeletionForm(forms.Form):
    reason = forms.CharField(
        label="Причина удаления", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Укажите причину удаления чужой работы."},
    )


class RatingForm(forms.Form):
    score = forms.IntegerField(min_value=1, max_value=5)


class CommentForm(forms.Form):
    text = forms.CharField(max_length=800, label="Комментарий", validators=[validate_public_text])


class ProjectDetailsForm(forms.Form):
    title = forms.CharField(max_length=200, label="Название", validators=[validate_public_text])
    description = forms.CharField(
        max_length=2000, label="Описание", widget=forms.Textarea(attrs={"rows": 3}),
        validators=[validate_public_text],
    )


class GraffitiPhotoForm(ProjectDetailsForm):
    photo = forms.FileField(
        label="Фото граффити", help_text="JPEG или PNG, до 10 МБ.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png"}),
    )
    field_order = ["photo", "title", "description"]

    def __init__(self, *args, revision=None, **kwargs):
        super().__init__(*args, **kwargs)
        if revision:
            self.fields["photo"].required = False
            self.fields["photo"].help_text = "Загрузите JPEG или PNG до 10 МБ или оставьте текущее фото."

    def clean_photo(self):
        photo = self.cleaned_data["photo"]
        return read_image(photo) if photo else None


class PlacementForm(ProjectDetailsForm):
    mural_state = forms.ChoiceField(
        label="Состояние мурала", choices=Placement.MuralState.choices,
        initial=Placement.MuralState.IDEA, required=False,
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

    def __init__(self, *args, building, preview=False, revision=None, **kwargs):
        super().__init__(*args, **kwargs)
        facades = building.facades.filter(is_public=True)
        designs = building.designs.filter(is_public=True)
        if revision:
            facades = facades | FacadePhoto.objects.filter(pk=revision.facade_photo_id)
            designs = designs | MuralDesign.objects.filter(pk=revision.mural_design_id)
        self.fields["facade"].queryset = facades.order_by("pk")
        self.fields["design"].queryset = designs.order_by("pk")
        for name in ("facade_file", "mural_file"):
            self.fields[name].widget.attrs["accept"] = "image/jpeg,image/png"
        if preview:
            del self.fields["title"]
            del self.fields["description"]
            del self.fields["mural_state"]
        else:
            self.fields["corners"].widget.attrs["id"] = "placement-corners"

    def clean_corners(self):
        try:
            corners = json.loads(self.cleaned_data["corners"])
        except (ValueError, RecursionError) as error:
            raise ValidationError("Не удалось прочитать координаты углов.") from error
        return [{"x": float(x), "y": float(y)} for x, y in validate_corners(corners)]

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
