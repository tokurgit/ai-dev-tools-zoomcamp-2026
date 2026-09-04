# Access convention (issue #11)

Authorization in this project is **login + per-user ownership scoping**. There
are no Django `Group`s, custom roles, or per-view permission wiring.

## Rules every app view must follow (#12–#14 depend on this)

- **Every view is login-gated.** `LoginRequiredMiddleware`
  (`config/settings.py`, added right after `AuthenticationMiddleware`) enforces
  this project-wide. Only the login view carries `login_not_required`
  (`config/urls.py`). Do not add `login_not_required` to any app view.
- **Every queryset is scoped to the requester:**
  `Model.objects.filter(user=request.user)`.
- **Every single-object lookup is scoped to the requester:**
  `get_object_or_404(Model, pk=..., user=request.user)`.
  Another user's object must therefore surface as a 404, never a 403.
- **No Django `Group` / `Permission` checks** are used for app views.

## Operator access

Operator / staff tasks live in the Django admin. Operator access =
`is_staff` / `is_superuser` + the admin site (#15). No custom groups or roles.

## Auth surface

- Built-in `django.contrib.auth` views only, routed explicitly under
  `/accounts/`: `login`, `logout`, `password_change`,
  `password_change/done`.
- No password-reset-by-email routes. No signup/registration route — users are
  created via `createsuperuser` or the admin.
- `LogoutView` is POST-only (Django 5+); the logout control in `base.html` is a
  POST form.
