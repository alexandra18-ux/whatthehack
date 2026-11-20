import json
import math
from decimal import Decimal

import cv2
import numpy as np
from django.core.exceptions import ValidationError
from django.db.models import Q
from PIL import Image

from .models import Panorama


def nearby_panoramas(building):
    latitude = Decimal("0.0018")
    longitude = Decimal("0.0029")
    return Panorama.objects.filter(is_public=True).filter(
        Q(building=building) | Q(
            building__latitude__range=(building.latitude - latitude, building.latitude + latitude),
            building__longitude__range=(building.longitude - longitude, building.longitude + longitude),
        )
    ).order_by("title", "pk")


def parse_camera(value):
    try:
        yaw, pitch, fov = json.loads(value)
        if not all(type(number) in (int, float) and math.isfinite(number) for number in (yaw, pitch, fov)):
            raise ValueError
        if -180 <= yaw <= 180 and -89 <= pitch <= 89 and 8 <= fov <= 80:
            return yaw, pitch, fov
    except (TypeError, ValueError, OverflowError, RecursionError):
        pass
    raise ValidationError("Выберите ракурс в панораме заново.")


def validate_panorama_size(width, height):
    if width * height > 36_000_000 or width < 800 or not .05 <= height / width <= .51:
        raise ValidationError("Нужна круговая панорама JPEG или PNG шириной от 800 пикселей и до 36 млн пикселей.")


def default_panorama_camera(panorama):
    with panorama.image.open("rb") as source, Image.open(source, formats=["JPEG", "PNG"]) as image:
        validate_panorama_size(*image.size)
        span = min(360 * image.height / image.width, 180)
    yaw = (panorama.initial_heading + 180) % 360 - 180
    return [yaw, 0, min(45, span * .84)], span


def panorama_frame(panorama, camera, *, size=(1440, 900)):
    with panorama.image.open("rb") as source, Image.open(source, formats=["JPEG", "PNG"]) as image:
        validate_panorama_size(*image.size)
        source_pixels = np.asarray(image.convert("RGB"))
    yaw, pitch, fov = map(math.radians, camera)
    width, height = size
    scale = math.tan(fov / 2)
    x = (np.arange(width, dtype=np.float32) + .5 - width / 2) * (2 * scale / height)
    y = (height / 2 - np.arange(height, dtype=np.float32) - .5)[:, None] * (2 * scale / height)
    vertical = y * math.cos(pitch) + math.sin(pitch)
    forward = math.cos(pitch) - y * math.sin(pitch)
    longitude = np.arctan2(x, forward) + yaw
    latitude = np.arctan2(vertical, np.hypot(x, forward))
    source_height, source_width = source_pixels.shape[:2]
    span = min(math.tau * source_height / source_width, math.pi)
    u = ((longitude / math.tau + .5) % 1) * source_width - .5
    v = np.clip((.5 - latitude / span) * source_height - .5, 0, source_height - 1)
    frame = cv2.remap(source_pixels, u.astype(np.float32), v.astype(np.float32), cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_WRAP)
    frame[(latitude < -span / 2) | (latitude > span / 2)] = (26, 31, 25)
    return Image.fromarray(frame)
