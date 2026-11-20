from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "POST"])
def register(request):
    next_url = request.POST.get("next", "") if request.method == "POST" else request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        next_url = ""
    if request.user.is_authenticated:
        return redirect(next_url or "mine")
    form = UserCreationForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        login(request, form.save())
        return redirect(next_url or "map")
    return render(request, "registration/register.html", {"form": form, "next": next_url})
