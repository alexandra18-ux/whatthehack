from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.buildings import views as buildings
from apps.maps.views import maps
from apps.placements import comment_moderation, moderation
from apps.placements import views as placements
from apps.users import views as users

urlpatterns = [
    path("", placements.home, name="home"),
    path("admin/", admin.site.urls),
    path("moderation/", moderation.queue, name="moderation_queue"),
    path("moderation/history/", moderation.history, name="moderation_history"),
    path("moderation/comments/", comment_moderation.comment_list, name="moderation_comments"),
    path("moderation/comments/<int:pk>/delete/", comment_moderation.delete_comment, name="moderation_delete_comment"),
    path("moderation/accounts/", comment_moderation.account_list, name="moderation_accounts"),
    path("moderation/accounts/<int:pk>/", comment_moderation.restrict_account, name="moderation_restrict_account"),
    path("moderation/<int:pk>/", moderation.review, name="moderation_review"),
    path("accounts/register/", users.register, name="register"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("maps/", maps, name="map"),
    path("buildings/new/", buildings.add_building, name="building_add"),
    path("buildings/<int:pk>/", buildings.detail, name="building"),
    path("placements/create/", placements.create, name="create"),
    path("placements/my/", users.account, name="mine"),
    path("people/<int:pk>/", users.public_profile, name="profile"),
    path("people/<int:pk>/avatar/", users.avatar, name="avatar"),
    path("placements/<int:pk>/", placements.detail, name="placement"),
    path("placements/<int:pk>/revise/", placements.revise, name="revise"),
    path("placements/<int:revision_pk>/revise/preview/", placements.preview, name="revision_preview"),
    path("placements/<int:pk>/rating/", placements.rate, name="rate"),
    path("placements/<int:pk>/comments/", placements.comment, name="comment"),
    path("placements/<int:pk>/image/<str:kind>/", placements.project_image, name="project_image"),
    path("images/<str:kind>/<int:pk>/", placements.asset, name="asset"),
    path("api/buildings/", buildings.buildings_api, name="buildings_api"),
    path("api/buildings/<int:pk>/facades/", buildings.catalog, {"kind": "facade"}, name="facades_api"),
    path("api/buildings/<int:pk>/designs/", buildings.catalog, {"kind": "design"}, name="designs_api"),
    path("api/placements/map/", placements.map_api, name="map_api"),
    path("api/placements/preview/", placements.preview, name="preview"),
]
