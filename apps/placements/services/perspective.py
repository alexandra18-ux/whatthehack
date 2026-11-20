import io
import math
from uuid import uuid4

import cv2
import numpy as np
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
WORK_SIZE = (1600, 1600)


def read_image(source, *, transparent=False):
    message = "Загрузите исправное изображение JPEG или PNG размером до 10 МБ."
    if source.size > MAX_BYTES:
        raise ValidationError(message)
    try:
        with Image.open(source, formats=["JPEG", "PNG"]) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValidationError("Изображение должно содержать не более 20 млн пикселей.")
            if min(original.size) < 2:
                raise ValidationError("Размер изображения должен быть не меньше 2 × 2 пикселей.")
            image = ImageOps.exif_transpose(original).convert("RGBA" if transparent else "RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError(message) from error

    image.thumbnail(WORK_SIZE, Image.Resampling.LANCZOS)
    if min(image.size) < 2:
        raise ValidationError("Изображение слишком узкое для обработки.")
    image.info.clear()
    return image


def validate_corners(corners):
    message = "Укажите четыре угла по часовой стрелке, начиная с верхнего левого."
    if not isinstance(corners, list) or len(corners) != 4:
        raise ValidationError(message)

    for corner in corners:
        if not isinstance(corner, dict):
            raise ValidationError(message)
        for key in ("x", "y"):
            value = corner.get(key)
            if type(value) not in (float, int) or not 0 <= value <= 1 or not math.isfinite(value):
                raise ValidationError("Координаты углов должны быть числами от 0 до 1.")

    points = np.array([[corner["x"], corner["y"]] for corner in corners], dtype=np.float64)
    edges = np.roll(points, -1, axis=0) - points
    next_edges = np.roll(edges, -1, axis=0)
    turns = edges[:, 0] * next_edges[:, 1] - edges[:, 1] * next_edges[:, 0]
    if (turns <= 1e-5).any() or turns.sum() < 0.004:
        raise ValidationError("Область стены должна быть выпуклой и достаточно большой.")
    return points


def render_placement(facade, mural, corners):
    width, height = facade.size
    mural_width, mural_height = mural.size
    destination = validate_corners(corners) * [width - 1, height - 1]
    source = [[0, 0], [mural_width - 1, 0],
              [mural_width - 1, mural_height - 1], [0, mural_height - 1]]

    try:
        matrix = cv2.getPerspectiveTransform(
            np.asarray(source, dtype=np.float32), destination.astype(np.float32),
        )
        # Premultiply before interpolation to avoid dark edges on transparent PNGs.
        overlay = np.asarray(mural, dtype=np.float32) / 255
        overlay[:, :, :3] *= overlay[:, :, 3:4]
        warped = cv2.warpPerspective(overlay, matrix, (width, height))
    except cv2.error as error:
        raise ValidationError("Не удалось построить перспективу. Измените положение углов.") from error

    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.rint(destination).astype(np.int32), 1)
    warped *= mask[:, :, None]
    base = np.asarray(facade, dtype=np.float32)
    result = base * (1 - warped[:, :, 3:4]) + warped[:, :, :3] * 255
    return Image.fromarray(np.clip(np.rint(result), 0, 255).astype(np.uint8))


def encode_image(image, *, png=False):
    buffer = io.BytesIO()
    if png:
        image.save(buffer, format="PNG")
    else:
        image.save(buffer, format="JPEG", quality=92)
    return ContentFile(buffer.getvalue(), name=f"{uuid4().hex}.{'png' if png else 'jpg'}")
