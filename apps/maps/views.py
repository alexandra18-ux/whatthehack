from django.conf import settings
from django.shortcuts import render

from apps.buildings.models import Building


def maps(request):
    response = render(request, "map.html", {
        "buildings": Building.objects.all(),
        "map_tile_url": settings.MAP_TILE_URL,
        "selected_building": request.GET.get("building", ""),
    })
    # The tile service needs the app origin, while the page path can stay private.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
