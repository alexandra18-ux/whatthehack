from django import forms
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.buildings.addresses import AddressSearchUnavailable, find_addresses
from apps.buildings.views import city_buildings

REGION_MAP_BOUNDS = [[49.75, 42.45], [52.9, 50.9]]


class AddressSearchForm(forms.Form):
    address = forms.CharField(
        label="Улица и номер дома", max_length=160,
        widget=forms.TextInput(attrs={"placeholder": "поиск на карте"}),
    )


@never_cache
def maps(request):
    form = AddressSearchForm(request.GET if "address" in request.GET else None)
    matches = None
    if form.is_valid():
        try:
            matches = find_addresses(form.cleaned_data["address"])
        except AddressSearchUnavailable:
            form.add_error("address", "Поиск временно недоступен. Повторите запрос чуть позже.")
    response = render(request, "map.html", {
        "buildings": city_buildings(),
        "region_map_bounds": REGION_MAP_BOUNDS,
        "map_tile_url": settings.MAP_TILE_URL,
        "selected_building": request.GET.get("building", ""),
        "address_form": form,
        "matches": matches,
    })
    # The tile service needs the app origin, while the page path can stay private.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
