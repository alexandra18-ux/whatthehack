from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.buildings.models import Building, FacadePhoto
from apps.murals.models import MuralDesign

from .forms import PlacementForm
from .models import Placement, can_moderate, published_placements
from .services.perspective import encode_image, render_placement


def home(request):
    return render(request, "home.html", {"projects": published_placements()[:12]})


@login_required
def mine(request):
    projects = Placement.objects.filter(author=request.user).select_related("building", "author")
    return render(request, "mine.html", {"projects": projects})


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
        for project in published_placements()
    ]})


def is_published(project):
    return project.status == Placement.Status.APPROVED and project.published_at is not None


def visible_project(request, pk):
    project = get_object_or_404(
        Placement.objects.select_related("building", "author", "facade_photo"), pk=pk,
    )
    if is_published(project) or project.author_id == request.user.pk or can_moderate(request.user):
        return project
    raise Http404


@never_cache
def detail(request, pk):
    return render(request, "placement.html", {"project": visible_project(request, pk)})


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
