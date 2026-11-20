from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from .models import CommentDeletion, ModerationDecision, Placement, can_moderate


class ModerationForm(forms.ModelForm):
    class Meta:
        model = Placement
        fields = ["status", "rejection_reason", "revision_notes"]

    class Media:
        js = ["js/moderation.js"]

    def clean(self):
        data = super().clean()
        for status, field, error in (
            (Placement.Status.REJECTED, "rejection_reason", "Укажите причину отклонения."),
            (Placement.Status.REVISION, "revision_notes", "Укажите, что автору нужно исправить."),
        ):
            if data.get("status") == status:
                if not data.get(field):
                    self.add_error(field, error)
            else:
                data[field] = ""
        return data


class DecisionForm(ModerationForm):
    status = forms.ChoiceField(
        label="Решение",
        choices=[
            ("", "Выберите решение"),
            (Placement.Status.APPROVED, "Опубликовать"),
            (Placement.Status.REVISION, "Вернуть на доработку"),
            (Placement.Status.REJECTED, "Отклонить"),
        ],
    )


class HistoryFilterForm(forms.Form):
    title = forms.CharField(label="Название работы", required=False, max_length=200)
    moderator = forms.CharField(label="Логин модератора", required=False, max_length=150)
    date = forms.DateField(label="Дата", required=False, widget=forms.DateInput(attrs={"type": "date"}))


class DecisionHistoryFilterForm(HistoryFilterForm):
    status = forms.ChoiceField(
        label="Решение", required=False, choices=[("", "Все решения"), *Placement.Status.choices],
    )


class CommentHistoryFilterForm(HistoryFilterForm):
    author = forms.CharField(label="Логин автора комментария", required=False, max_length=150)


def prepare_decision(project):
    if project.status == Placement.Status.APPROVED:
        project.published_at = project.published_at or timezone.now()
    else:
        project.published_at = None
    if project.status != Placement.Status.REJECTED:
        project.rejection_reason = ""
    if project.status != Placement.Status.REVISION:
        project.revision_notes = ""


def record_decision(project, moderator):
    ModerationDecision.objects.create(
        placement=project,
        moderator=moderator,
        moderator_username=moderator.get_username(),
        status=project.status,
        rejection_reason=project.rejection_reason,
        revision_notes=project.revision_notes,
    )


def require_moderation_access(user):
    if not can_moderate(user):
        raise PermissionDenied
    return True


@never_cache
@login_required
@user_passes_test(require_moderation_access)
@require_safe
def queue(request):
    projects = Placement.objects.filter(status=Placement.Status.PENDING).select_related(
        "building", "author__profile",
    ).order_by("created_at", "pk")
    page = Paginator(projects, 20).get_page(request.GET.get("page"))
    counts = dict(Placement.objects.order_by().values_list("status").annotate(total=Count("pk")))
    status_counts = [(label, counts.get(status, 0)) for status, label in Placement.Status.choices]
    return render(request, "moderation/queue.html", {"page": page, "status_counts": status_counts})


@never_cache
@login_required
@user_passes_test(require_moderation_access)
@require_safe
def history(request):
    show_deletions = request.GET.get("kind") == "comments"
    if show_deletions:
        entries = CommentDeletion.objects.select_related("placement__author__profile")
        filters = CommentHistoryFilterForm(request.GET)
        lookups = {"title": "placement_title__icontains", "author": "author_username__icontains"}
    else:
        entries = ModerationDecision.objects.select_related("placement__author__profile", "moderator__profile")
        filters = DecisionHistoryFilterForm(request.GET)
        lookups = {"title": "placement__title__icontains", "status": "status"}

    lookups.update(moderator="moderator_username__icontains", date="created_at__date")
    if filters.is_valid():
        entries = entries.filter(**{
            lookup: filters.cleaned_data[field]
            for field, lookup in lookups.items()
            if filters.cleaned_data[field]
        })
    else:
        entries = entries.none()
    page = Paginator(entries, 25).get_page(request.GET.get("page"))
    return render(request, "moderation/history.html", {
        "page": page, "filters": filters, "show_deletions": show_deletions,
    })


@never_cache
@login_required
@user_passes_test(require_moderation_access)
@require_http_methods(["GET", "POST"])
def review(request, pk):
    if request.method == "POST":
        with transaction.atomic():
            project = get_object_or_404(Placement.objects.select_for_update(), pk=pk)
            if project.status != Placement.Status.PENDING:
                messages.info(request, "По этой заявке уже принято решение.")
                return redirect("moderation_queue")

            form = DecisionForm(request.POST, instance=project)
            if form.is_valid():
                project = form.save(commit=False)
                prepare_decision(project)
                project.save(update_fields=["status", "rejection_reason", "revision_notes", "published_at"])
                record_decision(project, request.user)
                messages.success(request, f"«{project.title}» — {project.get_status_display().lower()}.")
                return redirect("moderation_queue")
    else:
        project = get_object_or_404(
            Placement.objects.select_related("building", "author__profile"), pk=pk,
        )
        form = DecisionForm(instance=project)

    # ModelForm validation mutates the instance even if the decision is invalid.
    return render(request, "moderation/review.html", {
        "project": project,
        "form": form,
        "decisions": project.moderation_decisions.select_related("placement__author__profile", "moderator__profile"),
        "can_decide": request.method == "POST" or project.status == Placement.Status.PENDING,
    })
