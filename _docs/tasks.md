# Backlog

## 1. Project bootstrap with passing test
Goal: Set up an empty Django project with one smoke test that passes.
Description: Create a new Django project and app skeleton using `uv` for all dependency and virtual environment management (no pip/venv directly). Configure settings for SQLite and add one trivial test (e.g. asserting the app loads) so the CI baseline is green from day one. All subsequent tasks assume `uv run` / `uv pip` as the standard interface.

## 2. Define the Listing model
Goal: Create the database model that represents a single auction listing.
Description: Inspect the actual `izsoles.csv` column structure and map each relevant column to a Django model field. Include a `raw_hash` field (hash of the full row) to enable fast change detection later. Write a migration and a test asserting the model can be saved and retrieved.

## 3. Define the reference-data models
Goal: Store category, region, and organizer lookup tables in the database.
Description: Create Django models for `Category`, `Region`, and `Organizer` based on the three supporting CSVs (`kategorija.csv`, `region.csv`, `birojs.csv`). These are used to decode codes on listings into human-readable labels. Include a management command that loads them from CSV, and a test that the load is idempotent.

## 4. CSV fetch and parse
Goal: Download and parse `izsoles.csv` into Python objects.
Description: Write a module that fetches the main CSV from the open-data URL (with a realistic `User-Agent`) and parses each row into a dict keyed by the model's field names. Handle encoding and any malformed rows gracefully. Include unit tests using a local fixture CSV so tests don't make real HTTP calls.

## 5. Listing import and diffing
Goal: Persist parsed listings to the DB and detect new or changed rows.
Description: Write a function that, given parsed CSV rows, upserts listings into the database and returns two lists: newly added listings and listings whose `raw_hash` changed. Write tests covering the insert-on-first-run, no-change, and changed-row scenarios.

## 6. Define a custom User model and the FilterProfile model
Goal: Establish a project-owned User model and store filter criteria in the database.
Description: Define a custom `User` model subclassing `AbstractUser` (even if empty initially) and set `AUTH_USER_MODEL` in settings — Django's own docs recommend this from day one because swapping the user model after migrations is painful. Then create a `FilterProfile` model linked to this custom user, with a `JSONField` for filter criteria (region codes, category codes, min/max price, etc.) and fields for notification preferences. Write migrations and basic model tests.

## 7. Filter matching logic
Goal: Determine which filter profiles match a given listing.
Description: Write a pure function that takes a listing and a list of filter profiles and returns the profiles that match, applying AND logic across criteria fields. Cover edge cases (empty filter = match all, missing fields, price range boundaries) with unit tests — no database needed for this module.

## 8. Define the Notification model and queuing logic
Goal: Record matched alerts in the DB so they can be dispatched later.
Description: Create a `Notification` model that links a user, a filter profile, a listing, and an alert type (new / changed / deadline-approaching). Write a function that, given match results, inserts pending notification rows without sending anything yet. Test that duplicates are not created if the same match occurs twice.

## 9. Email dispatch with pluggable provider backend
Goal: Send queued notifications as emails via a provider-agnostic interface.
Description: Define a `NotificationBackend` protocol/abstract class with a single `send(to, subject, body)` method, then implement it for Resend as the first concrete backend. The active backend is selected by a Django setting (e.g. `NOTIFICATION_BACKEND`), making it straightforward to swap in Postmark, SendGrid, or a console/file backend for local dev. Write a test using a stub backend to cover grouping, rendering, and the sent-flag logic — no real HTTP calls in tests.

## 10. Daily orchestration management command
Goal: Wire all the above steps into one runnable Django management command.
Description: Create `manage.py run_daily_import` that calls fetch → parse → import/diff → match filters → queue notifications → dispatch email in sequence. Log progress at each step. Integration-test the happy path using fixture data and a stubbed email sender.

## 11. User authentication and RBAC setup
Goal: Allow users to log in/out and establish role-based access control.
Description: Enable Django's built-in auth views (login, logout, password change) with minimal templates. Define at least two permission groups — e.g. `viewer` (read-only access to own data) and `manager` (can also manage filter profiles) — assigned at user creation via Django admin. Protect views with both `@login_required` and permission checks so access rules are predictable and testable. No self-registration for v1. Test each group's access explicitly (e.g. a `viewer` cannot POST to create a filter profile).

## 12. Filter profile list and create views
Goal: Let a logged-in user view and create filter profiles scoped to their account.
Description: Build a page listing the user's existing filter profiles and a form to create a new one, using Django forms and HTMX for inline feedback. Validate that at least one filter criterion is set. All querysets must filter by `request.user` — users must not be able to access any data belonging to other users, not just profiles. Test both that a user sees their own data and that direct URL access to another user's resources returns 404 (not just an empty page).

## 13. Filter profile edit and delete views
Goal: Let a user modify or remove an existing filter profile.
Description: Add edit and delete views for filter profiles, with a confirmation step for deletion. Reuse the create form for editing. All queryset lookups must use `get_object_or_404(FilterProfile, pk=pk, user=request.user)` — never fetch by PK alone — so ownership is enforced at the data layer, not just checked afterwards. Test that direct URL access to another user's profile returns 404 and that deletion also removes associated pending notifications.

## 14. Notification preference settings
Goal: Let a user configure how and when they receive alerts, with sensible defaults.
Description: Add a per-profile settings section (within the edit view) for alert types (new listing, price change, deadline reminder) and email timing (immediate vs. daily digest). Default new profiles to daily digest + new listing alerts — the most useful, least noisy combination. Persist choices on the `FilterProfile` model. Test that the orchestration command respects these preferences and that new profiles created without explicit preferences carry the correct defaults.

## 15. Django admin setup
Goal: Expose key models in the Django admin for operator use.
Description: Register `Listing`, `FilterProfile`, `Notification`, `Category`, `Region`, and `Organizer` in the Django admin with useful list display fields and filters. Add a custom admin action to manually re-send a failed notification. Test that the admin pages load without errors.

## 16. Deployment: reusable VPS setup playbook
Goal: Produce a parameterized deployment playbook that can be applied to any Django project, not just this one.
Description: Write an Ansible playbook (or equivalent shell scripts with clearly documented variables) that installs system dependencies, creates a dedicated system user, configures Gunicorn as a systemd service, sets up Nginx as a reverse proxy, and obtains a Let's Encrypt certificate via Certbot. All project-specific values (domain, app name, repo URL, Python version) must be variables — the playbook should be reusable by swapping a vars file. Include a post-deploy smoke test (HTTP 200 on the login page) and a brief README explaining how to adapt it to a different project.

## 17. Deployment: cron job for daily import
Goal: Schedule the daily import command to run automatically on the VPS.
Description: Add a system cron entry that runs `manage.py run_daily_import` once per day at a fixed time (e.g. 07:00 local time, after the source feed typically refreshes). Redirect output to a log file and configure log rotation. Verify the job runs successfully on first manual trigger post-deploy.
