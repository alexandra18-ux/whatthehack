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

from .models import Comment, CommentLike, Placement, Rating


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
        for url in (detail, result, before):
            response = visitor.get(url)
            self.assertEqual(response.status_code, 200)
            if response.streaming:
                self.assertTrue(b"".join(response.streaming_content))
        for url in (facade, design):
            self.assertEqual(visitor.get(url).status_code, 404)
        self.assertEqual(visitor.get(reverse("map_api")).json()["projects"][0]["id"], project.pk)
        self.assertContains(visitor.get(reverse("home")), project.title)

    def test_search_matches_cyrillic_and_only_shows_published_cards(self):
        self.client.post(reverse("create"), self.payload())
        project = Placement.objects.get()
        visitor = Client()
        url = reverse("search")
        self.assertContains(visitor.get(url, {"q": "мурал фасад"}), "ничего не найдено")

        project.status = Placement.Status.APPROVED
        project.published_at = timezone.now()
        project.save(update_fields=["status", "published_at"])
        Comment.objects.create(placement=project, author=self.owner, text="Отличная работа")
        response = visitor.get(url, {"q": "мурал фасад"})
        self.assertContains(response, f'id="result-title-{project.pk}"')
        self.assertContains(response, "Отличная работа")
        self.assertNotContains(response, "data-feed-direction")
        self.assertNotContains(response, 'src="/static/js/feed.js"')
        self.assertContains(visitor.get(url, {"q": ".*"}), "ничего не найдено")

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
