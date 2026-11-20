from django.conf import settings
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
    )
    nickname = models.CharField("Ник", max_length=40, blank=True)
    avatar = models.ImageField("Аватар", upload_to="avatars/", blank=True)

    def __str__(self):
        return self.nickname or self.user.get_username()



class AccountRestriction(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="restrictions")
    banned = models.BooleanField("Блокировка аккаунта", default=False)
    banned_until = models.DateTimeField(null=True, blank=True)
    comments_blocked = models.BooleanField("Запрет на комментарии", default=False)
    comments_blocked_until = models.DateTimeField(null=True, blank=True)
    publications_blocked = models.BooleanField("Запрет на отправку работ", default=False)
    publications_blocked_until = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def _active(enabled, expires_at):
        return enabled and (expires_at is None or expires_at > timezone.now())

    @property
    def ban_active(self):
        return self._active(self.banned, self.banned_until)

    @property
    def comments_block_active(self):
        return self._active(self.comments_blocked, self.comments_blocked_until)

    @property
    def publications_block_active(self):
        return self._active(self.publications_blocked, self.publications_blocked_until)
