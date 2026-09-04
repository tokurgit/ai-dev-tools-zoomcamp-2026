from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.forms import FilterProfileForm
from accounts.models import FilterProfile
from accounts.summaries import summarize_criteria, summarize_preferences


def home(request):
    """Placeholder landing page shown after login (``LOGIN_REDIRECT_URL``).

    Login-gated by ``LoginRequiredMiddleware`` like every other app view. #12
    links from / replaces this with the filter-profile dashboard.
    """
    return render(request, "home.html")


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def filterprofile_list(request):
    """List the current user's filter profiles (issue #12).

    Scoped strictly to ``request.user`` per ``_docs/access-convention.md``.
    """
    profiles = FilterProfile.objects.filter(user=request.user)
    rows = [
        {
            "profile": profile,
            "criteria": summarize_criteria(profile.criteria),
            "preferences": summarize_preferences(profile),
        }
        for profile in profiles
    ]
    return render(request, "accounts/filterprofile_list.html", {"rows": rows})


def filterprofile_create(request):
    """Create a filter profile owned by ``request.user`` (issue #12).

    ``user`` is bound server-side in :class:`FilterProfileForm`, never taken
    from POST data. A valid submit redirects to the list with a success
    message (an ``HX-Redirect`` header for HTMX requests); an invalid HTMX
    submit re-renders just the form partial with inline errors.
    """
    if request.method == "POST":
        form = FilterProfileForm(request.POST, user=request.user)
        if form.is_valid():
            profile = form.save()
            messages.success(
                request, f"Filter profile “{profile.name}” created."
            )
            if _is_htmx(request):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("filterprofile_list")
                return response
            return redirect("filterprofile_list")
        if _is_htmx(request):
            return render(
                request, "accounts/_filterprofile_form.html", {"form": form}
            )
    else:
        form = FilterProfileForm(user=request.user)
    return render(request, "accounts/filterprofile_form.html", {"form": form})
