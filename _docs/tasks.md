# Backlog

> All tasks below are groomed as GitHub issues (#2–#22) — the issue is the
> source of truth; this file is the running index. Follow-ups filed during
> grooming: #18 (Listing FKs, do right after #3), #19 (deadline queuing),
> #20 (RBAC via Groups — parked), #21 (pytest runner), #22 (env-driven settings,
> prereq for #16).

## 1. Project bootstrap with passing test
Goal: Set up an empty Django project with one smoke test that passes.
Description: Create a new Django project and app skeleton using `uv` for all dependency and virtual environment management (no pip/venv directly). Configure settings for SQLite and add one trivial test (e.g. asserting the app loads) so the CI baseline is green from day one. All subsequent tasks assume `uv run` / `uv pip` as the standard interface.

## 2. Define the Listing model
Goal: Create the database model that represents a single auction listing.
Description: Inspect the actual `izsoles.csv` column structure and map each relevant column to a Django model field. Include a `raw_hash` field (hash of the full row) to enable fast change detection later. Write a migration and a test asserting the model can be saved and retrieved. (Implemented pre-process in `a29a18c`/`06024c7`; GH #2 groomed retroactively as a verification checklist — verify against the code and close.)

## 3. Define the reference-data models
Goal: Store category, region, and organizer lookup tables in the database.
Description: Create Django models for `Category`, `Region`, and `Organizer` based on the three supporting CSVs (`kategorija.csv`, `region.csv`, `birojs.csv`). These are used to decode codes on listings into human-readable labels. Include a management command that loads them from CSV, and a test that the load is idempotent.

## 3b. Convert Listing region/category codes to ForeignKeys (GH #18)
Goal: Point `Listing.region` / `Listing.category` at the reference models instead of loose codes.
Description: Split out of task 3 during grooming. Do immediately after task 3 and before task 4, so the CSV import work is built against the final schema. Nullable FKs with `on_delete=SET_NULL`; `office_id` stays a plain field (no reference model). See GH #18.

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

## 8b. Deadline-approaching notification detection and queuing (GH #19)
Goal: Queue `deadline` notifications for matching listings whose auction end_time is near.
Description: Split out of task 8 during grooming — deadline reminders are time-driven, not diff-driven, so they need a separate producer that reuses the task 7 matcher and task 8 dedup. See GH #19.

## 9. Email dispatch with pluggable provider backend
Goal: Send queued notifications as emails via a provider-agnostic interface.
Description: Define a `NotificationBackend` protocol/abstract class with a single `send(to, subject, body)` method, then implement it for Resend as the first concrete backend. The active backend is selected by a Django setting (e.g. `NOTIFICATION_BACKEND`), making it straightforward to swap in Postmark, SendGrid, or a console/file backend for local dev. Write a test using a stub backend to cover grouping, rendering, and the sent-flag logic — no real HTTP calls in tests.

## 10. Daily orchestration management command
Goal: Wire all the above steps into one runnable Django management command.
Description: Create `manage.py run_daily_import` that calls fetch → parse → import/diff → match filters → queue notifications → dispatch email in sequence. Log progress at each step. Integration-test the happy path using fixture data and a stubbed email sender.

## 11. User authentication and access control
Goal: Allow users to log in/out; gate every view behind login + per-user ownership scoping.
Description: Enable Django's built-in auth views (login, logout, password change) with minimal templates and settings. Authorization is login + ownership only — no `viewer`/`manager` Groups (dropped during grooming as over-engineering; every user only ever touches their own data). Operator access = `is_staff`/admin. No self-registration for v1. See GH #11; RBAC-via-Groups parked at GH #20; test-runner gap at GH #21.

## 12. Filter profile list and create views
Goal: Let a logged-in user view and create filter profiles scoped to their account.
Description: Build a page listing the user's existing filter profiles and a form to create a new one, using Django forms and HTMX for inline feedback. Validate that at least one filter criterion is set. All querysets must filter by `request.user` — users must not be able to access any data belonging to other users, not just profiles. Test both that a user sees their own data and that direct URL access to another user's resources returns 404 (not just an empty page).

## 13. Filter profile edit and delete views
Goal: Let a user modify or remove an existing filter profile.
Description: Add edit and delete views for filter profiles, with a confirmation step for deletion. Reuse the create form for editing. All queryset lookups must use `get_object_or_404(FilterProfile, pk=pk, user=request.user)` — never fetch by PK alone — so ownership is enforced at the data layer, not just checked afterwards. Test that direct URL access to another user's profile returns 404 and that deletion also removes associated pending notifications.

## 14. Notification preference settings
Goal: Let a user configure which alert types a profile sends and how emails are bundled, with quiet defaults.
Description: Add a "Notifications" section to the #12 create/edit form exposing the preference columns already on `FilterProfile` (#6). Make `delivery` real: digest = one combined email per user, immediate = one email per listing (small seam in #9's dispatch). Defaults: new-listing alerts + digest. See GH #14.

## 15. Django admin setup
Goal: Expose key models in the Django admin for operator use.
Description: Register `Listing`, `FilterProfile`, `Notification`, `Category`, `Region` and the custom `User` with useful list display, filters and select_related. (No `Organizer`/birojs model — dropped in #3.) Add a `Notification` action that re-sends failed rows immediately via #9's dispatch. Smoke-test every admin page loads. See GH #15.

## 16. Deployment: reusable VPS setup playbook
Goal: A `deploy/` folder that stands up the app on a fresh Ubuntu VPS and is reusable for the next Django project by editing one env file.
Description: Templated shell (not Ansible — Docker comes later): `bootstrap.sh` (once), `deploy.sh` (each release), `smoke.sh`, and `envsubst` templates for Nginx + Gunicorn systemd unit. Every project-specific value lives in `deploy/app.env`. Depends on GH #22 (env-driven settings). Adds `gunicorn` (needs sign-off). See GH #16.

## 17. Deployment: scheduled daily import (systemd timer)
Goal: Run `run_daily_import` automatically once a day on the VPS with journald logs and a manual trigger.
Description: A systemd `.service` + `.timer` (templated in #16's `deploy/`), `OnCalendar=07:00 Europe/Riga`, `Persistent=true`, same `EnvironmentFile`/`User` as Gunicorn. Logs to journald (no logfile/logrotate). Verified by a manual `systemctl start` on first deploy. Chosen over cron during grooming. See GH #17.

## 22. Environment-driven settings (GH #22)
Goal: `config/settings.py` reads every environment-specific value from the process environment.
Description: Split out during #16 grooming — prerequisite for a reusable deploy and for the env vars #4/#9 already assume. `SECRET_KEY`, `DEBUG` (default False), `ALLOWED_HOSTS`, DB path, app settings from env; `.env.example` committed; no new dependency (`uv run --env-file` for local, systemd `EnvironmentFile=` for prod). See GH #22.
