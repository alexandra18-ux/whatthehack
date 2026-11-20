import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .addresses import AddressSearchUnavailable, CITY_FILTER, address_at, get_address, in_city
from .models import Building, Panorama
from .panoramas import default_panorama_camera, nearby_panoramas, panorama_frame, parse_camera


def street_walk_url(latitude, longitude):
    point = f"{longitude},{latitude}"
    yandex_query = urlencode({
        "l": "stv,sta",
        "ll": point,
        "panorama[point]": point,
        "panorama[full]": "true",
        "z": 17,
    })
    return f"https://yandex.ru/maps/194/saratov/?{yandex_query}"


def building_data(building):
    return {
        "id": building.pk,
        "address": building.address,
        "latitude": float(building.latitude),
        "longitude": float(building.longitude),
        "url": reverse("building", args=[building.pk]),
        "street_walk_url": street_walk_url(building.latitude, building.longitude),
        "panorama_url": (
            reverse("building_panorama", args=[building.pk])
            if building.panorama_available else ""
        ),
    }


def city_buildings():
    return [
        item for item in Building.objects.filter(**CITY_FILTER).annotate(
            panorama_available=Exists(Panorama.objects.filter(building_id=OuterRef("pk"), is_public=True)),
        )
        if in_city(item.latitude, item.longitude)
    ]


def buildings_api(request):
    return JsonResponse({"buildings": [
        building_data(item) for item in city_buildings()
    ]})


@require_GET
def map_address(request):
    try:
        latitude = Decimal(request.GET.get("lat", ""))
        longitude = Decimal(request.GET.get("lon", ""))
    except InvalidOperation:
        return JsonResponse({"error": "Укажите точку на карте."}, status=400)
    if not (latitude.is_finite() and longitude.is_finite() and in_city(latitude, longitude)):
        return JsonResponse({"error": "Выберите точку в границах Саратова."}, status=400)
    try:
        address = address_at(latitude, longitude)
    except AddressSearchUnavailable:
        return JsonResponse({"error": "Поиск адреса временно недоступен. Попробуйте ещё раз."}, status=503)
    if address is None:
        return JsonResponse({"error": "Адрес рядом с точкой не найден. Нажмите на здание."}, status=404)
    return JsonResponse({
        "address": address.label,
        "ticket": address.ticket,
        "street_walk_url": street_walk_url(address.latitude, address.longitude),
    })


def catalog(request, pk, kind):
    building = get_object_or_404(Building, pk=pk)
    entries = building.facades if kind == "facade" else building.designs
    return JsonResponse({"items": [
        {"id": item.pk, "label": str(item), "url": reverse("asset", args=[kind, item.pk])}
        for item in entries.filter(is_public=True).order_by("pk")
    ]})


def detail(request, pk):
    from apps.placements.models import published_placements

    building = get_object_or_404(Building, pk=pk)
    return render(request, "building.html", {
        "building": building,
        "facades": building.facades.filter(is_public=True),
        "has_panoramas": nearby_panoramas(building).exists(),
        "street_walk_url": street_walk_url(building.latitude, building.longitude),
        "yandex_panorama_key": settings.YANDEX_MAPS_API_KEY,
        "projects": published_placements().filter(building=building),
    })


@require_GET
def building_panorama(request, pk):
    building = get_object_or_404(Building, pk=pk)
    panoramas = nearby_panoramas(building)
    panorama = panoramas.filter(building=building).first() or panoramas.first()
    if panorama is None:
        return redirect("building", pk=pk)
    try:
        camera, span = default_panorama_camera(panorama)
    except (ValidationError, OSError, ValueError):
        camera, span = None, None
    serialized = json.dumps(camera, separators=(",", ":"))
    return render(request, "panorama_page.html", {
        "building": building,
        "panorama": panorama,
        "camera": camera,
        "span": span,
        "frame_url": f"{reverse('panorama_view', args=[panorama.pk])}?{urlencode({'camera': serialized, 'small': 1})}",
        "editor_url": f"{reverse('create')}?{urlencode({'building': pk, 'panorama_source': panorama.pk, 'camera': serialized})}",
        "street_walk_url": street_walk_url(building.latitude, building.longitude),
        "yandex_panorama_key": settings.YANDEX_MAPS_API_KEY,
    })


@require_GET
def panorama_image(request, pk):
    panorama = get_object_or_404(Panorama, pk=pk, is_public=True)
    try:
        return FileResponse(panorama.image.open("rb"))
    except OSError as error:
        raise Http404 from error


@require_GET
def panorama_view(request, pk):
    from apps.placements.services.perspective import encode_image

    panorama = get_object_or_404(Panorama, pk=pk, is_public=True)
    try:
        camera = parse_camera(request.GET.get("camera", ""))
        size = (960, 600) if request.GET.get("small") == "1" else (1440, 900)
        frame = panorama_frame(panorama, camera, size=size)
    except (ValidationError, OSError, ValueError):
        return JsonResponse({"error": "Не удалось подготовить вид на стену."}, status=400)
    return HttpResponse(encode_image(frame).read(), content_type="image/jpeg")


@login_required
@require_http_methods(["GET", "POST"])
def add_building(request):
    if request.method == "GET":
        return redirect(f"{reverse('map')}#address-search")
    address = get_address(request.POST.get("address_ticket", ""))
    if address is None:
        raise Http404("Результат поиска устарел. Найдите адрес снова.")
    building, _ = Building.objects.get_or_create(
        osm_ref=address.ref,
        defaults={"address": address.label, "latitude": address.latitude, "longitude": address.longitude},
    )
    return redirect(f"{reverse('create')}?building={building.pk}")
