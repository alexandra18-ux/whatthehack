from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from apps.placements.models import Comment, ModerationDecision, Placement, author_rating, can_moderate, published_placements
from apps.placements.views import image_response

from .auth import can_manage_restrictions
from .forms import ProfileEmailForm, ProfileForm, RegistrationForm
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
    tab = request.GET.get("tab", "wall")
    if tab not in {"wall", "settings", "notifications", "comments", "logout"}:
        tab = "wall"
    submitted = request.method == "POST"
    if submitted:
        tab = "settings"

    context = {
        "profile_user": request.user, "profile": profile, "profile_rating": author_rating(request.user),
        "tab": tab,
    }
    if tab == "settings":
        form = ProfileForm(
            request.POST if submitted else None,
            request.FILES if submitted else None,
            initial={"nickname": profile.nickname if profile else ""},
        )
        if form.is_valid():
            save_profile(request.user, form.cleaned_data)
            messages.success(request, "Профиль обновлён.")
            return redirect("mine")
        context["form"] = form
        context["email_form"] = ProfileEmailForm(initial={"email": profile.pending_email if profile else ""})
    elif tab == "notifications":
        context["notifications"] = ModerationDecision.objects.filter(
            Q(placement__author=request.user, status__in=[
                Placement.Status.APPROVED, Placement.Status.REJECTED, Placement.Status.REVISION,
            ]) | Q(recipient=request.user, status=ModerationDecision.DELETED)
        ).select_related("placement")[:12]
    elif tab == "comments":
        comments = Comment.objects.filter(
            placement__in=published_placements().filter(author=request.user),
        ).exclude(author=request.user).select_related("placement", "author__profile")
        context["page"] = Paginator(comments, 12).get_page(request.GET.get("page"))
    elif tab == "wall":
        projects = Placement.objects.filter(author=request.user).select_related("building", "author__profile", "facade_photo__panorama")
        page = Paginator(projects, 12).get_page(request.GET.get("page"))
        context.update(projects=page.object_list, page=page)
    return render(request, "mine.html", context)


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
            profile.save()
            if old_name and old_name != profile.avatar.name:
                transaction.on_commit(lambda: storage.delete(old_name), robust=True)
    except Exception:
        if replacement:
            replacement.storage.delete(replacement.name)
        raise


def public_profile(request, pk):
    may_delete_other_works = can_moderate(request.user)
    authors = get_user_model().objects.select_related("profile")
    if not may_delete_other_works:
        authors = authors.filter(is_active=True)
    author = get_object_or_404(authors, pk=pk)
    projects = (
        Placement.objects.select_related("building", "author__profile", "facade_photo__panorama")
        if may_delete_other_works else published_placements()
    )
    page = Paginator(projects.filter(author=author), 12).get_page(request.GET.get("page"))
    return render(request, "profile.html", {
        "profile_user": author, "profile": getattr(author, "profile", None),
        "profile_rating": author_rating(author),
        "may_manage_restrictions": can_manage_restrictions(request.user, author),
        "may_delete_other_works": may_delete_other_works,
        "projects": page.object_list, "page": page,
    })


def avatar(request, pk):
    profile = get_object_or_404(Profile, user_id=pk, user__is_active=True)
    return image_response(profile.avatar)
