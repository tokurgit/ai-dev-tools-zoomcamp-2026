"""``accounts`` app URLs — the filter-profile pages (issue #12).

Included from ``config/urls.py`` at the project root. Every view here is
login-gated by ``LoginRequiredMiddleware`` (see ``_docs/access-convention.md``).
"""

from django.urls import path

from accounts import views

urlpatterns = [
    path("profiles/", views.filterprofile_list, name="filterprofile_list"),
    path("profiles/new/", views.filterprofile_create, name="filterprofile_create"),
    path(
        "profiles/<int:pk>/edit/",
        views.filterprofile_edit,
        name="filterprofile_edit",
    ),
    path(
        "profiles/<int:pk>/delete/",
        views.filterprofile_delete,
        name="filterprofile_delete",
    ),
]
