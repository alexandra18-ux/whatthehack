import io
import json
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from apps.buildings.models import Building

from .models import Placement


class PlacementWorkflowTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.enterContext(self.settings(MEDIA_ROOT=media.name))
        self.building = Building.objects.create(address="Тестовый фасад", latitude=51, longitude=46)
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
        self.assertEqual(self.client.get(result).status_code, 200)
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
            self.assertEqual(visitor.get(url).status_code, 200)
        for url in (facade, design):
            self.assertEqual(visitor.get(url).status_code, 404)
        self.assertEqual(visitor.get(reverse("map_api")).json()["projects"][0]["id"], project.pk)
        self.assertContains(visitor.get(reverse("home")), project.title)
