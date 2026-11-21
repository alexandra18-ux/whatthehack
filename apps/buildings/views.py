from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .addresses import (
    REGION_FILTER, AddressSearchUnavailable, address_at, get_address, in_map_region, street_walk_url,
)
from .models import Building


def building_data(building):
    return {
        "id": building.pk,
        "address": building.address,
        "latitude": float(building.latitude),
        "longitude": float(building.longitude),
        "url": reverse("building", args=[building.pk]),
        "street_walk_url": street_walk_url(building.latitude, building.longitude),
    }


def regional_buildings():
    return Building.objects.filter(**REGION_FILTER)


def buildings_api(request):
    return JsonResponse({"buildings": [
        building_data(item) for item in regional_buildings()
    ]})


@require_GET
@never_cache
def map_address(request):
    try:
        latitude = Decimal(request.GET.get("lat", ""))
        longitude = Decimal(request.GET.get("lon", ""))
    except InvalidOperation:
        return JsonResponse({"error": "Укажите точку на карте."}, status=400)
    if not in_map_region(latitude, longitude):
        return JsonResponse({"error": "Выберите здание в пределах карты."}, status=400)
    try:
        address = address_at(latitude, longitude)
    except AddressSearchUnavailable:
        return JsonResponse({"error": "Поиск адреса временно недоступен. Попробуйте ещё раз."}, status=503)
    if address is None:
        return JsonResponse({"error": "Адрес рядом с точкой не найден. Нажмите на здание."}, status=404)
    return JsonResponse({
        "address": address.label,
        "ticket": address.ticket,
        "street_walk_url": address.street_walk_url,
        "is_authenticated": request.user.is_authenticated,
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
        "street_walk_url": street_walk_url(building.latitude, building.longitude),
        "projects": published_placements().filter(building=building),
    })


@require_GET
def building_panorama(request, pk):
    building = get_object_or_404(Building, pk=pk)
    return redirect(street_walk_url(building.latitude, building.longitude))


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
    mode = "&mode=photo" if request.POST.get("mode") == "photo" else ""
    return redirect(f"{reverse('create')}?building={building.pk}{mode}")
