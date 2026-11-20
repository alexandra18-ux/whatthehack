from django import forms
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Building


class BuildingForm(forms.ModelForm):
    class Meta:
        model = Building
        fields = ["address", "latitude", "longitude"]


def building_data(building):
    return {
        "id": building.pk,
        "address": building.address,
        "latitude": float(building.latitude),
        "longitude": float(building.longitude),
        "url": reverse("building", args=[building.pk]),
    }


def buildings_api(request):
    return JsonResponse({"buildings": [building_data(item) for item in Building.objects.all()]})


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
    form = BuildingForm(
        request.POST if request.method == "POST" else None,
        initial={key: request.GET.get(key) for key in ("latitude", "longitude")},
    )
    if form.is_valid():
        return redirect(f"{reverse('create')}?building={form.save().pk}")
    return render(request, "building_form.html", {"form": form})
