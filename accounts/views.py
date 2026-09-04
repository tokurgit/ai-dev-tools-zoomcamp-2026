from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
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


def filterprofile_edit(request, pk):
    """Edit one of ``request.user``'s filter profiles (issue #13).

    Ownership is enforced at the query — another user's ``pk`` is a 404, never a
    403 (see ``_docs/access-convention.md``). The #12 :class:`FilterProfileForm`
    is reused: it pre-populates its discrete fields from the stored ``criteria``
    on GET and re-serialises them on a valid POST, bumping ``updated_at``
    (``auto_now``). HTMX behaviour matches create — inline partial on error, a
    204 + ``HX-Redirect`` on success.
    """
    profile = get_object_or_404(FilterProfile, pk=pk, user=request.user)
    context = {
        "form_action": reverse("filterprofile_edit", args=[profile.pk]),
        "page_title": f"Edit “{profile.name}”",
        "submit_label": "Save changes",
    }
    if request.method == "POST":
        form = FilterProfileForm(
            request.POST, instance=profile, user=request.user
        )
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Filter profile “{profile.name}” updated."
            )
            if _is_htmx(request):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("filterprofile_list")
                return response
            return redirect("filterprofile_list")
        if _is_htmx(request):
            return render(
                request,
                "accounts/_filterprofile_form.html",
                {"form": form, **context},
            )
    else:
        form = FilterProfileForm(instance=profile, user=request.user)
    return render(
        request,
        "accounts/filterprofile_form.html",
        {"form": form, **context},
    )


def filterprofile_delete(request, pk):
    """Delete one of ``request.user``'s filter profiles (issue #13).

    Same query-level ownership scoping as :func:`filterprofile_edit`. GET shows
    a confirmation page; POST hard-deletes the profile. The profile's
    ``Notification`` rows are kept — their ``filter_profile`` FK is
    ``on_delete=SET_NULL``, so ``profile.delete()`` nulls the link and leaves
    the rows (sent and pending alike) attributable via ``user`` + ``listing``.
    """
    profile = get_object_or_404(FilterProfile, pk=pk, user=request.user)
    if request.method == "POST":
        name = profile.name
        profile.delete()
        messages.success(request, f"Filter profile “{name}” deleted.")
        return redirect("filterprofile_list")
    return render(
        request,
        "accounts/filterprofile_confirm_delete.html",
        {"profile": profile},
    )
