"""Integration tests for ``manage.py run_daily_import`` (issue #10).

Drives the whole command through :func:`django.core.management.call_command`
against the shared ``izsoles_sample.csv`` fixture (also used by #4/#5's own
tests) with a seeded, matching :class:`~accounts.models.FilterProfile`, and a
stub email backend.

Fixture shape (see ``auctions/tests/test_ingest.py`` /
``auctions/tests/test_importer.py`` for the same numbers derived independently):
11 data rows, 7 parse cleanly, 4 are malformed and skipped by the parser. Of
the 7 clean rows, 1 is not real estate (``Kustamā manta``), so 6 qualify and
are imported; all 6 have a 2026 ``start_time`` so none is cut by the pre-2026
filter. Of those 6, 4 carry ``region_id == 7``: "Maltas iela 21 - 74, Rīga",
"Bez cenām, Rīga", "Rusova iela 32 - 12,\\nRīga", and the very long ("ĀĀĀ...")
title row.
"""

from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import FilterProfile, User
from auctions.ingest.fetch import FetchError
from auctions.models import Category, Listing, Notification, Region

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "izsoles_sample.csv"

COMMAND_MODULE = "auctions.management.commands.run_daily_import"
COMMAND_LOG = COMMAND_MODULE


class _CapturingBackend:
    """``NOTIFICATION_BACKEND`` stub that records sends at the class level.

    ``auctions.email.get_backend`` instantiates the backend fresh from a
    dotted path for every ``dispatch_pending()`` call (there is no live
    instance for the test to hold a reference to), so this records onto the
    *class* rather than ``self`` — the only way a test can inspect what a
    settings-resolved backend actually sent. Reset in ``setUp``.
    """

    sent = []

    def send(self, to, subject, body):
        type(self).sent.append((to, subject, body))


def _run(**options):
    options.setdefault("csv_path", str(SAMPLE))
    call_command("run_daily_import", **options)


@override_settings(
    NOTIFICATION_BACKEND=f"{__name__}._CapturingBackend"
)
class RunDailyImportTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", email="alice@example.test", password="pw"
        )
        Region.objects.create(id=7, name="Rīga")
        Category.objects.create(id=3, name="Dzīvokļi")

    def setUp(self):
        _CapturingBackend.sent = []

    def _profile(self, **kwargs):
        kwargs.setdefault("notify_new", True)
        kwargs.setdefault("delivery", FilterProfile.Delivery.IMMEDIATE)
        kwargs.setdefault("criteria", {"region_ids": [7]})
        return FilterProfile.objects.create(user=self.user, name="p", **kwargs)

    # --- happy path ------------------------------------------------------

    def test_happy_path_imports_matches_queues_and_sends(self):
        profile = self._profile()

        with self.assertLogs(COMMAND_LOG, level="INFO") as cm:
            _run()

        log_text = "\n".join(cm.output)
        self.assertIn("parse:", log_text)
        self.assertIn("import: 6 created", log_text)
        self.assertIn("match:", log_text)
        self.assertIn("queue: 4 new", log_text)
        self.assertIn("queue: 0 deadline", log_text)
        self.assertIn("dispatch:", log_text)

        self.assertEqual(Listing.objects.count(), 6)

        notes = Notification.objects.filter(filter_profile=profile)
        self.assertEqual(notes.count(), 4)
        self.assertTrue(
            all(n.status == Notification.Status.SENT for n in notes),
            [n.status for n in notes],
        )
        self.assertTrue(all(n.alert_type == Notification.AlertType.NEW for n in notes))

        # One immediate-delivery notification == one email each.
        self.assertEqual(len(_CapturingBackend.sent), 4)
        to, subject, body = _CapturingBackend.sent[0]
        self.assertEqual(to, "alice@example.test")
        self.assertIn("1 auction alert", subject)
        self.assertIn("Rīga", body)

    def test_second_invocation_on_unchanged_csv_is_a_clean_no_op(self):
        self._profile()
        _run()
        _CapturingBackend.sent = []

        with self.assertLogs(COMMAND_LOG, level="INFO") as cm:
            _run()

        log_text = "\n".join(cm.output)
        self.assertIn("import: 0 created, 0 updated", log_text)
        self.assertIn("queue: 0 new, 0 changed", log_text)
        self.assertIn("dispatch: 0 email(s) sent, 0 notification(s) sent, "
                       "0 notification(s) failed", log_text)

        self.assertEqual(Listing.objects.count(), 6)
        self.assertEqual(Notification.objects.count(), 4)
        self.assertEqual(_CapturingBackend.sent, [])

    # --- --no-email --------------------------------------------------------

    def test_no_email_queues_but_never_calls_dispatch(self):
        profile = self._profile()

        with mock.patch(f"{COMMAND_MODULE}.dispatch_pending") as dispatch_mock:
            _run(no_email=True)

        dispatch_mock.assert_not_called()
        notes = Notification.objects.filter(filter_profile=profile)
        self.assertEqual(notes.count(), 4)
        self.assertTrue(
            all(n.status == Notification.Status.PENDING for n in notes)
        )
        self.assertEqual(_CapturingBackend.sent, [])

    # --- --dry-run -----------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        self._profile()

        with self.assertLogs(COMMAND_LOG, level="INFO") as cm:
            _run(dry_run=True)

        self.assertTrue(any("dry-run" in line for line in cm.output))
        self.assertEqual(Listing.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(_CapturingBackend.sent, [])

    # --- --fetch -------------------------------------------------------------

    def test_fetch_flag_calls_fetch_csv_before_parsing(self):
        dest = FIXTURES / "_fetched_izsoles.csv.tmp"
        self.addCleanup(lambda: dest.unlink(missing_ok=True))

        def fake_fetch(dest_path=None, **kwargs):
            path = Path(dest_path)
            path.write_bytes(SAMPLE.read_bytes())
            return path

        with mock.patch(
            f"{COMMAND_MODULE}.fetch_csv", side_effect=fake_fetch
        ) as fetch_mock:
            _run(fetch=True, csv_path=str(dest))

        fetch_mock.assert_called_once_with(dest_path=str(dest))
        self.assertEqual(Listing.objects.count(), 6)

    def test_fetch_flag_failure_is_fatal_and_aborts(self):
        with mock.patch(
            f"{COMMAND_MODULE}.fetch_csv", side_effect=FetchError("boom")
        ):
            with self.assertLogs(COMMAND_LOG, level="ERROR"):
                with self.assertRaises(CommandError):
                    _run(fetch=True)

        self.assertEqual(Listing.objects.count(), 0)

    # --- fatal path: missing CSV --------------------------------------------

    def test_missing_csv_path_aborts_with_command_error_no_listings(self):
        missing = str(FIXTURES / "does_not_exist.csv")

        with self.assertLogs(COMMAND_LOG, level="ERROR"):
            with self.assertRaises(CommandError):
                _run(csv_path=missing)

        self.assertEqual(Listing.objects.count(), 0)

    # --- step 7 partial failure --------------------------------------------

    @override_settings(
        NOTIFICATION_BACKEND="auctions.tests.support.AlwaysFailingBackend"
    )
    def test_email_failure_exits_non_zero_but_keeps_earlier_steps(self):
        profile = self._profile()

        with self.assertLogs(COMMAND_LOG, level="ERROR"):
            with self.assertRaises(SystemExit) as cm:
                _run()

        self.assertEqual(cm.exception.code, 1)

        # Steps 1-6 (import + queue) succeeded even though step 7 failed.
        self.assertEqual(Listing.objects.count(), 6)
        notes = Notification.objects.filter(filter_profile=profile)
        self.assertEqual(notes.count(), 4)
        self.assertTrue(
            all(n.status == Notification.Status.FAILED for n in notes),
            [n.status for n in notes],
        )
