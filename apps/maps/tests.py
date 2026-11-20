from django.test import TestCase
from django.urls import reverse


class MapPageTests(TestCase):
    def test_map_sends_site_origin_to_public_tile_server(self):
        response = self.client.get(reverse("map"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
