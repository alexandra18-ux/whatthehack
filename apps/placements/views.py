from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
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
        context.update(
            previous_post=ids.filter(newer).order_by("published_at", "pk").first(),
            next_post=ids.filter(older).first(),
            comments=project.comments.select_related("author__profile")[:20],
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
    if form.is_valid():
        Comment.objects.create(placement=project, author=request.user, text=form.cleaned_data["text"])
    else:
        messages.error(request, "Введите комментарий длиной от 1 до 800 символов.")
    return discussion_redirect(request, project, "comments")


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
def preview(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Войдите, чтобы создать визуализацию."}, status=401)
    try:
        building = selected_building(request.POST.get("building"))
    except Http404:
        return JsonResponse({"error": "Здание не найдено."}, status=404)
    form = PlacementForm(request.POST, request.FILES, building=building, preview=True)
    if not form.is_valid():
        return JsonResponse({"errors": dict(form.errors)}, status=400)
    try:
        result = encode_image(rendered_image(form.cleaned_data), png=True)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return HttpResponse(result.read(), content_type="image/png")


def save_project(building, author, data, result):
    stored_files = []

    def store(field, content):
        field.save(content.name, content, save=False)
        stored_files.append((field.storage, field.name))

    try:
        with transaction.atomic():
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

            project = Placement(
                building=building, author=author, facade_photo=facade, mural_design=design,
                title=data["title"], description=data["description"], corners=data["corners"],
            )
            store(project.result_image, encode_image(result, png=True))
            project.save()
    except Exception:
        for storage, name in stored_files:
            storage.delete(name)
        raise
    return project


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
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
