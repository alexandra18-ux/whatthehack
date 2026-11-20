import hashlib
import logging
import secrets
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import PasswordResetDoneView, PasswordResetView
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .forms import ProfileEmailForm
from .models import Profile


logger = logging.getLogger(__name__)


EMAIL_TOKEN_SALT = "users.verify-recovery-email"
EMAIL_TOKEN_TIMEOUT = 30 * 60


def settings_url():
    return reverse("mine") + "?tab=settings"


def email_frequency_key(action, value):
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"recovery:{action}:{digest}"


class ConfirmedEmailResetForm(PasswordResetForm):
    def get_users(self, email):
        verified = email.casefold()
        return (
            user for user in super().get_users(verified)
            if getattr(getattr(user, "profile", None), "verified_email", None) == verified
            and not getattr(getattr(user, "restrictions", None), "ban_active", False)
        )


def uses_console_email():
    return settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


class AccountPasswordResetDoneView(PasswordResetDoneView):
    def get_context_data(self, **kwargs):
        return super().get_context_data(console_email=uses_console_email(), **kwargs)


class AccountPasswordResetView(PasswordResetView):
    form_class = ConfirmedEmailResetForm
    template_name = "registration/password_reset_form.html"
    subject_template_name = "registration/password_reset_subject.txt"
    email_template_name = "registration/password_reset_email.txt"

    def form_valid(self, form):
        address_key = email_frequency_key("password", form.cleaned_data["email"].casefold())
        ip_key = email_frequency_key("ip", self.request.META.get("REMOTE_ADDR", ""))
        if cache.add(ip_key, 1, timeout=600):
            count = 1
        else:
            try:
                count = cache.incr(ip_key)
            except ValueError:
                cache.add(ip_key, 1, timeout=600)
                count = 1
        if count > 20 or not cache.add(address_key, 1, timeout=60):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


@login_required
@require_POST
def request_email_verification(request):
    form = ProfileEmailForm(request.POST)
    if not form.is_valid():
        messages.error(request, next(iter(form.errors.values()))[0])
        return redirect(settings_url())

    address = form.cleaned_data["email"].casefold()
    if len(address) > 254:
        messages.error(request, "Почтовый адрес слишком длинный.")
        return redirect(settings_url())
    key = email_frequency_key("verification", str(request.user.pk))
    if not cache.add(key, 1, timeout=60):
        messages.info(request, "Повторить отправку можно через минуту.")
        return redirect(settings_url())

    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        profile, _ = Profile.objects.select_for_update().get_or_create(user=user)
        if profile.verified_email == address and user.email == address:
            messages.info(request, "Этот адрес уже подтверждён.")
            cache.delete(key)
            return redirect(settings_url())
        profile.pending_email = address
        profile.email_verification_nonce = secrets.token_urlsafe(32)
        profile.save(update_fields=["pending_email", "email_verification_nonce"])

    token = signing.dumps({"user": user.pk, "nonce": profile.email_verification_nonce}, salt=EMAIL_TOKEN_SALT)
    url = request.build_absolute_uri(reverse("verify_profile_email", args=[token]))
    try:
        send_mail(
            "Подтверждение почты · Murrralium",
            render_to_string("registration/email_verification_email.txt", {"url": url}),
            settings.DEFAULT_FROM_EMAIL,
            [address],
        )
    except (OSError, SMTPException) as error:
        smtp_code = getattr(error, "smtp_code", None)
        if smtp_code is None and getattr(error, "recipients", None):
            smtp_code = next(iter(error.recipients.values()))[0]
        logger.warning(
            "Recovery email delivery failed (%s, SMTP status: %s)",
            type(error).__name__,
            smtp_code,
        )
        cache.delete(key)
        messages.error(request, "Не удалось отправить письмо. Попробуйте ещё раз позже.")
    else:
        if uses_console_email():
            messages.success(request, "Тестовое письмо со ссылкой для подтверждения записано в журнал Django.")
        else:
            messages.success(request, "Ссылка для подтверждения отправлена на указанную почту.")
    return redirect(settings_url())


def valid_verification(profile, token):
    return (
        profile is not None and profile.user_id == token["user"] and profile.pending_email
        and constant_time_compare(profile.email_verification_nonce, token["nonce"])
    )


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def verify_profile_email(request, token):
    try:
        data = signing.loads(token, salt=EMAIL_TOKEN_SALT, max_age=EMAIL_TOKEN_TIMEOUT)
    except signing.BadSignature:
        data = None

    if data and data["user"] == request.user.pk and request.method == "POST":
        try:
            with transaction.atomic():
                user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                profile = Profile.objects.select_for_update().filter(user=user).first()
                if valid_verification(profile, data):
                    profile.verified_email = profile.pending_email
                    profile.pending_email = ""
                    profile.email_verification_nonce = ""
                    profile.save(update_fields=["verified_email", "pending_email", "email_verification_nonce"])
                    user.email = profile.verified_email
                    user.save(update_fields=["email"])
                    messages.success(request, "Почта подтверждена.")
                    return redirect(settings_url())
        except IntegrityError:
            messages.error(request, "Не удалось привязать этот адрес. Укажите другой.")
            return redirect(settings_url())
    profile = Profile.objects.filter(user=request.user).first()
    address = profile.pending_email if data and valid_verification(profile, data) else ""
    response = render(request, "registration/email_verification.html", {
        "address": address if request.method == "GET" else "",
    })
    # Keep the form's same-origin POST compatible with Django's CSRF checks.
    response.headers["Referrer-Policy"] = "same-origin"
    return response
