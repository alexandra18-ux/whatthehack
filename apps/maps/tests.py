import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.buildings.addresses import find_addresses
from apps.buildings.models import Building


class MapPageTests(TestCase):
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
