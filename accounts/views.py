from django.shortcuts import render


def home(request):
    """Placeholder landing page shown after login (``LOGIN_REDIRECT_URL``).

    Login-gated by ``LoginRequiredMiddleware`` like every other app view. #12
    links from / replaces this with the filter-profile dashboard.
    """
    return render(request, "home.html")
