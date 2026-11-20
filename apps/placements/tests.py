import io
import json
from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from PIL import Image

from apps.buildings.models import Building
from apps.users.models import AccountRestriction

from .models import Comment, CommentDeletion, CommentLike, ModerationDecision, Placement, Rating


class PlacementWorkflowTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.enterContext(self.settings(MEDIA_ROOT=media.name))
        self.building = Building.objects.create(
            address="Тестовый фасад", latitude=51.529990, longitude=46.035350,
        )
        self.owner = get_user_model().objects.create_user(username="author")
        self.client.force_login(self.owner)
        self.corners = [
            {"x": .15, "y": .15}, {"x": .85, "y": .15},
            {"x": .85, "y": .85}, {"x": .15, "y": .85},
        ]

    def upload(self, name, mode, color):
        buffer = io.BytesIO()
        Image.new(mode, (80, 60), color).save(buffer, format="PNG")
        return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

    def payload(self):
        return {
            "building": self.building.pk,
            "title": "Мурал",
            "description": "Проверка публикации",
            "corners": json.dumps(self.corners),
            "facade_file": self.upload("facade.png", "RGB", (200, 200, 200)),
            "mural_file": self.upload("mural.png", "RGBA", (0, 100, 200, 128)),
        }

    def test_preview_preserves_facade_and_blends_transparent_design(self):
        response = self.client.post(reverse("preview"), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.getpixel((0, 0)), (200, 200, 200))
        self.assertEqual(image.getpixel((40, 30)), (100, 150, 200))
        self.assertFalse(Placement.objects.exists())

    def test_invalid_corners_and_image_produce_field_errors(self):
        payload = self.payload()
        payload["corners"] = json.dumps([*self.corners[:3], {"x": .7, "y": .4}])
        payload["mural_file"] = SimpleUploadedFile("broken.png", b"invalid")
        response = self.client.post(reverse("preview"), payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("corners", response.json()["errors"])
        self.assertIn("mural_file", response.json()["errors"])

    def test_corner_order_does_not_change_preview(self):
        expected = self.client.post(reverse("preview"), self.payload())
        for order in [(0, 3, 2, 1), (2, 0, 3, 1)]:
            payload = self.payload()
            payload["corners"] = json.dumps([self.corners[index] for index in order])
            response = self.client.post(reverse("preview"), payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, expected.content)

    def test_preview_accepts_shallow_convex_corner(self):
        payload = self.payload()
        payload["corners"] = json.dumps([
            {"x": .9, "y": .10003}, {"x": .1, "y": .1},
            {"x": .2, "y": .9}, {"x": .5, "y": .10001},
        ])
        response = self.client.post(reverse("preview"), payload)
        self.assertEqual(response.status_code, 200)
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.getpixel((30, 20)), (100, 150, 200))

    def test_preview_accepts_small_fraction_of_photo_with_enough_pixels(self):
        payload = self.payload()
        payload["corners"] = json.dumps([
            {"x": .48, "y": .48}, {"x": .52, "y": .48},
            {"x": .52, "y": .52}, {"x": .48, "y": .52},
        ])
        response = self.client.post(reverse("preview"), payload)
        self.assertEqual(response.status_code, 200)
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.getpixel((40, 30)), (100, 150, 200))

    def test_preview_rejects_area_smaller_than_a_pixel(self):
        payload = self.payload()
        payload["corners"] = json.dumps([
            {"x": .5, "y": .5}, {"x": .501, "y": .5},
            {"x": .501, "y": .501}, {"x": .5, "y": .501},
        ])
        response = self.client.post(reverse("preview"), payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("слишком мала для этого фото", response.json()["error"])

    def test_moderation_controls_project_visibility_and_keeps_assets_private(self):
        response = self.client.post(reverse("create"), {**self.payload(), "status": "approved"})
        project = Placement.objects.get()
        detail = reverse("placement", args=[project.pk])
        result = reverse("project_image", args=[project.pk, "result"])
        before = reverse("project_image", args=[project.pk, "before"])
        facade = reverse("asset", args=["facade", project.facade_photo_id])
        design = reverse("asset", args=["design", project.mural_design_id])
        admin = reverse("admin:placements_placement_change", args=[project.pk])
        self.assertRedirects(response, detail)
        self.assertEqual(project.status, Placement.Status.PENDING)
        response = self.client.get(result)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content))
        self.assertNotEqual(self.client.post(admin, {"status": "approved"}).status_code, 200)

        visitor = Client()
        for url in (detail, result, before, facade, design):
            self.assertEqual(visitor.get(url).status_code, 404)
        self.assertEqual(visitor.get(reverse("map_api")).json(), {"projects": []})

        moderator = get_user_model().objects.create_user(username="moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        self.client.force_login(moderator)
        self.assertEqual(self.client.get(admin).status_code, 200)
        self.assertEqual(self.client.post(admin, {"status": "approved", "rejection_reason": ""}).status_code, 302)

        project.refresh_from_db()
        self.assertIsNotNone(project.published_at)
        decision = ModerationDecision.objects.get(placement=project)
        self.assertEqual((decision.moderator, decision.status), (moderator, Placement.Status.APPROVED))
        for url in (detail, result, before):
            response = visitor.get(url)
            self.assertEqual(response.status_code, 200)
            if response.streaming:
                self.assertTrue(b"".join(response.streaming_content))
        for url in (facade, design):
            self.assertEqual(visitor.get(url).status_code, 404)
        self.assertEqual(visitor.get(reverse("map_api")).json()["projects"][0]["id"], project.pk)
        self.assertContains(visitor.get(reverse("home")), project.title)

    def test_site_moderation_requires_permission_and_applies_decisions(self):
        rejected = self.create_work("Работа для отказа")
        approved = self.create_work("Работа для публикации")
        queue = reverse("moderation_queue")
        history = reverse("moderation_history")
        reject_url = reverse("moderation_review", args=[rejected.pk])
        approve_url = reverse("moderation_review", args=[approved.pk])

        self.assertEqual(Client().get(queue).status_code, 302)
        self.assertNotContains(self.client.get(reverse("home")), f'href="{queue}"')
        self.assertEqual(self.client.get(queue).status_code, 403)
        self.assertEqual(self.client.get(history).status_code, 403)
        self.assertEqual(self.client.post(approve_url, {"status": "approved"}).status_code, 403)

        moderator = get_user_model().objects.create_user(username="site-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        self.client.force_login(moderator)

        self.assertContains(self.client.get(reverse("home")), f'href="{queue}"')
        response = self.client.get(queue)
        self.assertEqual(list(response.context["page"]), [rejected, approved])
        self.assertContains(self.client.get(reject_url), "Решение по заявке")
        response = self.client.post(reject_url, {"status": "rejected"})
        self.assertContains(response, "Укажите причину отклонения.")
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Placement.Status.PENDING)
        self.assertRedirects(self.client.post(reject_url, {
            "status": "rejected", "rejection_reason": "Нужен новый эскиз",
        }), queue)
        self.assertRedirects(self.client.post(approve_url, {
            "status": "approved", "rejection_reason": "Не относится к публикации",
        }), queue)
        self.assertRedirects(self.client.post(reject_url, {"status": "approved"}), queue)

        rejected.refresh_from_db()
        approved.refresh_from_db()
        self.assertEqual(rejected.status, Placement.Status.REJECTED)
        self.assertEqual(rejected.rejection_reason, "Нужен новый эскиз")
        self.assertIsNone(rejected.published_at)
        self.assertEqual(approved.status, Placement.Status.APPROVED)
        self.assertIsNotNone(approved.published_at)
        self.assertEqual(approved.rejection_reason, "")
        decisions = list(ModerationDecision.objects.values_list("moderator_username", "status", "rejection_reason"))
        self.assertEqual(decisions, [
            ("site-moderator", "approved", ""),
            ("site-moderator", "rejected", "Нужен новый эскиз"),
        ])
        response = self.client.get(history)
        self.assertContains(response, "site-moderator")
        self.assertContains(response, "Нужен новый эскиз")
        self.assertEqual(list(self.client.get(queue).context["page"]), [])
        self.assertContains(Client().get(reverse("home")), approved.title)

    def test_comment_filter_and_moderator_deletion(self):
        project = self.create_work("Мурал для обсуждения", timezone.now())
        comment_url = reverse("comment", args=[project.pk])
        detail = reverse("placement", args=[project.pk])
        comment_list = reverse("moderation_comments")
        words = ("БЛЯТЬ!", "Ну, СУКА.", "ＦＵＣＨ", "Долбоёб")
        for text in words:
            with self.subTest(text=text):
                response = self.client.post(comment_url, {"text": text}, follow=True)
                self.assertContains(response, "запрещено уберите его и отправьте снова.")
                self.assertIn(response.context["comment_draft"]["error"].split('"')[1], ("БЛЯТЬ", "СУКА", "FUCH", "Долбоёб"))
                self.assertContains(response, text)
                self.assertFalse(project.comments.exists())

        response = self.client.post(comment_url, {"text": "СУКА!"}, headers={"X-Muralium-Async": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertIn('"СУКА"', response.json()["error"])
        self.assertFalse(project.comments.exists())

        self.client.post(comment_url, {"text": "Круглый сучок на фасаде"})
        entry = project.comments.get()
        delete = reverse("moderation_delete_comment", args=[entry.pk])
        self.assertNotContains(self.client.get(detail), delete)
        self.assertEqual(self.client.get(comment_list).status_code, 403)
        self.assertEqual(self.client.post(delete).status_code, 403)

        moderator = get_user_model().objects.create_user(username="comment-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        reviewer = Client()
        reviewer.force_login(moderator)
        self.assertContains(reviewer.get(detail), delete)
        self.assertContains(reviewer.get(comment_list, {"q": "сучок"}), entry.text)
        self.assertEqual(reviewer.get(delete).status_code, 405)
        self.assertRedirects(reviewer.post(delete), f"{detail}#comments")
        self.assertFalse(project.comments.exists())

        self.client.post(comment_url, {"text": "Новый комментарий"})
        delete = reverse("moderation_delete_comment", args=[project.comments.get().pk])
        self.assertRedirects(reviewer.post(delete, {"source": "moderation"}), comment_list)
        self.assertFalse(project.comments.exists())
        self.assertEqual(CommentDeletion.objects.filter(
            placement=project, author_username=self.owner.username, moderator_username=moderator.username,
        ).count(), 2)
        self.assertEqual(reviewer.post(delete).status_code, 404)
        self.assertEqual(CommentDeletion.objects.count(), 2)

        history = reverse("moderation_history")
        self.assertEqual(self.client.get(history, {"kind": "comments"}).status_code, 403)
        response = reviewer.get(history, {
            "kind": "comments", "title": project.title, "author": self.owner.username, "moderator": moderator.username,
        })
        self.assertContains(response, entry.text)
        self.assertContains(response, "Новый комментарий")
        self.assertContains(response, moderator.username)
        self.assertNotContains(self.client.get(detail), entry.text)

    def test_filter_blocks_public_work_metadata_and_profile_names(self):
        payload = self.payload()
        payload.update(title="Фасад: СУКА!", description="Эскиз FUCH")
        response = self.client.post(reverse("create"), payload)
        self.assertContains(response, escape('Слово "СУКА" запрещено уберите его и отправьте снова.'))
        self.assertContains(response, escape('Слово "FUCH" запрещено уберите его и отправьте снова.'))
        self.assertFalse(Placement.objects.exists())

        response = self.client.post(reverse("mine"), {"nickname": "Блять художник"})
        self.assertContains(response, escape('Слово "Блять" запрещено уберите его и отправьте снова.'))
        self.assertFalse(hasattr(self.owner, "profile"))

        response = Client().post(reverse("register"), {
            "username": "fuch_artist", "password1": "strong-test-password", "password2": "strong-test-password",
        })
        self.assertContains(response, escape('Слово "fuch" запрещено уберите его и отправьте снова.'))
        self.assertFalse(get_user_model().objects.filter(username="fuch_artist").exists())

    def test_moderator_account_restrictions_and_unban(self):
        project = self.create_work("Мурал для проверки ограничений", timezone.now())
        needs_revision = self.create_work("Мурал на доработке")
        Placement.objects.filter(pk=needs_revision.pk).update(status=Placement.Status.REVISION)
        moderator = get_user_model().objects.create_user(username="sanctions-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        reviewer = Client()
        reviewer.force_login(moderator)
        restriction_url = reverse("moderation_restrict_account", args=[self.owner.pk])
        comment_url = reverse("comment", args=[project.pk])
        create_url = reverse("create")
        revise_url = reverse("revise", args=[needs_revision.pk])
        self.owner.set_password("test-author-password")
        self.owner.save(update_fields=["password"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(restriction_url, {"banned": "indefinite"}).status_code, 403)
        self.assertEqual(reviewer.post(
            reverse("moderation_restrict_account", args=[moderator.pk]), {"banned": "indefinite"},
        ).status_code, 403)

        self.assertRedirects(reviewer.post(restriction_url, {"comments_blocked": "indefinite"}), restriction_url)
        self.client.post(comment_url, {"text": "Этот комментарий запрещён"})
        self.assertFalse(project.comments.exists())
        self.assertEqual(self.client.get(create_url, {"building": self.building.pk}).status_code, 200)

        self.assertRedirects(reviewer.post(restriction_url, {"publications_blocked": "indefinite"}), restriction_url)
        self.client.post(comment_url, {"text": "Комментировать снова можно"})
        self.assertEqual(project.comments.count(), 1)
        self.assertEqual(self.client.post(create_url, self.payload()).status_code, 403)
        self.assertEqual(self.client.get(revise_url).status_code, 403)
        self.assertEqual(self.client.post(reverse("preview"), self.payload()).status_code, 403)

        self.assertRedirects(reviewer.post(restriction_url, {"banned": "indefinite"}), restriction_url)
        self.assertEqual(self.client.get(reverse("mine")).status_code, 302)
        self.assertFalse(Client().login(username=self.owner.username, password="test-author-password"))
        self.assertTrue(AccountRestriction.objects.get(user=self.owner).banned)
        self.assertRedirects(reviewer.post(restriction_url, {}), restriction_url)
        self.assertTrue(Client().login(username=self.owner.username, password="test-author-password"))

    def test_temporary_restrictions_expire_independently(self):
        project = self.create_work("Мурал для временных ограничений", timezone.now())
        moderator = get_user_model().objects.create_user(username="timed-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        reviewer = Client()
        reviewer.force_login(moderator)
        restrict_url = reverse("moderation_restrict_account", args=[self.owner.pk])
        comment_url = reverse("comment", args=[project.pk])
        create_url = reverse("create")
        now = timezone.now()
        response = reviewer.post(restrict_url, {"banned": "999"})
        self.assertIn("banned", response.context["form"].errors)
        self.assertFalse(AccountRestriction.objects.filter(user=self.owner).exists())

        self.assertRedirects(reviewer.post(restrict_url, {
            "comments_blocked": "24",
            "publications_blocked": "3",
        }), restrict_url)
        restriction = AccountRestriction.objects.get(user=self.owner)
        self.assertGreaterEqual(restriction.comments_blocked_until, now + timedelta(days=1))
        self.assertLess(restriction.comments_blocked_until, now + timedelta(days=1, minutes=1))
        self.assertGreaterEqual(restriction.publications_blocked_until, now + timedelta(hours=3))
        self.assertLess(restriction.publications_blocked_until, now + timedelta(hours=3, minutes=1))
        self.assertContains(reviewer.get(restrict_url), "Сохранить текущий срок")
        self.assertRedirects(reviewer.post(restrict_url, {
            "comments_blocked": "keep",
            "publications_blocked": "keep",
        }), restrict_url)
        self.assertEqual(
            AccountRestriction.objects.get(user=self.owner).comments_blocked_until,
            restriction.comments_blocked_until,
        )
        self.client.post(comment_url, {"text": "Срок пока не истёк"})
        self.assertFalse(project.comments.exists())
        self.assertEqual(self.client.get(create_url, {"building": self.building.pk}).status_code, 403)

        restriction.comments_blocked_until = now - timedelta(seconds=1)
        restriction.save(update_fields=["comments_blocked_until"])
        self.client.post(comment_url, {"text": "Срок запрета комментариев истёк"})
        self.assertEqual(project.comments.count(), 1)
        self.assertEqual(self.client.get(create_url, {"building": self.building.pk}).status_code, 403)

        restriction.publications_blocked_until = now - timedelta(seconds=1)
        restriction.save(update_fields=["publications_blocked_until"])
        self.assertEqual(self.client.get(create_url, {"building": self.building.pk}).status_code, 200)

        self.owner.set_password("temporary-ban-password")
        self.owner.save(update_fields=["password"])
        self.assertRedirects(reviewer.post(restrict_url, {
            "banned": "24",
        }), restrict_url)
        self.assertFalse(Client().login(username=self.owner.username, password="temporary-ban-password"))
        AccountRestriction.objects.filter(pk=restriction.pk).update(banned_until=now - timedelta(seconds=1))
        self.assertTrue(Client().login(username=self.owner.username, password="temporary-ban-password"))
        self.assertEqual(reviewer.get(restrict_url).context["form"]["banned"].value(), "off")

    def test_moderation_user_directory_profile_links_and_clear_all(self):
        expired = get_user_model().objects.create_user(username="directory-expired")
        AccountRestriction.objects.create(
            user=expired, comments_blocked=True, comments_blocked_until=timezone.now() - timedelta(seconds=1),
        )
        self.client.post(reverse("mine"), {"nickname": "Мастер фасадов"})
        moderator = get_user_model().objects.create_user(username="directory-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        reviewer = Client()
        reviewer.force_login(moderator)
        directory = reverse("moderation_accounts")
        profile = reverse("profile", args=[self.owner.pk])
        restrict_url = reverse("moderation_restrict_account", args=[self.owner.pk])

        self.assertEqual(self.client.get(directory).status_code, 403)
        self.assertNotContains(self.client.get(profile), restrict_url)
        self.assertContains(reviewer.get(profile), restrict_url)
        self.assertContains(reviewer.get(directory), expired.username)
        self.assertContains(reviewer.get(directory, {"q": "Мастер"}), restrict_url)

        self.assertRedirects(reviewer.post(restrict_url, {
            "comments_blocked": "24",
            "publications_blocked": "indefinite",
        }), restrict_url)
        response = reviewer.get(directory, {"status": "restricted"})
        self.assertContains(response, self.owner.username)
        self.assertNotContains(response, expired.username)

        self.assertRedirects(reviewer.post(restrict_url, {"action": "clear"}), restrict_url)
        self.assertNotContains(reviewer.get(directory, {"status": "restricted"}), restrict_url)
        restriction = AccountRestriction.objects.get(user=self.owner)
        self.assertFalse(restriction.comments_block_active)
        self.assertFalse(restriction.publications_block_active)
        self.assertIsNone(restriction.comments_blocked_until)

    def test_author_revises_same_application_and_moderator_history_is_preserved(self):
        project = self.create_work("Мурал для доработки")
        moderator = get_user_model().objects.create_user(username="revision-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        reviewer = Client()
        reviewer.force_login(moderator)
        other = Client()
        other.force_login(get_user_model().objects.create_user(username="other-author"))
        review = reverse("moderation_review", args=[project.pk])
        revise = reverse("revise", args=[project.pk])
        preview = reverse("revision_preview", args=[project.pk])
        history = reverse("moderation_history")
        queue = reverse("moderation_queue")
        home = reverse("home")
        notes = "Сдвиньте эскиз левее"
        result = project.result_image.name

        self.assertEqual(self.client.get(revise).status_code, 404)
        self.assertContains(reviewer.post(review, {"status": "revision"}), "Укажите, что автору нужно исправить.")
        self.assertRedirects(reviewer.post(review, {
            "status": "revision", "revision_notes": notes, "rejection_reason": "Лишний текст",
        }), queue)
        self.assertNotContains(Client().get(home), project.title)
        project.refresh_from_db()
        self.assertEqual(project.status, Placement.Status.REVISION)
        self.assertEqual(project.rejection_reason, "")
        self.assertContains(self.client.get(reverse("mine")), notes)
        self.assertNotContains(other.get(reverse("mine")), notes)
        self.assertContains(self.client.get(revise), notes)
        self.assertEqual(other.get(revise).status_code, 404)

        data = {
            "facade": project.facade_photo_id, "design": project.mural_design_id,
            "corners": json.dumps(project.corners),
        }
        self.assertEqual(other.post(preview, data).status_code, 404)
        self.assertEqual(self.client.post(preview, data)["Content-Type"], "image/png")
        self.assertRedirects(self.client.post(revise, {
            **data, "title": project.title, "description": "Исправленное описание",
        }), reverse("placement", args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual(Placement.objects.count(), 1)
        self.assertEqual(project.status, Placement.Status.PENDING)
        self.assertEqual(project.description, "Исправленное описание")
        self.assertNotEqual(project.result_image.name, result)
        self.assertEqual(self.client.post(revise, data).status_code, 404)

        response = reviewer.get(review)
        self.assertContains(response, notes)
        self.assertContains(response, reverse("asset", args=["design", project.mural_design_id]))
        self.assertRedirects(reviewer.post(review, {"status": "approved"}), queue)
        self.assertContains(Client().get(home), project.title)
        self.assertContains(self.client.get(reverse("mine")), "Опубликован")

        response = reviewer.get(history, {
            "title": "Мурал", "moderator": "revision-moderator",
            "status": "revision", "date": timezone.localdate().isoformat(),
        })
        self.assertEqual([decision.status for decision in response.context["page"]], [
            Placement.Status.REVISION,
        ])
        self.assertContains(response, notes)
        self.assertEqual(list(project.moderation_decisions.values_list("status", flat=True)), [
            Placement.Status.APPROVED, Placement.Status.REVISION,
        ])

    def test_admin_defaults_to_oldest_pending_applications_and_can_switch_status(self):
        oldest = self.create_work("Первая заявка")
        newest = self.create_work("Вторая заявка")
        published = self.create_work("Опубликованная работа", timezone.now())
        rejected = self.create_work("Отклонённая работа")
        Placement.objects.filter(pk=rejected.pk).update(status=Placement.Status.REJECTED)

        moderator = get_user_model().objects.create_user(username="queue-moderator", is_staff=True)
        moderator.user_permissions.add(Permission.objects.get(codename="moderate_placement"))
        self.client.force_login(moderator)
        queue = reverse("admin:placements_placement_changelist")

        for status, expected in (
            (None, [oldest, newest]),
            ("approved", [published]),
            ("rejected", [rejected]),
            ("all", [rejected, published, newest, oldest]),
        ):
            with self.subTest(status=status):
                response = self.client.get(queue, {"moderation_status": status} if status else {})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["cl"].result_list), expected)

    def test_published_projects_accept_one_editable_rating_and_comments(self):
        self.client.post(reverse("create"), self.payload())
        project = Placement.objects.get()
        rate = reverse("rate", args=[project.pk])
        comment = reverse("comment", args=[project.pk])
        self.assertEqual(self.client.post(rate, {"score": 4}).status_code, 404)
        self.assertEqual(self.client.post(comment, {"text": "Комментарий"}).status_code, 404)

        project.status = Placement.Status.APPROVED
        project.published_at = timezone.now()
        project.save(update_fields=["status", "published_at"])
        visitor = Client()
        self.assertEqual(visitor.post(rate, {"score": 4}).status_code, 302)
        self.assertEqual(visitor.post(comment, {"text": "От гостя"}).status_code, 302)
        self.assertFalse(Rating.objects.exists())
        self.assertFalse(Comment.objects.exists())

        self.client.post(rate, {"score": 4})
        self.client.post(rate, {"score": 5})
        self.client.post(rate, {"score": 0})
        self.assertEqual(list(Rating.objects.values_list("score", flat=True)), [5])
        self.client.post(comment, {"text": "Хорошая работа!"})
        self.client.post(comment, {"text": "  "})
        self.assertEqual(list(Comment.objects.values_list("text", flat=True)), ["Хорошая работа!"])
        feed = visitor.get(reverse("home"))
        self.assertContains(feed, "Хорошая работа!")
        self.assertContains(feed, "5,0 из 5")

    def test_feed_switches_one_work_and_its_discussion_together(self):
        published_at = timezone.now()
        older = self.create_work("Первая работа", published_at)
        latest = self.create_work("Вторая работа", published_at)
        pending = self.create_work("Скрытая работа")
        Comment.objects.create(placement=older, author=self.owner, text="Комментарий первой работы")
        Comment.objects.create(placement=latest, author=self.owner, text="Комментарий второй работы")
        url = reverse("home")

        response = self.client.get(url)
        self.assertContains(response, "Вторая работа")
        self.assertContains(response, "Комментарий второй работы")
        self.assertNotContains(response, "Первая работа")
        self.assertNotContains(response, "Комментарий первой работы")
        self.assertEqual(response.context["next_post"], older.pk)
        self.assertEqual(response.context["previous_post"], older.pk)

        response = self.client.get(url, {"post": older.pk}, headers={"X-Muralium-Feed": "1"})
        self.assertTemplateUsed(response, "feed.html")
        self.assertContains(response, "Первая работа")
        self.assertContains(response, "Комментарий первой работы")
        self.assertNotContains(response, "Вторая работа")
        self.assertContains(response, reverse("profile", args=[self.owner.pk]))
        self.assertEqual(response.context["previous_post"], latest.pk)
        self.assertEqual(response.context["next_post"], latest.pk)
        self.assertEqual(self.client.get(url, {"post": pending.pk}).status_code, 404)

        response = self.client.post(reverse("comment", args=[older.pk]), {
            "source": "feed", "text": "Новый комментарий",
        })
        self.assertRedirects(response, f"{url}?post={older.pk}#projects")
        detail = self.client.get(reverse("placement", args=[older.pk]))
        self.assertContains(detail, f'href="{url}?post={older.pk}#projects"')
        self.assertContains(detail, "publication-author-name")

    def test_feed_fills_stars_and_shows_only_the_most_liked_comment(self):
        project = self.create_work("Работа", timezone.now())
        highlighted = Comment.objects.create(placement=project, author=self.owner, text="Популярный отзыв")
        newest = Comment.objects.create(placement=project, author=self.owner, text="Новый отзыв")
        rate = reverse("rate", args=[project.pk])
        like = reverse("like_comment", args=[highlighted.pk])
        feed = reverse("home")

        self.assertContains(self.client.get(feed), "☆", count=5)
        self.client.post(rate, {"score": 3})
        self.assertContains(self.client.get(feed), "★", count=3)
        self.assertContains(self.client.get(feed), "☆", count=2)
        self.assertEqual(Client().post(like, {"liked": "1"}).status_code, 302)
        self.assertFalse(CommentLike.objects.exists())
        for _ in range(2):
            self.client.post(like, {"liked": "1", "source": "feed"})
        self.assertEqual(CommentLike.objects.count(), 1)
        response = self.client.get(feed)
        self.assertContains(response, highlighted.text)
        self.assertNotContains(response, newest.text)
        details = reverse("placement", args=[project.pk])
        self.assertContains(response, f'href="{details}#comments"')
        self.assertContains(self.client.get(details), newest.text)
        self.client.post(like, {"liked": "0"})
        self.assertContains(self.client.get(feed), newest.text)

    def test_async_ratings_return_updated_fragment_without_redirect(self):
        project = self.create_work("Оцениваемая работа", timezone.now())
        url = reverse("rate", args=[project.pk])
        headers = {"X-Muralium-Async": "1"}

        response = self.client.post(url, {"score": "3", "source": "feed"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Rating.objects.get(placement=project).score, 3)
        self.assertEqual(response.json()["html"].count("★"), 3)
        self.assertIn("3,0 из 5", response.json()["html"])
        self.assertIn('aria-pressed="true"', response.json()["html"])

        response = self.client.post(url, {"score": "5"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Rating.objects.get(placement=project).score, 5)
        self.assertEqual(response.json()["html"].count("★"), 5)
        self.assertEqual(self.client.post(url, {"score": "0"}, headers=headers).status_code, 400)
        self.assertEqual(Rating.objects.get(placement=project).score, 5)

    def test_async_comments_and_likes_update_discussion_without_redirect(self):
        project = self.create_work("Обсуждаемая работа", timezone.now())
        comment_url = reverse("comment", args=[project.pk])
        headers = {"X-Muralium-Async": "1"}

        response = self.client.post(comment_url, {"text": "Без перезагрузки"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Без перезагрузки", response.json()["html"])
        self.assertEqual(Comment.objects.filter(placement=project).count(), 1)
        self.assertEqual(self.client.post(comment_url, {"text": "   "}, headers=headers).status_code, 400)

        entry = Comment.objects.get(placement=project)
        like_url = reverse("like_comment", args=[entry.pk])
        response = self.client.post(
            like_url, {"liked": "1", "source": "feed"}, headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-pressed="true"', response.json()["html"])
        self.assertIn("♥", response.json()["html"])
        self.assertEqual(CommentLike.objects.filter(comment=entry).count(), 1)

        response = self.client.post(like_url, {"liked": "0"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-pressed="false"', response.json()["html"])
        self.assertFalse(CommentLike.objects.filter(comment=entry).exists())

    def test_author_rating_weights_each_rated_public_work_equally(self):
        published_at = timezone.now()
        first = self.create_work("Первая оценённая работа", published_at)
        second = self.create_work("Вторая оценённая работа", published_at)
        self.create_work("Без оценок", published_at)
        pending = self.create_work("Скрытая работа")
        another = get_user_model().objects.create_user(username="another")
        Rating.objects.bulk_create([
            Rating(placement=first, author=self.owner, score=5),
            Rating(placement=first, author=another, score=3),
            Rating(placement=second, author=another, score=2),
            Rating(placement=pending, author=another, score=5),
        ])
        for url in (reverse("mine"), reverse("profile", args=[self.owner.pk])):
            response = self.client.get(url)
            self.assertEqual(response.context["profile_rating"], {"average": 3, "rated_works": 2})
            self.assertContains(response, "3,0 из 5")

    def create_work(self, title, published_at=None):
        response = self.client.post(reverse("create"), {**self.payload(), "title": title})
        self.assertEqual(response.status_code, 302)
        project = Placement.objects.get(title=title)
        if published_at:
            project.status = Placement.Status.APPROVED
            project.published_at = published_at
            project.save(update_fields=["status", "published_at"])
        return project

    def test_profile_avatar_and_private_wall_do_not_publish_pending_projects(self):
        self.client.post(reverse("create"), self.payload())
        project = Placement.objects.get()
        account = reverse("mine")
        public = reverse("profile", args=[self.owner.pk])
        icon = reverse("avatar", args=[self.owner.pk])
        response = self.client.post(account, {
            "nickname": "Artist Studio",
            "avatar": self.upload("avatar.png", "RGB", (65, 75, 85)),
        })
        self.assertRedirects(response, account)
        self.assertContains(self.client.get(account), project.title)
        visitor = Client()
        self.assertContains(visitor.get(public), "Artist Studio")
        self.assertNotContains(visitor.get(public), project.title)
        response = visitor.get(icon)
        self.assertEqual(response["Content-Type"], "image/png")
        with Image.open(io.BytesIO(b"".join(response.streaming_content))) as image:
            self.assertEqual(image.size, (256, 256))

        original = self.owner.profile.avatar
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(account, {
                "nickname": "Artist Studio",
                "avatar": self.upload("new-avatar.png", "RGB", (85, 75, 65)),
            })
        self.assertFalse(original.storage.exists(original.name))
