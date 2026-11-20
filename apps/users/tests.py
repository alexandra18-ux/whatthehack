import re
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from .models import Profile


class PasswordRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(
            username="artist", password="initial-password-49", email="legacy@example.com",
        )

    def extract_path(self, message):
        return urlsplit(re.search(r"http://testserver/[^\s]+", message.body).group()).path

    def test_confirmed_profile_email_supports_one_time_password_reset(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.user)
        self.assertContains(owner.get(reverse("mine"), {"tab": "settings"}), "Почта для восстановления")
        address = "artist@example.org"
        verification = reverse("request_profile_email")
        self.assertEqual(owner.post(
            verification, {"email": address},
            headers={"X-CSRFToken": owner.cookies["csrftoken"].value, "Origin": "http://testserver"},
        ).status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        confirmation = self.extract_path(mail.outbox[0])
        self.assertEqual(mail.outbox[0].to, [address])
        self.assertIsNone(Profile.objects.get(user=self.user).verified_email)

        stranger = Client()
        stranger.force_login(get_user_model().objects.create_user(username="stranger"))
        self.assertContains(stranger.post(confirmation), "Ссылка недействительна")
        page = owner.get(confirmation)
        self.assertContains(page, "Подтвердить почту")
        self.assertEqual(page.headers["Referrer-Policy"], "same-origin")
        self.assertIsNone(Profile.objects.get(user=self.user).verified_email)

        csrf_headers = {"X-CSRFToken": owner.cookies["csrftoken"].value, "Origin": "http://testserver"}
        self.assertEqual(owner.post(confirmation, headers={"Origin": "http://testserver"}).status_code, 403)
        self.assertRedirects(owner.post(confirmation, headers=csrf_headers), reverse("mine") + "?tab=settings")
        self.assertContains(owner.post(confirmation, headers=csrf_headers), "Ссылка недействительна")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, address)

        visitor = Client()
        reset = reverse("password_reset")
        sent = reverse("password_reset_done")
        self.assertContains(visitor.get(reverse("login")), "Забыли пароль?")
        self.assertRedirects(visitor.post(reset, {"email": "unknown@example.org"}), sent)
        self.assertRedirects(visitor.post(reset, {"email": "legacy@example.com"}), sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertRedirects(visitor.post(reset, {"email": "Artist@example.org"}), sent)
        self.assertRedirects(visitor.post(reset, {"email": address}), sent)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[-1].to, [address])

        reset_link = self.extract_path(mail.outbox[-1])
        response = visitor.get(reset_link)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(visitor.post(response.url, {
            "new_password1": "replacement-password-34", "new_password2": "replacement-password-34",
        }), reverse("password_reset_complete"))
        self.assertTrue(Client().login(username=self.user.username, password="replacement-password-34"))
        self.assertContains(Client().get(reset_link), "Ссылка недействительна")

    def test_confirmed_address_is_replaced_only_after_verifying_new_address(self):
        old_address = self.user.email
        new_address = "replacement@example.org"
        Profile.objects.create(user=self.user, verified_email=old_address)
        self.client.force_login(self.user)
        settings_url = reverse("mine") + "?tab=settings"
        settings_page = self.client.get(settings_url)
        self.assertContains(settings_page, old_address)
        self.assertContains(settings_page, '<summary class="button outline">Поменять почту</summary>', html=True)
        self.assertNotContains(settings_page, 'name="password"')

        self.assertRedirects(
            self.client.post(reverse("request_profile_email"), {"email": new_address}), settings_url,
        )
        self.assertContains(self.client.get(settings_url), "Ожидает подтверждения")
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.verified_email, old_address)
        self.assertEqual(profile.pending_email, new_address)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, old_address)

        confirmation = self.extract_path(mail.outbox[0])
        self.assertEqual(mail.outbox[0].to, [new_address])
        self.assertRedirects(self.client.post(confirmation), settings_url)
        profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(profile.verified_email, new_address)
        self.assertEqual(self.user.email, new_address)
        self.assertFalse(profile.pending_email)
        self.assertNotContains(self.client.get(settings_url), old_address)
