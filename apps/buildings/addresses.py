import json
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from math import hypot
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from django.conf import settings
from django.core import signing
from django.core.cache import cache

SOUTH, WEST, NORTH, EAST = map(Decimal, ("49.75", "42.45", "52.9", "50.9"))
REGION_MAP_BOUNDS = [[float(SOUTH), float(WEST)], [float(NORTH), float(EAST)]]
REGION_FILTER = {
    "latitude__range": (SOUTH, NORTH),
    "longitude__range": (WEST, EAST),
}
ADDRESS_SALT = "muralium-saratov-address"


class AddressSearchUnavailable(Exception):
    pass


def in_map_region(latitude, longitude):
    return (
        latitude.is_finite() and longitude.is_finite()
        and SOUTH <= latitude <= NORTH and WEST <= longitude <= EAST
    )


def street_walk_url(latitude, longitude):
    point = f"{longitude},{latitude}"
    query = urlencode({
        "l": "stv,sta",
        "ll": point,
        "panorama[point]": point,
        "panorama[full]": "true",
        "z": 17,
    })
    return f"https://yandex.ru/maps/?{query}"


@dataclass(frozen=True)
class Address:
    ref: str
    street: str
    number: str
    latitude: Decimal
    longitude: Decimal
    settlement: str = ""

    @property
    def label(self):
        return ", ".join(filter(None, (self.settlement, self.street, self.number)))

    @property
    def street_walk_url(self):
        return street_walk_url(self.latitude, self.longitude)

    @property
    def ticket(self):
        return signing.dumps(
            [self.ref, self.street, self.number, str(self.latitude), str(self.longitude), self.settlement],
            salt=ADDRESS_SALT,
        )


def from_feature(feature):
    properties = feature.get("properties", {})
    if not isinstance(properties, dict):
        return None
    street = properties.get("street") or properties.get("locality") or properties.get("city")
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
    if in_map_region(latitude, longitude):
        settlement = properties.get("city")
        if (
            not isinstance(settlement, str) or settlement.casefold() == street.casefold()
            or len(settlement) + len(street) + len(number) + 4 > 220
        ):
            settlement = ""
        return Address(f"{osm_type.lower()}{osm_id}", street, number, latitude, longitude, settlement)
    return None


def find_addresses(query):
    normalized = " ".join(query.split())
    return geocode(settings.GEOCODER_URL, {
        "q": normalized,
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
    key = f"regional-address:{digest}"
    matches = cache.get(key)
    if matches is not None:
        return matches
    if not cache.add("regional-geocoding-request", True, timeout=1):
        raise AddressSearchUnavailable

    request = Request(f"{url}?{query}", headers={
        "User-Agent": "Murrralium/1.0 (Regional address search)",
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
            matches.setdefault(address.ref, address)
    results = list(matches.values())
    cache.set(key, results, timeout=86400 if results else 3600)
    return results


def get_address(ticket):
    try:
        ref, street, number, latitude, longitude, *settlement = signing.loads(
            ticket, salt=ADDRESS_SALT, max_age=86400,
        )
    except signing.BadSignature:
        return None
    return Address(ref, street, number, Decimal(latitude), Decimal(longitude), *settlement)
