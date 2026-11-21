import io
import json
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.buildings.addresses import find_addresses
from apps.buildings.models import Building, FacadePhoto, Panorama
from apps.murals.models import MuralDesign
from apps.placements.models import Placement


class MapPageTests(TestCase):
    @override_settings(YANDEX_MAPS_API_KEY="test-browser-key")
    def test_panorama_navigation_is_external_even_when_a_key_is_configured(self):
        building = Building.objects.create(address="Московская улица, 55", latitude=51.532716, longitude=46.039064)
        Panorama.objects.create(building=building, title="Архивная панорама", is_public=True)
        for url in (reverse("map"), reverse("building", args=[building.pk])):
            page = self.client.get(url)
            self.assertContains(page, 'target="_blank" rel="noopener noreferrer">Открыть в Яндекс Картах')
            self.assertNotContains(page, 'id="street-walk-dialog"')
            self.assertNotContains(page, "street_walk.js")
            self.assertNotContains(page, "test-browser-key")
            self.assertNotContains(page, "Панорама 360°")

        old_link = self.client.get(reverse("building_panorama", args=[building.pk]))
        self.assertEqual(old_link.status_code, 302)
        destination = urlparse(old_link["Location"])
        self.assertEqual(destination.netloc, "yandex.ru")
        self.assertEqual(parse_qs(destination.query)["panorama[point]"], ["46.039064,51.532716"])

    def test_map_sends_site_origin_to_public_tile_server(self):
        response = self.client.get(reverse("map"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotContains(response, 'id="map-address-action"')
        self.assertContains(response, 'id="map-address-login"')

    @patch("apps.buildings.addresses.urlopen")
    def test_search_distinguishes_settlements_and_creates_the_confirmed_address(self, urlopen):
        cache.clear()
        self.addCleanup(cache.clear)

        def feature(osm_id, latitude, longitude, city):
            return {
                "properties": {
                    "osm_type": "W", "osm_id": osm_id, "street": "Московская улица",
                    "housenumber": "55", "city": city,
                },
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            }

        urlopen.return_value = io.BytesIO(json.dumps({
            "features": [
                feature(138564607, 51.4949444, 46.1344316, "Энгельс"),
                feature(100909666, 51.5327164, 46.0390643, "Саратов"),
                feature(123, 55.7558, 37.6176, "Москва"),
            ],
        }).encode())
        request = {"address": "Энгельс, Московская, 55"}
        response = self.client.get(reverse("map"), request)
        self.assertContains(response, "Энгельс, Московская улица, 55")
        self.assertContains(response, "Саратов, Московская улица, 55")
        self.assertContains(response, "panorama%5Bpoint%5D=46.039064%2C51.532716")
        self.assertEqual([match.ref for match in response.context["matches"]], ["w138564607", "w100909666"])
        match, _ = find_addresses(request["address"])
        self.assertEqual(urlopen.call_count, 1)
        requested = urlparse(urlopen.call_args.args[0].full_url)
        self.assertEqual(parse_qs(requested.query)["q"], [request["address"]])

        self.client.force_login(get_user_model().objects.create_user(username="artist"))
        add = reverse("building_add")
        self.assertEqual(self.client.post(add, {"address_ticket": "invalid"}).status_code, 404)
        self.client.post(add, {"address_ticket": match.ticket})
        self.client.post(add, {"address_ticket": match.ticket})
        building = Building.objects.get()
        self.assertEqual(building.osm_ref, "w138564607")
        self.assertEqual(building.address, "Энгельс, Московская улица, 55")
        self.assertEqual(self.client.get(reverse("buildings_api")).json()["buildings"][0]["id"], building.pk)

    @override_settings(GEOCODER_URL="https://example.org/photon/api/")
    @patch("apps.buildings.addresses.urlopen")
    def test_map_click_resolves_a_nearby_address_for_creation(self, urlopen):
        cache.clear()
        self.addCleanup(cache.clear)
        urlopen.return_value = io.BytesIO(json.dumps({
            "features": [{
                "properties": {
                    "osm_type": "W", "osm_id": 138564607, "street": "Московская улица",
                    "housenumber": "55", "city": "Энгельс",
                },
                "geometry": {"type": "Point", "coordinates": [46.1344316, 51.4949444]},
            }],
        }).encode())
        url = reverse("map_address")
        self.assertEqual(self.client.get(url, {"lat": "nan", "lon": "46"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"lat": "55.75", "lon": "37.61"}).status_code, 400)
        urlopen.assert_not_called()

        point = {"lat": "51.49494", "lon": "46.13443"}
        response = self.client.get(url, point)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_authenticated"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.json()["address"], "Энгельс, Московская улица, 55")
        destination = urlparse(response.json()["street_walk_url"])
        self.assertEqual(destination.netloc, "yandex.ru")
        self.assertEqual(parse_qs(destination.query)["panorama[point]"], ["46.134432,51.494944"])
        requested = urlparse(urlopen.call_args.args[0].full_url)
        self.assertEqual(requested.path, "/photon/reverse/")
        self.assertEqual(parse_qs(requested.query)["layer"], ["house"])

        author = get_user_model().objects.create_user(username="map-artist")
        self.client.force_login(author)
        self.assertContains(self.client.get(reverse("map")), 'id="map-address-action"')
        authenticated = self.client.get(url, point)
        self.assertTrue(authenticated.json()["is_authenticated"])
        created = self.client.post(reverse("building_add"), {"address_ticket": response.json()["ticket"]})
        building = Building.objects.get(osm_ref="w138564607")
        self.assertRedirects(created, f"{reverse('create')}?building={building.pk}")
        self.assertContains(self.client.get(reverse("map")), building.address)

        project = Placement.objects.create(
            author=author, building=building, title="Мурал в Энгельсе", corners=[],
            facade_photo=FacadePhoto.objects.create(building=building, uploaded_by=author),
            mural_design=MuralDesign.objects.create(title="Эскиз", author=author),
            status=Placement.Status.APPROVED, published_at=timezone.now(),
        )
        markers = self.client.get(reverse("map_api")).json()["projects"]
        self.assertEqual([marker["id"] for marker in markers], [project.pk])
