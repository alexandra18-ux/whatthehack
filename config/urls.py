from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.buildings import views as buildings
from apps.maps.views import maps
from apps.placements import views as placements
from apps.users.views import register

urlpatterns = [
    path("", placements.home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/register/", register, name="register"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("maps/", maps, name="map"),
    path("buildings/new/", buildings.add_building, name="building_add"),
    path("buildings/<int:pk>/", buildings.detail, name="building"),
    path("placements/create/", placements.create, name="create"),
    path("placements/my/", placements.mine, name="mine"),
    path("placements/<int:pk>/", placements.detail, name="placement"),
    path("placements/<int:pk>/image/<str:kind>/", placements.project_image, name="project_image"),
    path("images/<str:kind>/<int:pk>/", placements.asset, name="asset"),
    path("api/buildings/", buildings.buildings_api, name="buildings_api"),
    path("api/buildings/<int:pk>/facades/", buildings.catalog, {"kind": "facade"}, name="facades_api"),
    path("api/buildings/<int:pk>/designs/", buildings.catalog, {"kind": "design"}, name="designs_api"),
    path("api/placements/map/", placements.map_api, name="map_api"),
    path("api/placements/preview/", placements.preview, name="preview"),
]
