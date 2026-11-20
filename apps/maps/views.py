from django.conf import settings
from django.shortcuts import render

from apps.buildings.models import Building


def maps(request):
    return render(request, "map.html", {
        "buildings": Building.objects.all(),
        "maps_key": settings.YANDEX_MAPS_API_KEY,
        "selected_building": request.GET.get("building", ""),
    })
