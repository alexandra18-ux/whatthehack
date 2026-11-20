import io
import json
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.buildings.addresses import find_addresses
from apps.buildings.models import Building


class MapPageTests(TestCase):
    def test_panorama_dialog_is_available_only_with_configured_key(self):
        url = reverse("map")
        with self.settings(YANDEX_MAPS_API_KEY=""):
            self.assertNotContains(self.client.get(url), 'id="street-walk-dialog"')
        with self.settings(YANDEX_MAPS_API_KEY="test-browser-key"):
            response = self.client.get(url)
            self.assertContains(response, 'id="street-walk-dialog"')
            self.assertContains(response, 'data-api-key="test-browser-key"')
            self.assertNotContains(response, "api-maps.yandex.ru")
            building = Building.objects.create(address="Московская улица, 55", latitude=51.532716, longitude=46.039064)
            detail = self.client.get(reverse("building", args=[building.pk]))
            self.assertEqual(detail.headers["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_map_sends_site_origin_to_public_tile_server(self):
        response = self.client.get(reverse("map"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")

    @patch("apps.buildings.addresses.urlopen")
    def test_search_filters_engels_and_creates_only_the_confirmed_saratov_address(self, urlopen):
        cache.clear()
        self.addCleanup(cache.clear)

        def feature(osm_id, latitude, longitude):
            return {
                "properties": {"osm_type": "W", "osm_id": osm_id, "street": "Московская улица", "housenumber": "55"},
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            }

        urlopen.return_value = io.BytesIO(json.dumps({
            "features": [
                feature(138564607, 51.4949444, 46.1344316),  # Engels
                feature(100909666, 51.5327164, 46.0390643),  # Saratov
            ],
        }).encode())
        request = {"address": "Московская, 55"}
        response = self.client.get(reverse("map"), request)
        self.assertContains(response, "Московская улица, 55")
        self.assertContains(response, 'panorama%5Bpoint%5D=46.039064%2C51.532716')
        self.assertEqual([match.ref for match in response.context["matches"]], ["w100909666"])
        match, = find_addresses(request["address"])
        self.assertEqual(urlopen.call_count, 1)

        self.client.force_login(get_user_model().objects.create_user(username="artist"))
        add = reverse("building_add")
        self.assertEqual(self.client.post(add, {"address_ticket": "invalid"}).status_code, 404)
        self.client.post(add, {"address_ticket": match.ticket})
        self.client.post(add, {"address_ticket": match.ticket})
        building = Building.objects.get()
        self.assertEqual(building.osm_ref, "w100909666")
        self.assertEqual(self.client.get(reverse("buildings_api")).json()["buildings"][0]["id"], building.pk)

    @override_settings(GEOCODER_URL="https://example.org/photon/api/")
    @patch("apps.buildings.addresses.urlopen")
    def test_map_click_resolves_a_nearby_address_for_creation(self, urlopen):
        cache.clear()
        self.addCleanup(cache.clear)
        urlopen.return_value = io.BytesIO(json.dumps({
            "features": [{
                "properties": {"osm_type": "W", "osm_id": 100909666, "street": "Московская улица", "housenumber": "55"},
                "geometry": {"type": "Point", "coordinates": [46.0390643, 51.5327164]},
            }],
        }).encode())
        url = reverse("map_address")
        self.assertEqual(self.client.get(url, {"lat": "nan", "lon": "46"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"lat": "51.4949444", "lon": "46.1344316"}).status_code, 400)
        urlopen.assert_not_called()

        response = self.client.get(url, {"lat": "51.53270", "lon": "46.03900"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["address"], "Московская улица, 55")
        street_walk = urlparse(response.json()["street_walk_url"])
        self.assertEqual((street_walk.netloc, street_walk.path), ("yandex.ru", "/maps/194/saratov/"))
        self.assertEqual(parse_qs(street_walk.query), {
            "l": ["stv,sta"], "ll": ["46.039064,51.532716"],
            "panorama[point]": ["46.039064,51.532716"], "panorama[full]": ["true"], "z": ["17"],
        })
        requested = urlparse(urlopen.call_args.args[0].full_url)
        self.assertEqual(requested.path, "/photon/reverse/")
        self.assertEqual(parse_qs(requested.query)["layer"], ["house"])

        self.client.force_login(get_user_model().objects.create_user(username="map-artist"))
        created = self.client.post(reverse("building_add"), {"address_ticket": response.json()["ticket"]})
        building = Building.objects.get(osm_ref="w100909666")
        self.assertRedirects(created, f"{reverse('create')}?building={building.pk}")
