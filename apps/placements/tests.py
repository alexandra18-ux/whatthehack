import io
import json
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.buildings.models import Building

from .models import Comment, Placement, Rating


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
        payload["corners"] = json.dumps([self.corners[index] for index in (0, 2, 1, 3)])
        payload["mural_file"] = SimpleUploadedFile("broken.png", b"invalid")
        response = self.client.post(reverse("preview"), payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("corners", response.json()["errors"])
        self.assertIn("mural_file", response.json()["errors"])

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
        for url in (detail, result, before):
            response = visitor.get(url)
            self.assertEqual(response.status_code, 200)
            if response.streaming:
                self.assertTrue(b"".join(response.streaming_content))
        for url in (facade, design):
            self.assertEqual(visitor.get(url).status_code, 404)
        self.assertEqual(visitor.get(reverse("map_api")).json()["projects"][0]["id"], project.pk)
        self.assertContains(visitor.get(reverse("home")), project.title)

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
