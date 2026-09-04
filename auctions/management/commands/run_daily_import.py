r"""Daily pipeline orchestrator (issue #10).

``manage.py run_daily_import`` runs the whole daily izsoles.csv pipeline as one
command, calling straight into the modules the individual pipeline steps
already live in — it implements none of their logic itself:

1. **Ensure the CSV is present** at ``settings.IZSOLES_CSV_PATH`` (or
   ``--csv-path``) — the existing local file by default, or
   :func:`auctions.ingest.fetch.fetch_csv` first when ``--fetch`` is passed
   (issue #4).
2. **Parse** it with :func:`auctions.ingest.parse.parse_listings` (#4).
3. **Import/diff** the parsed records with
   :func:`auctions.ingest.importer.import_listings` (#5).
4. **Match**: for every listing in ``result.created + result.updated``, run
   :func:`auctions.matching.match_profiles` against every ``FilterProfile``,
   building the ``{listing: [profile, ...]}`` mapping step 5 expects (#7).
5. **Queue new/changed**:
   :func:`auctions.notifications.queue_notifications` (#8).
6. **Queue deadlines**:
   :func:`auctions.notifications.queue_deadline_notifications` (#19).
7. **Dispatch**: :func:`auctions.notifications.dispatch_pending` (#9), unless
   ``--no-email``.

Each step logs one ``INFO`` summary line with its counts.

Fatal path (steps 1-3)
-----------------------
Making the CSV available and parsing it (``--fetch``'s :func:`fetch_csv` and
:func:`parse_listings`) are wrapped in one ``try``/``except``: a missing file
(``parse_listings`` opens it eagerly and raises ``OSError`` — that's the "no
CSV" case, so there is no separate existence check to keep in sync) or a
failed fetch (:class:`~auctions.ingest.fetch.FetchError`) is logged at
``ERROR`` and re-raised as :class:`~django.core.management.base.CommandError`,
which Django turns into a clean non-zero exit with no traceback. Because that
happens before :func:`import_listings` is ever called, step 3 never runs on
bad input — "no partial import" on this path is simply "import never
started". ``import_listings`` itself already wraps its writes in one
``transaction.atomic()`` (#5); this command adds no further transaction around
it, since that would only duplicate protection #5 already provides.

Step-7 exit code
-----------------
``dispatch_pending()`` isolates a per-batch send failure into the returned
``DispatchResult`` rather than raising (#9) — a bad recipient must not abort
the run. But cron needs to see a partial failure, so once *every* step has
run, if ``result.failed`` is nonzero the command calls ``sys.exit(1)``. This is
deliberately not another ``CommandError``: a ``CommandError`` at that point
would misleadingly suggest the run itself failed, when steps 1-6 fully
succeeded and only some emails didn't go out — the ``ERROR`` log line already
carries the diagnostic, so a plain nonzero exit is all cron needs.

No outer transaction spans all seven steps: steps 3, 5, 6 and 7 each already
wrap their own writes (#5, #8, #9, #19), and step 7 batching one email
failure from corrupting another is the entire point of #9 — a project-wide
``transaction.atomic()`` here would contradict that by rolling every batch
back together on any single failure.
"""

import logging
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import FilterProfile
from auctions.ingest.fetch import FetchError, fetch_csv
from auctions.ingest.importer import import_listings
from auctions.ingest.parse import parse_listings
from auctions.matching import match_profiles
from auctions.notifications import (
    dispatch_pending,
    queue_deadline_notifications,
    queue_notifications,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run the daily izsoles.csv pipeline end to end: ensure the CSV is "
        "present, parse it, import/diff it, match filter profiles, queue "
        "new/changed/deadline notifications, and dispatch pending email."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fetch",
            action="store_true",
            help=(
                "Download izsoles.csv via fetch_csv() before parsing, instead "
                "of using the existing local file."
            ),
        )
        parser.add_argument(
            "--csv-path",
            default=None,
            help=(
                "Path to izsoles.csv for this run only, overriding "
                "settings.IZSOLES_CSV_PATH."
            ),
        )
        parser.add_argument(
            "--no-email",
            action="store_true",
            help="Run steps 1-6 only; skip dispatch_pending() (step 7).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Fetch/parse only and report counts; no import, no queuing, "
                "no email, no database writes."
            ),
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"] or settings.IZSOLES_CSV_PATH

        # --- steps 1-2: ensure the CSV is present, then parse it -----------
        try:
            if options["fetch"]:
                fetch_csv(dest_path=csv_path)
            parse_result = parse_listings(csv_path)
            records = list(parse_result)
        except (FetchError, OSError) as exc:
            logger.error("could not make izsoles.csv ready for import: %s", exc)
            raise CommandError(str(exc)) from exc

        logger.info(
            "parse: %d row(s) total, %d parsed, %d skipped",
            parse_result.total_rows,
            parse_result.parsed_rows,
            parse_result.skipped_rows,
        )

        if options["dry_run"]:
            logger.info(
                "dry-run: stopping after parse; no import, queuing, or email"
            )
            return

        # --- step 3: import/diff --------------------------------------------
        import_result = import_listings(records)
        logger.info(
            "import: %d created, %d updated, %d skipped (not real estate), "
            "%d skipped (pre-2026)",
            len(import_result.created),
            len(import_result.updated),
            import_result.skipped_not_real_estate,
            import_result.skipped_pre_2026,
        )

        # --- step 4: match created/updated listings against every profile --
        touched = import_result.created + import_result.updated
        profiles = list(FilterProfile.objects.all())
        matches = {listing: match_profiles(listing, profiles) for listing in touched}
        # "matches found" = number of touched listings that matched at least
        # one profile (not the total profile-listing pair count).
        matched_listings = sum(1 for hits in matches.values() if hits)
        logger.info(
            "match: %d of %d touched listing(s) matched at least one profile",
            matched_listings,
            len(touched),
        )

        # --- step 5: queue new/changed notifications ------------------------
        queued = queue_notifications(
            import_result.created, import_result.updated, matches
        )
        queued_new = sum(1 for n in queued if n.alert_type == n.AlertType.NEW)
        queued_changed = sum(
            1 for n in queued if n.alert_type == n.AlertType.CHANGED
        )
        logger.info(
            "queue: %d new, %d changed notification(s) queued",
            queued_new,
            queued_changed,
        )

        # --- step 6: queue deadline notifications ----------------------------
        deadline_queued = queue_deadline_notifications()
        logger.info(
            "queue: %d deadline notification(s) queued", len(deadline_queued)
        )

        # --- step 7: dispatch pending email -----------------------------------
        if options["no_email"]:
            logger.info("dispatch: skipped (--no-email)")
            return

        dispatch_result = dispatch_pending()
        logger.info(
            "dispatch: %d email(s) sent, %d notification(s) sent, "
            "%d notification(s) failed",
            dispatch_result.emails,
            dispatch_result.sent,
            dispatch_result.failed,
        )
        if dispatch_result.failed:
            logger.error(
                "dispatch: %d notification(s) failed to send; see Notification "
                "rows with status=failed",
                dispatch_result.failed,
            )
            sys.exit(1)
