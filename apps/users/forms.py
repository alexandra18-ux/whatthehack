from django import forms
from django.contrib.auth.forms import UserCreationForm
from PIL import ImageOps

from apps.placements.services.perspective import encode_image, read_image
from apps.placements.text_moderation import validate_public_text


class RegistrationForm(UserCreationForm):
    def clean_username(self):
        username = super().clean_username()
        validate_public_text(username)
        return username


class ProfileEmailForm(forms.Form):
    email = forms.EmailField(label="Email для восстановления", max_length=254)


class ProfileForm(forms.Form):
    nickname = forms.CharField(label="Ник", max_length=40, required=False, validators=[validate_public_text])
    avatar = forms.FileField(
        label="Новый аватар", required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png"}),
    )

    def clean_avatar(self):
        upload = self.cleaned_data["avatar"]
        if not upload:
            return None
        image = ImageOps.fit(read_image(upload, transparent=True), (256, 256))
        return encode_image(image, png=True)
