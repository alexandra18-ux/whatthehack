from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.users.auth import can_manage_restrictions
from apps.users.models import AccountRestriction

from .models import Comment, CommentDeletion
from .moderation import require_moderation_access
from .views import discussion_redirect


class RestrictionForm(forms.Form):
    restriction_fields = (
        ("banned", "banned_until", "ban_active", "Блокировка аккаунта"),
        ("comments_blocked", "comments_blocked_until", "comments_block_active", "Запрет на комментарии"),
        ("publications_blocked", "publications_blocked_until", "publications_block_active", "Запрет на отправку работ"),
    )
    durations = [
        ("1", "1 час"), ("3", "3 часа"), ("12", "12 часов"),
        ("24", "1 день"), ("168", "Неделя"), ("720", "Месяц"),
    ]

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance if instance is not None else AccountRestriction()
        for flag, _, active, label in self.restriction_fields:
            is_active = getattr(self.instance, active)
            choices = [("off", "Без ограничения"), *self.durations, ("indefinite", "Бессрочно")]
            if is_active:
                choices.insert(1, ("keep", "Сохранить текущий срок"))
            self.fields[flag] = forms.ChoiceField(
                label=label, choices=choices, required=False, initial="keep" if is_active else "off",
            )

    @property
    def restriction_rows(self):
        return [
            (self[flag], getattr(self.instance, expires), getattr(self.instance, active))
            for flag, expires, active, _ in self.restriction_fields
        ]

    def save(self):
        now = timezone.now()
        for flag, expires, _, _ in self.restriction_fields:
            choice = self.cleaned_data[flag] or "off"
            if choice == "keep":
                continue
            setattr(self.instance, flag, choice != "off")
            expires_at = now + timedelta(hours=int(choice)) if choice.isdecimal() else None
            setattr(self.instance, expires, expires_at)
        self.instance.save()


@never_cache
@login_required
@user_passes_test(require_moderation_access)
@require_safe
def comment_list(request):
    query = request.GET.get("q", "").strip()[:200]
    comments = Comment.objects.select_related("placement__author__profile", "author__profile")
    accounts = ()
    if query:
        comments = comments.filter(
            Q(text__icontains=query) | Q(author__username__icontains=query) | Q(placement__title__icontains=query)
        )
        accounts = get_user_model().objects.filter(username__icontains=query).select_related("profile", "restrictions").order_by("username")[:20]
    page = Paginator(comments, 25).get_page(request.GET.get("page"))
    return render(request, "moderation/comments.html", {"page": page, "query": query, "accounts": accounts})


@login_required
@user_passes_test(require_moderation_access)
@require_POST
def delete_comment(request, pk):
    with transaction.atomic():
        comment = get_object_or_404(Comment.objects.select_for_update(), pk=pk)
        project = comment.placement
        CommentDeletion.objects.create(
            placement=project,
            placement_title=project.title,
            author_username=comment.author.get_username(),
            moderator_username=request.user.get_username(),
            text=comment.text,
        )
        comment.delete()
    messages.success(request, "Комментарий удалён.")
    if request.POST.get("source") == "moderation":
        return redirect("moderation_comments")
    return discussion_redirect(request, project, "comments")


def check_target(moderator, account):
    if not can_manage_restrictions(moderator, account):
        raise PermissionDenied("У вас нет прав менять ограничения этого аккаунта.")


@never_cache
@login_required
@user_passes_test(require_moderation_access)
@require_http_methods(["GET", "POST"])
def restrict_account(request, pk):
    accounts = get_user_model().objects.all()
    if request.method == "POST":
        with transaction.atomic():
            account = get_object_or_404(accounts.select_for_update(), pk=pk)
            check_target(request.user, account)
            restriction = getattr(account, "restrictions", None) or AccountRestriction(user=account)
            clear = request.POST.get("action") == "clear"
            form = RestrictionForm({} if clear else request.POST, instance=restriction)
            if form.is_valid():
                form.save()
                if clear:
                    messages.success(request, f"Все ограничения для {account.get_username()} сняты.")
                else:
                    messages.success(request, f"Ограничения для {account.get_username()} сохранены.")
                return redirect("moderation_restrict_account", pk=account.pk)
    else:
        account = get_object_or_404(accounts, pk=pk)
        check_target(request.user, account)
        form = RestrictionForm(instance=getattr(account, "restrictions", None))
    return render(request, "moderation/account.html", {"account": account, "form": form})



@never_cache
@login_required
@user_passes_test(require_moderation_access)
@require_safe
def account_list(request):
    query = request.GET.get("q", "").strip()[:200]
    restricted_only = request.GET.get("status") == "restricted"
    role = request.GET.get("role")
    accounts = get_user_model().objects.select_related("profile", "restrictions").order_by("username", "pk")
    administrator = Q(is_staff=True) | Q(is_superuser=True)
    if role == "admin":
        accounts = accounts.filter(administrator)
    elif role == "user":
        accounts = accounts.exclude(administrator)
    else:
        role = ""
    if query:
        accounts = accounts.filter(Q(username__icontains=query) | Q(profile__nickname__icontains=query))
    if restricted_only:
        now = timezone.now()
        active = Q()
        for flag, expires, _, _ in RestrictionForm.restriction_fields:
            active |= Q(**{f"restrictions__{flag}": True}) & (
                Q(**{f"restrictions__{expires}__isnull": True}) | Q(**{f"restrictions__{expires}__gt": now})
            )
        accounts = accounts.filter(active)
    page = Paginator(accounts, 25).get_page(request.GET.get("page"))
    for account in page:
        account.can_manage_restrictions = can_manage_restrictions(request.user, account)
    return render(request, "moderation/accounts.html", {
        "page": page, "query": query, "restricted_only": restricted_only, "role": role,
    })
