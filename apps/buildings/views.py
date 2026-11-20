from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .addresses import CITY_FILTER, get_address, in_city
from .models import Building


def building_data(building):
    return {
        "id": building.pk,
        "address": building.address,
        "latitude": float(building.latitude),
        "longitude": float(building.longitude),
        "url": reverse("building", args=[building.pk]),
    }


def city_buildings():
    return [
        item for item in Building.objects.filter(**CITY_FILTER)
        if in_city(item.latitude, item.longitude)
    ]


def buildings_api(request):
    return JsonResponse({"buildings": [
        building_data(item) for item in city_buildings()
    ]})


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
        "projects": published_placements().filter(building=building),
    })


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
