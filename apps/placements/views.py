import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.vary import vary_on_headers

from apps.buildings.addresses import CITY_FILTER, in_city
from apps.buildings.models import Building, FacadePhoto
from apps.murals.models import MuralDesign

from .forms import CommentForm, PlacementForm, RatingForm
from .models import Comment, Placement, Rating, can_moderate, published_placements, with_ratings
from .services.perspective import encode_image, render_placement


@vary_on_headers("X-Muralium-Feed")
def home(request):
    published = published_placements()
    projects = with_ratings(published, request.user)
    post = request.GET.get("post")
    if post is None:
        project = projects.first()
    else:
        if not post.isascii() or not post.isdecimal() or len(post) > 19 or int(post) >= 2**63:
            raise Http404
        project = get_object_or_404(projects, pk=post)

    context = {"project": project, "in_feed": True}
    if project:
        same_date = Q(published_at=project.published_at)
        newer = Q(published_at__gt=project.published_at) | (same_date & Q(pk__gt=project.pk))
        older = Q(published_at__lt=project.published_at) | (same_date & Q(pk__lt=project.pk))
        ids = published.values_list("pk", flat=True)
        previous_post = ids.filter(newer).order_by("published_at", "pk").first()
        next_post = ids.filter(older).first()
        if previous_post is None and next_post is not None:
            previous_post = ids.order_by("published_at", "pk").first()
        if next_post is None and previous_post is not None:
            next_post = ids.first()
        context.update(
            previous_post=previous_post,
            next_post=next_post,
            comments=project.comments.select_related("author__profile")[:20],
            comment_draft=take_comment_draft(request, project),
        )

    if request.headers.get("X-Muralium-Feed") == "1":
        return render(request, "feed.html", context)
    context["featured_project"] = published.first() if post is not None else project
    return render(request, "home.html", context)


def map_api(request):
    return JsonResponse({"projects": [
        {
            "id": project.pk,
            "title": project.title,
            "address": project.building.address,
            "latitude": float(project.building.latitude),
            "longitude": float(project.building.longitude),
            "image": reverse("project_image", args=[project.pk, "result"]),
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
    projects = Placement.objects.select_related("building", "author__profile", "facade_photo")
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
    page = Paginator(project.comments.select_related("author__profile"), 20).get_page(
        request.GET.get("page"),
    ) if published else None
    return render(request, "placement.html", {
        "project": project, "published": published,
        "comments": page.object_list if page else [], "page": page,
        "comment_draft": take_comment_draft(request, project) if published else "",
    })


def discussion_redirect(request, project, section):
    if request.POST.get("source") == "feed":
        return redirect(f"{reverse('home')}?post={project.pk}#projects")
    return redirect(f"{reverse('placement', args=[project.pk])}#{section}")


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
        messages.error(request, "Выберите оценку от 1 до 5.")
    return discussion_redirect(request, project, "rating")


@login_required
@require_POST
def comment(request, pk):
    project = get_object_or_404(published_placements(), pk=pk)
    form = CommentForm(request.POST)
    with transaction.atomic():
        author = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        restriction = getattr(author, "restrictions", None)
        if restriction and (restriction.ban_active or restriction.comments_block_active):
            messages.error(request, "Вам запрещено оставлять комментарии.")
        elif form.is_valid():
            Comment.objects.create(placement=project, author=author, text=form.cleaned_data["text"])
        else:
            request.session["comment_draft"] = {
                "project": project.pk,
                "text": request.POST.get("text", "")[:800],
                "error": form.errors["text"][0],
            }
    return discussion_redirect(request, project, "comments")


def take_comment_draft(request, project):
    draft = request.session.get("comment_draft")
    if draft and draft["project"] == project.pk:
        return request.session.pop("comment_draft")
    return None


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
    if kind == "before":
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
        revision = get_object_or_404(revisable_placements(request.user), pk=revision_pk) if revision_pk else None
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


def save_project(building, author, data, result, *, revision=None):
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

            previous_image = project.result_image.name
            storage = project.result_image.storage
            project.facade_photo = facade
            project.mural_design = design
            project.title = data["title"]
            project.description = data["description"]
            project.corners = data["corners"]
            project.status = Placement.Status.PENDING
            project.published_at = None
            project.revision_notes = ""
            project.rejection_reason = ""
            store(project.result_image, encode_image(result, png=True))
            project.save()
            if previous_image:
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
    building_id = (request.POST if submitting else request.GET).get("building")
    if not building_id and not submitting:
        return redirect("map")

    building = selected_building(building_id)
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

    return render(request, "editor.html", {"building": building, "form": form})



@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def revise(request, pk):
    if not can_submit_work(request.user):
        raise PermissionDenied("Вам запрещено отправлять работы.")
    project = get_object_or_404(revisable_placements(request.user).select_related("building"), pk=pk)
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
    })
