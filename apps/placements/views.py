import json
import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.vary import vary_on_cookie

from apps.buildings.addresses import CITY_FILTER, in_city, street_walk_url
from apps.buildings.models import Building, FacadePhoto
from apps.murals.models import MuralDesign

from .forms import CommentForm, GraffitiPhotoForm, PlacementDeletionForm, PlacementForm, RatingForm
from .models import Comment, CommentLike, ModerationDecision, Placement, Rating, can_moderate, published_placements, with_ratings
from .services.perspective import encode_image, render_placement


def with_comment_likes(comments, viewer):
    comments = comments.select_related("author__profile").annotate(like_count=Count("likes")).order_by("-created_at", "-pk")
    if viewer.is_authenticated:
        liked = CommentLike.objects.filter(comment_id=OuterRef("pk"), author=viewer)
        comments = comments.annotate(viewer_liked=Exists(liked))
    return comments


def with_feed_comments(projects, viewer):
    comments = with_comment_likes(Comment.objects.all(), viewer).order_by("-like_count", "-created_at", "-pk")
    return projects.prefetch_related(Prefetch("comments", queryset=comments[:1], to_attr="feed_comments"))


def home(request):
    published = published_placements()
    post = request.GET.get("post")
    if post is not None:
        if not post.isascii() or not post.isdecimal() or len(post) > 19 or int(post) >= 2**63:
            raise Http404
        project = get_object_or_404(published, pk=post)
        return redirect(f"{reverse('home')}#project-{project.pk}")

    projects = list(with_feed_comments(with_ratings(published, request.user), request.user))
    for project in projects:
        project.comment_draft = take_comment_draft(request, project)
    return render(request, "home.html", {
        "projects": projects,
        "in_feed": True,
    })


def search(request):
    query = request.GET.get("q", "").strip()[:120]
    page = None
    if query:
        projects = published_placements()
        for term in query.split():
            pattern = re.escape(term)
            projects = projects.filter(
                Q(title__iregex=pattern)
                | Q(description__iregex=pattern)
                | Q(building__address__iregex=pattern)
                | Q(author__username__iregex=pattern)
                | Q(author__profile__nickname__iregex=pattern)
            )
        projects = with_feed_comments(with_ratings(projects, request.user), request.user)
        page = Paginator(projects, 6).get_page(request.GET.get("page"))
    return render(request, "search.html", {"search_query": query, "page": page})


@vary_on_cookie
def map_api(request):
    return JsonResponse({"projects": [
        {
            "id": project.pk,
            "title": project.title,
            "address": project.building.address,
            "latitude": float(project.building.latitude),
            "longitude": float(project.building.longitude),
            "image": reverse("project_image", args=[project.pk, "result"]),
            "is_own": project.author_id == request.user.pk,
            "url": reverse("placement", args=[project.pk]),
        }
        for project in published_placements().filter(**{
            f"building__{field}": bounds for field, bounds in CITY_FILTER.items()
        })
        if in_city(project.building.latitude, project.building.longitude)
    ]})


def is_published(project):
    return project.status == Placement.Status.APPROVED and project.published_at is not None


def visible_project(request, pk, *, include_ratings=False):
    projects = Placement.objects.select_related("building", "author__profile", "facade_photo__panorama")
    if include_ratings:
        projects = with_ratings(projects, request.user)
    project = get_object_or_404(projects, pk=pk)
    if is_published(project) or project.author_id == request.user.pk or can_moderate(request.user):
        return project
    raise Http404


@never_cache
def detail(request, pk):
    project = visible_project(request, pk, include_ratings=True)
    published = is_published(project)
    page = Paginator(with_comment_likes(project.comments.all(), request.user), 20).get_page(
        request.GET.get("page"),
    ) if published else None
    return render(request, "placement.html", {
        "project": project, "published": published,
        "comments": page.object_list if page else [], "page": page,
        "comment_draft": take_comment_draft(request, project) if published else "",
    })


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def delete_placement(request, pk):
    projects = Placement.objects.all()
    if not can_moderate(request.user):
        projects = projects.filter(author=request.user)

    if request.method == "POST" and request.POST.get("confirm") == "1":
        with transaction.atomic():
            project = get_object_or_404(projects.select_for_update(), pk=pk)
            moderator_removal = project.author_id != request.user.pk
            form = PlacementDeletionForm(request.POST) if moderator_removal else None
            if form is None or form.is_valid():
                author = project.author
                ModerationDecision.objects.filter(placement=project).update(
                    placement_title=project.title,
                    placement_author_username=author.get_username(),
                )
                if moderator_removal:
                    ModerationDecision.objects.create(
                        placement_title=project.title,
                        placement_author_username=author.get_username(),
                        recipient=author,
                        moderator=request.user,
                        moderator_username=request.user.get_username(),
                        status=ModerationDecision.DELETED,
                        deletion_reason=form.cleaned_data["reason"],
                    )
                image_name = project.result_image.name
                storage = project.result_image.storage
                project.delete()
                if image_name and not Placement.objects.filter(result_image=image_name).exists():
                    transaction.on_commit(lambda: storage.delete(image_name), robust=True)
                messages.success(request, "Работа удалена.")
                if moderator_removal:
                    return redirect("profile", pk=author.pk)
                return redirect("mine")
    else:
        project = get_object_or_404(projects, pk=pk)
        form = PlacementDeletionForm() if project.author_id != request.user.pk else None

    source = request.GET.get("from")
    if source == "wall" and project.author_id == request.user.pk:
        cancel_url = reverse("mine")
    elif source == "profile":
        cancel_url = reverse("profile", args=[project.author_id])
    elif source == "moderation" and can_moderate(request.user):
        cancel_url = reverse("moderation_review", args=[pk])
    else:
        cancel_url = reverse("placement", args=[pk])
    return render(request, "placement_delete.html", {"project": project, "form": form, "cancel_url": cancel_url})


def discussion_redirect(request, project, section):
    if request.POST.get("source") == "feed":
        return redirect(f"{reverse('home')}#project-{project.pk}")
    return redirect(f"{reverse('placement', args=[project.pk])}#{section}")


def asynchronous_feedback(request):
    return request.headers.get("X-Muralium-Async") == "1"


def feedback_response(request, project, section, *, new_comment=False):
    if not asynchronous_feedback(request):
        return discussion_redirect(request, project, section)

    in_feed = request.POST.get("source") == "feed"
    if section == "rating":
        updated = with_ratings(Placement.objects.filter(pk=project.pk), request.user).get()
        html = render_to_string(
            "rating.html", {"project": updated, "in_feed": in_feed}, request=request,
        )
    else:
        page = None
        if in_feed:
            project = with_ratings(Placement.objects.filter(pk=project.pk), request.user).get()
            comments = with_comment_likes(project.comments.all(), request.user).order_by(
                "-like_count", "-created_at", "-pk",
            )[:1]
        else:
            page_number = "1" if new_comment else request.POST.get("page", "1")
            page = Paginator(with_comment_likes(project.comments.all(), request.user), 20).get_page(page_number)
            comments = page.object_list
        html = render_to_string("discussion.html", {
            "project": project, "in_feed": in_feed, "comments": comments, "page": page,
        }, request=request)
    return JsonResponse({"html": html})


@login_required
@require_POST
def rate(request, pk):
    project = get_object_or_404(published_placements(), pk=pk)
    form = RatingForm(request.POST)
    if form.is_valid():
        Rating.objects.update_or_create(
            placement=project, author=request.user, defaults={"score": form.cleaned_data["score"]},
        )
    else:
        if asynchronous_feedback(request):
            return JsonResponse({"error": "Выберите оценку от 1 до 5."}, status=400)
        messages.error(request, "Выберите оценку от 1 до 5.")
    return feedback_response(request, project, "rating")


@login_required
@require_POST
def comment(request, pk):
    project = get_object_or_404(published_placements(), pk=pk)
    form = CommentForm(request.POST)
    is_async = asynchronous_feedback(request)
    with transaction.atomic():
        author = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        restriction = getattr(author, "restrictions", None)
        if restriction and (restriction.ban_active or restriction.comments_block_active):
            error = "Вам запрещено оставлять комментарии."
            if is_async:
                return JsonResponse({"error": error}, status=403)
            messages.error(request, error)
        elif form.is_valid():
            Comment.objects.create(placement=project, author=author, text=form.cleaned_data["text"])
        else:
            error = form.errors["text"][0]
            if is_async:
                return JsonResponse({"error": error}, status=400)
            request.session["comment_draft"] = {
                "project": project.pk,
                "text": request.POST.get("text", "")[:800],
                "error": error,
            }
    return feedback_response(request, project, "comments", new_comment=True)


def take_comment_draft(request, project):
    draft = request.session.get("comment_draft")
    if draft and draft["project"] == project.pk:
        return request.session.pop("comment_draft")
    return None


@login_required
@require_POST
def like_comment(request, pk):
    entry = get_object_or_404(
        Comment.objects.select_related("placement"), pk=pk, placement__in=published_placements(),
    )
    likes = CommentLike.objects.filter(comment=entry, author=request.user)
    liked = request.POST.get("liked")
    if asynchronous_feedback(request) and liked not in ("0", "1"):
        return JsonResponse({"error": "Не удалось изменить лайк."}, status=400)
    if liked == "1":
        likes.get_or_create(comment=entry, author=request.user)
    else:
        likes.delete()
    return feedback_response(request, entry.placement, "comments")


def image_response(image):
    if not image:
        raise Http404
    content_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    suffix = "." + image.name.rsplit(".", 1)[-1].lower()
    if suffix not in content_types:
        raise Http404
    try:
        response = FileResponse(image.open("rb"), content_type=content_types[suffix])
    except FileNotFoundError as error:
        raise Http404 from error
    add_never_cache_headers(response)
    return response


def project_image(request, pk, kind):
    project = visible_project(request, pk)
    if kind == "result":
        return image_response(project.result_image)
    if kind == "before" and not project.is_existing_graffiti:
        return image_response(project.facade_photo.image)
    raise Http404


def asset(request, kind, pk):
    if kind == "facade":
        item = get_object_or_404(FacadePhoto, pk=pk)
        owner = item.uploaded_by_id
    elif kind == "design":
        item = get_object_or_404(MuralDesign, pk=pk)
        owner = item.author_id
    else:
        raise Http404
    if not (item.is_public or owner == request.user.pk or can_moderate(request.user)):
        raise Http404
    return image_response(item.image)


def selected_building(value):
    try:
        pk = int(value)
    except (TypeError, ValueError) as error:
        raise Http404 from error
    if not 0 < pk < 2**63:
        raise Http404
    return get_object_or_404(Building, pk=pk)


def rendered_image(data):
    return render_placement(data["facade_image"], data["mural_image"], data["corners"])


@require_POST
@never_cache
def preview(request, revision_pk=None):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Войдите, чтобы создать визуализацию."}, status=401)
    if not can_submit_work(request.user):
        return JsonResponse({"error": "Вам запрещено отправлять работы."}, status=403)
    try:
        revision = get_object_or_404(
            revisable_placements(request.user), pk=revision_pk, facade_photo__isnull=False,
        ) if revision_pk else None
        building = revision.building if revision else selected_building(request.POST.get("building"))
    except Http404:
        return JsonResponse({"error": "Заявка на доработке или здание не найдены."}, status=404)
    form = PlacementForm(request.POST, request.FILES, building=building, preview=True, revision=revision)
    if not form.is_valid():
        return JsonResponse({"errors": dict(form.errors)}, status=400)
    try:
        result = encode_image(rendered_image(form.cleaned_data), png=True)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return HttpResponse(result.read(), content_type="image/png")


def can_submit_work(user):
    restriction = getattr(user, "restrictions", None)
    return not (restriction and (restriction.ban_active or restriction.publications_block_active))


def revisable_placements(author):
    return Placement.objects.filter(author=author, status=Placement.Status.REVISION)


def save_project(building, author, data, result, *, revision=None, existing_photo=False):
    stored_files = []

    def store(field, content):
        field.save(content.name, content, save=False)
        stored_files.append((field.storage, field.name))

    try:
        with transaction.atomic():
            author = get_user_model().objects.select_for_update().get(pk=author.pk)
            if not can_submit_work(author):
                raise PermissionDenied("Вам запрещено отправлять работы.")
            if revision is None:
                project = Placement(building=building, author=author)
            else:
                project = get_object_or_404(revisable_placements(author).select_for_update(), pk=revision.pk)
                current = (project.facade_photo_id, project.mural_design_id, project.result_image.name, project.revision_notes)
                original = (revision.facade_photo_id, revision.mural_design_id, revision.result_image.name, revision.revision_notes)
                if current != original:
                    raise ValidationError("Заявка изменилась. Откройте редактор заново.")
            if existing_photo:
                project.corners = []
            else:
                facade = data["facade"]
                if data["facade_file"]:
                    facade = FacadePhoto(building=building, uploaded_by=author)
                    store(facade.image, encode_image(data["facade_image"], png=True))
                    facade.save()
                design = data["design"]
                if data["mural_file"]:
                    design = MuralDesign(title=data["title"], author=author)
                    store(design.image, encode_image(data["mural_image"], png=True))
                    design.save()
                    design.buildings.add(building)
                project.facade_photo = facade
                project.mural_design = design
                project.corners = data["corners"]

            previous_image = project.result_image.name
            storage = project.result_image.storage
            project.title = data["title"]
            project.description = data["description"]
            project.status = Placement.Status.PENDING
            project.published_at = None
            project.revision_notes = ""
            project.rejection_reason = ""
            if result is not None:
                store(project.result_image, encode_image(result, png=not existing_photo))
            project.save()
            if previous_image and result is not None:
                transaction.on_commit(lambda: storage.delete(previous_image), robust=True)
    except Exception:
        for storage, name in stored_files:
            storage.delete(name)
        raise
    return project


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    if not can_submit_work(request.user):
        raise PermissionDenied("Вам запрещено отправлять работы.")
    submitting = request.method == "POST"
    params = request.POST if submitting else request.GET
    existing_photo = params.get("mode") == "photo"
    building_id = params.get("building")
    if not building_id and not submitting:
        return render(request, "create_placement.html", {"existing_photo": existing_photo})

    building = selected_building(building_id)
    if existing_photo:
        return graffiti_photo_editor(request, building)
    form = PlacementForm(
        request.POST if submitting else None,
        request.FILES if submitting else None,
        building=building,
    )
    if form.is_valid():
        try:
            result = rendered_image(form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            project = save_project(building, request.user, form.cleaned_data, result)
            return redirect("placement", pk=project.pk)

    return render(request, "editor.html", {
        "building": building,
        "form": form,
        "street_walk_url": street_walk_url(building.latitude, building.longitude),
    })



@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def revise(request, pk):
    if not can_submit_work(request.user):
        raise PermissionDenied("Вам запрещено отправлять работы.")
    project = get_object_or_404(revisable_placements(request.user).select_related("building"), pk=pk)
    if project.is_existing_graffiti:
        return graffiti_photo_editor(request, project.building, revision=project)

    submitting = request.method == "POST"
    form = PlacementForm(
        request.POST if submitting else None,
        request.FILES if submitting else None,
        building=project.building,
        revision=project,
        initial={
            "title": project.title, "description": project.description,
            "facade": project.facade_photo_id, "design": project.mural_design_id,
            "corners": json.dumps(project.corners),
        },
    )
    if form.is_valid():
        try:
            result = rendered_image(form.cleaned_data)
            save_project(project.building, request.user, form.cleaned_data, result, revision=project)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Исправленная заявка отправлена на модерацию.")
            return redirect("placement", pk=project.pk)

    return render(request, "editor.html", {
        "building": project.building, "form": form, "revision": project,
        "preview_url": reverse("revision_preview", args=[project.pk]),
        "street_walk_url": street_walk_url(project.building.latitude, project.building.longitude),
    })


def graffiti_photo_editor(request, building, *, revision=None):
    submitting = request.method == "POST"
    form = GraffitiPhotoForm(
        request.POST if submitting else None,
        request.FILES if submitting else None,
        revision=revision,
        initial={"title": revision.title, "description": revision.description} if revision else None,
    )
    if form.is_valid():
        data = form.cleaned_data
        try:
            project = save_project(
                building, request.user, data, data["photo"], revision=revision, existing_photo=True,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if revision:
                messages.success(request, "Исправленная заявка отправлена на модерацию.")
            return redirect("placement", pk=project.pk)

    return render(request, "create_placement.html", {
        "building": building, "form": form, "revision": revision, "existing_photo": True,
    })
