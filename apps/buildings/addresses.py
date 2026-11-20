import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from math import hypot
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

import cv2
import numpy as np
from django.conf import settings
from django.core import signing
from django.core.cache import cache

SOUTH, WEST, NORTH, EAST = map(Decimal, ("51.392", "45.805", "51.686", "46.210"))
CITY_FILTER = {
    "latitude__range": (SOUTH, NORTH),
    "longitude__range": (WEST, EAST),
}
BOUNDARY_FILE = Path(__file__).with_name("data") / "saratov-boundary.json"
ADDRESS_SALT = "muralium-saratov-address"


class AddressSearchUnavailable(Exception):
    pass


@lru_cache(maxsize=1)
def city_boundary():
    return json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))


def city_point(latitude, longitude):
    return (float(longitude) - 46) * 1000000, (float(latitude) - 51) * 1000000


@lru_cache(maxsize=1)
def city_contours():
    return [
        np.array([city_point(lat, lon) for lat, lon in ring], dtype=np.float32)
        for ring in city_boundary()
    ]


def in_city(latitude, longitude):
    return (
        SOUTH <= latitude <= NORTH and WEST <= longitude <= EAST
        and any(cv2.pointPolygonTest(contour, city_point(latitude, longitude), False) >= 0
                for contour in city_contours())
    )


@dataclass(frozen=True)
class SaratovAddress:
    ref: str
    street: str
    number: str
    latitude: Decimal
    longitude: Decimal

    @property
    def label(self):
        return f"{self.street}, {self.number}"

    @property
    def ticket(self):
        return signing.dumps(
            [self.ref, self.street, self.number, str(self.latitude), str(self.longitude)],
            salt=ADDRESS_SALT,
        )


def from_feature(feature):
    properties = feature.get("properties", {})
    if not isinstance(properties, dict):
        return None
    street = properties.get("street") or properties.get("locality")
    number = properties.get("housenumber")
    osm_type = properties.get("osm_type")
    osm_id = properties.get("osm_id")
    geometry = feature.get("geometry") or {}
    if (
        not isinstance(street, str) or not isinstance(number, str) or
        not street or not number or len(street) + len(number) > 218 or
        osm_type not in {"N", "W", "R"} or type(osm_id) is not int or osm_id <= 0 or
        not isinstance(geometry, dict) or geometry.get("type") != "Point"
    ):
        return None

    try:
        lon, lat = geometry["coordinates"]
        latitude = Decimal(str(lat)).quantize(Decimal("0.000001"))
        longitude = Decimal(str(lon)).quantize(Decimal("0.000001"))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if latitude.is_finite() and longitude.is_finite() and in_city(latitude, longitude):
        return SaratovAddress(f"{osm_type.lower()}{osm_id}", street, number, latitude, longitude)
    return None


def find_addresses(query):
    normalized = " ".join(query.split())
    return geocode(settings.GEOCODER_URL, {
        "q": normalized if "саратов" in normalized.casefold() else f"Саратов, {normalized}",
        "layer": "house",
        "limit": 12,
        "bbox": f"{WEST},{SOUTH},{EAST},{NORTH}",
    })[:8]


def address_at(latitude, longitude):
    reverse_url = urljoin(settings.GEOCODER_URL.rstrip("/") + "/", "../reverse/")
    matches = geocode(reverse_url, {
        "lat": f"{latitude:.5f}", "lon": f"{longitude:.5f}", "layer": "house", "limit": 10,
    })

    def distance(address):
        return hypot(
            float(address.latitude - latitude) * 111_200,
            float(address.longitude - longitude) * 69_300,
        )

    nearest = min(matches, key=distance, default=None)
    return nearest if nearest and distance(nearest) <= 150 else None


def geocode(url, params):
    query = urlencode(params)
    digest = sha256(f"{url}?{query}".casefold().encode()).hexdigest()
    key = f"saratov-address:{digest}"
    matches = cache.get(key)
    if matches is not None:
        return matches
    if not cache.add("saratov-geocoding-request", True, timeout=1):
        raise AddressSearchUnavailable

    request = Request(f"{url}?{query}", headers={
        "User-Agent": "Muralium/1.0 (Saratov address search)",
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=4) as response:
            payload = json.loads(response.read(256_000))
        features = payload["features"]
        if not isinstance(features, list):
            raise ValueError("Invalid Photon feature list")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise AddressSearchUnavailable from error

    matches = {}
    for feature in features:
        if isinstance(feature, dict) and (address := from_feature(feature)):
            matches.setdefault(address.label.casefold(), address)
    results = list(matches.values())
    cache.set(key, results, timeout=86400 if results else 3600)
    return results


def get_address(ticket):
    try:
        ref, street, number, latitude, longitude = signing.loads(
            ticket, salt=ADDRESS_SALT, max_age=86400,
        )
    except signing.BadSignature:
        return None
    return SaratovAddress(ref, street, number, Decimal(latitude), Decimal(longitude))
