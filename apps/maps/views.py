from django import forms
from django.conf import settings
from django.shortcuts import render

from apps.buildings.addresses import AddressSearchUnavailable, CITY_BOUNDS, city_boundary, find_addresses
from apps.buildings.views import city_buildings


class AddressSearchForm(forms.Form):
    address = forms.CharField(
        label="Улица и номер дома", max_length=160,
        widget=forms.TextInput(attrs={"placeholder": "Например, Московская, 55"}),
    )


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
        "city_bounds": CITY_BOUNDS,
        "city_boundary": city_boundary(),
        "map_tile_url": settings.MAP_TILE_URL,
        "selected_building": request.GET.get("building", ""),
        "address_form": form,
        "matches": matches,
        "yandex_panorama_key": settings.YANDEX_MAPS_API_KEY,
    })
    # The tile service needs the app origin, while the page path can stay private.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
