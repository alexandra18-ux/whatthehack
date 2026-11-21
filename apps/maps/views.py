from django import forms
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.buildings.addresses import REGION_MAP_BOUNDS, AddressSearchUnavailable, find_addresses
from apps.buildings.views import regional_buildings


class AddressSearchForm(forms.Form):
    address = forms.CharField(
        label="Населённый пункт, улица и номер дома", max_length=160,
        widget=forms.TextInput(attrs={"placeholder": "Населённый пункт, улица, дом"}),
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
        "buildings": regional_buildings(),
        "region_map_bounds": REGION_MAP_BOUNDS,
        "map_tile_url": settings.MAP_TILE_URL,
        "selected_building": request.GET.get("building", ""),
        "address_form": form,
        "matches": matches,
        "selecting_graffiti_building": request.GET.get("mode") == "photo",
    })
    # The tile service needs the app origin, while the page path can stay private.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
