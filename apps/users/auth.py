from django.contrib.auth.backends import ModelBackend


class AccountBackend(ModelBackend):
    def user_can_authenticate(self, user):
        restriction = getattr(user, "restrictions", None)
        return super().user_can_authenticate(user) and not (restriction and restriction.ban_active)



def can_manage_restrictions(moderator, account):
    from apps.placements.models import can_moderate

    return (
        can_moderate(moderator) and account.pk != moderator.pk and not account.is_superuser
        and (moderator.is_superuser or not account.is_staff)
    )
