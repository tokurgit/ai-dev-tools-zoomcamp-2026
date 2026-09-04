"""URL configuration for config project.

Auth is Django's built-in ``django.contrib.auth`` views wired explicitly under
``/accounts/`` — login, logout and password-change only. The password-reset
(by email) views are deliberately NOT routed (issue #11); there is also no
signup/registration route — users are created via ``createsuperuser`` or the
admin.

Login is enforced globally by ``LoginRequiredMiddleware`` (see config/settings.py
and _docs/access-convention.md). Only the login view is marked
``login_not_required`` so an anonymous visitor can reach it; every other URL
here (home, logout, password change) requires an authenticated session.
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path

from accounts.views import home

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('', include('accounts.urls')),
    path(
        'accounts/login/',
        login_not_required(auth_views.LoginView.as_view()),
        name='login',
    ),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path(
        'accounts/password_change/',
        auth_views.PasswordChangeView.as_view(),
        name='password_change',
    ),
    path(
        'accounts/password_change/done/',
        auth_views.PasswordChangeDoneView.as_view(),
        name='password_change_done',
    ),
]
