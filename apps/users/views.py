from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from apps.placements.models import ModerationDecision, Placement, author_rating, published_placements
from apps.placements.views import image_response

from .auth import can_manage_restrictions
from .forms import ProfileForm, RegistrationForm
from .models import Profile


@require_http_methods(["GET", "POST"])
def register(request):
    next_url = request.POST.get("next", "") if request.method == "POST" else request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        next_url = ""
    if request.user.is_authenticated:
        return redirect(next_url or "mine")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        login(request, form.save())
        return redirect(next_url or "map")
    return render(request, "registration/register.html", {"form": form, "next": next_url})


@login_required
@require_http_methods(["GET", "POST"])
def account(request):
    profile = Profile.objects.filter(user=request.user).first()
    submitted = request.method == "POST"
    form = ProfileForm(
        request.POST if submitted else None,
        request.FILES if submitted else None,
        initial={"nickname": profile.nickname if profile else ""},
    )
    if form.is_valid():
        save_profile(request.user, form.cleaned_data)
        messages.success(request, "Профиль обновлён.")
        return redirect("mine")

    projects = Placement.objects.filter(author=request.user).select_related("building", "author__profile")
    page = Paginator(projects, 12).get_page(request.GET.get("page"))
    notifications = ModerationDecision.objects.filter(
        placement__author=request.user,
        status__in=[Placement.Status.APPROVED, Placement.Status.REJECTED, Placement.Status.REVISION],
    ).select_related("placement")[:12]
    return render(request, "mine.html", {
        "profile_user": request.user, "profile": profile, "form": form,
        "profile_rating": author_rating(request.user), "notifications": notifications,
        "projects": page.object_list, "page": page,
    })


def save_profile(user, data):
    replacement = None
    try:
        with transaction.atomic():
            profile, _ = Profile.objects.select_for_update().get_or_create(user=user)
            storage = profile.avatar.storage
            old_name = profile.avatar.name
            profile.nickname = data["nickname"]
            if upload := data["avatar"]:
                profile.avatar.save(upload.name, upload, save=False)
                replacement = profile.avatar
            elif data["remove_avatar"]:
                profile.avatar = ""
            profile.save()
            if old_name and old_name != profile.avatar.name:
                transaction.on_commit(lambda: storage.delete(old_name), robust=True)
    except Exception:
        if replacement:
            replacement.storage.delete(replacement.name)
        raise


def public_profile(request, pk):
    author = get_object_or_404(get_user_model().objects.select_related("profile"), pk=pk, is_active=True)
    page = Paginator(published_placements().filter(author=author), 12).get_page(request.GET.get("page"))
    return render(request, "profile.html", {
        "profile_user": author, "profile": getattr(author, "profile", None),
        "profile_rating": author_rating(author),
        "may_manage_restrictions": can_manage_restrictions(request.user, author),
        "projects": page.object_list, "page": page,
    })


def avatar(request, pk):
    profile = get_object_or_404(Profile, user_id=pk, user__is_active=True)
    return image_response(profile.avatar)
