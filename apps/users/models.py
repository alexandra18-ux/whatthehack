from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
    )
    nickname = models.CharField("Ник", max_length=40, blank=True)
    avatar = models.ImageField("Аватар", upload_to="avatars/", blank=True)

    def __str__(self):
        return self.nickname or self.user.get_username()
