"""Tests for the ``auctions`` admin (#15): registrations, N+1 guard, resend action."""

import uuid

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import FilterProfile
from auctions.models import Category, Listing, Notification, Region

User = get_user_model()


def _listing(**kwargs):
    defaults = dict(
        source_id=uuid.uuid4(),
        title="Dzīvoklis Rīgā",
        initiated_by="ZTI",
        start_time=timezone.now(),
        end_time=timezone.now(),
        state="apstiprināta",
        start_price="50000.00",
        raw_hash="a" * 64,
    )
    defaults.update(kwargs)
    return Listing.objects.create(**defaults)


class RegistrationTest(TestCase):
    def test_only_the_expected_auctions_models_are_registered(self):
        registered = {
            model.__name__
            for model in admin.site._registry
            if model._meta.app_label == "auctions"
        }
        # No Organizer / birojs model — it was dropped in #3.
        self.assertEqual(registered, {"Category", "Region", "Listing", "Notification"})


class AdminSmokeTest(TestCase):
    """Every registered auctions model's changelist/add/change pages load (200)."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            "admin", "admin@example.test", "pw"
        )
        cls.region = Region.objects.create(id=1, name="Rīga")
        cls.category = Category.objects.create(id=1, name="Flats")
        cls.listing = _listing(region=cls.region, category=cls.category)
        cls.user = User.objects.create_user("alice", password="pw")
        cls.profile = FilterProfile.objects.create(user=cls.user, name="p")
        cls.notification = Notification.objects.create(
            user=cls.user,
            filter_profile=cls.profile,
            listing=cls.listing,
            alert_type=Notification.AlertType.NEW,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_changelist_and_change_pages_return_200(self):
        cases = [
            ("category", self.category.pk),
            ("region", self.region.pk),
            ("listing", self.listing.pk),
            ("notification", self.notification.pk),
        ]
        for model_name, pk in cases:
            with self.subTest(model=model_name, page="changelist"):
                url = reverse(f"admin:auctions_{model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)
            with self.subTest(model=model_name, page="change"):
                url = reverse(f"admin:auctions_{model_name}_change", args=[pk])
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_page_returns_200_where_enabled(self):
        for model_name in ("category", "region", "listing"):
            with self.subTest(model=model_name):
                url = reverse(f"admin:auctions_{model_name}_add")
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_notification_add_page_is_forbidden(self):
        url = reverse("admin:auctions_notification_add")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_notification_changelist_offers_no_add_link(self):
        url = reverse("admin:auctions_notification_changelist")
        response = self.client.get(url)
        self.assertNotContains(response, "Add notification")


class ChangelistQueryCountTest(TestCase):
    """Guard against N+1 on the Listing / Notification changelists."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            "admin", "admin@example.test", "pw"
        )
        cls.region = Region.objects.create(id=1, name="Rīga")
        cls.category = Category.objects.create(id=1, name="Flats")
        cls.user = User.objects.create_user("alice", password="pw")
        cls.profile = FilterProfile.objects.create(user=cls.user, name="p")

    def setUp(self):
        self.client.force_login(self.staff)

    def _query_count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_listing_changelist_query_count_does_not_scale_with_row_count(self):
        url = reverse("admin:auctions_listing_changelist")

        _listing(region=self.region, category=self.category)
        one_row = self._query_count(url)

        for _ in range(4):
            _listing(region=self.region, category=self.category)
        five_rows = self._query_count(url)

        self.assertEqual(one_row, five_rows)
        self.assertLessEqual(five_rows, 20)

    def test_notification_changelist_query_count_does_not_scale_with_row_count(self):
        url = reverse("admin:auctions_notification_changelist")

        Notification.objects.create(
            user=self.user,
            filter_profile=self.profile,
            listing=_listing(),
            alert_type=Notification.AlertType.NEW,
        )
        one_row = self._query_count(url)

        for _ in range(4):
            Notification.objects.create(
                user=self.user,
                filter_profile=self.profile,
                listing=_listing(),
                alert_type=Notification.AlertType.NEW,
            )
        five_rows = self._query_count(url)

        self.assertEqual(one_row, five_rows)
        self.assertLessEqual(five_rows, 20)


class ResendSelectedActionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            "admin", "admin@example.test", "pw"
        )
        cls.user = User.objects.create_user(
            "alice", email="alice@example.test", password="pw"
        )
        cls.profile = FilterProfile.objects.create(user=cls.user, name="p")

    def setUp(self):
        self.client.force_login(self.staff)

    def _notification(self, status, **kwargs):
        defaults = dict(
            user=self.user,
            filter_profile=self.profile,
            listing=_listing(),
            alert_type=Notification.AlertType.NEW,
            status=status,
        )
        defaults.update(kwargs)
        return Notification.objects.create(**defaults)

    def _run_action(self, pks):
        url = reverse("admin:auctions_notification_changelist")
        data = {
            "action": "resend_selected",
            "_selected_action": [str(pk) for pk in pks],
        }
        return self.client.post(url, data, follow=True)

    @override_settings(
        NOTIFICATION_BACKEND="auctions.tests.support.RecordingBackend"
    )
    def test_failed_row_becomes_sent_with_sent_at_and_clears_error(self):
        row = self._notification(Notification.Status.FAILED, error="old error")

        response = self._run_action([row.pk])

        row.refresh_from_db()
        self.assertEqual(row.status, Notification.Status.SENT)
        self.assertIsNotNone(row.sent_at)
        self.assertEqual(row.error, "")
        self.assertContains(response, "1 resent, 0 still failing, 0 skipped")

    @override_settings(
        NOTIFICATION_BACKEND="auctions.tests.support.AlwaysFailingBackend"
    )
    def test_row_stays_failed_and_error_is_set_when_the_backend_raises(self):
        row = self._notification(Notification.Status.FAILED)

        response = self._run_action([row.pk])

        row.refresh_from_db()
        self.assertEqual(row.status, Notification.Status.FAILED)
        self.assertIn("provider unavailable", row.error)
        self.assertContains(response, "0 resent, 1 still failing, 0 skipped")

    @override_settings(
        NOTIFICATION_BACKEND="auctions.tests.support.RecordingBackend"
    )
    def test_pending_and_sent_rows_in_the_selection_are_skipped_untouched(self):
        failed = self._notification(Notification.Status.FAILED)
        pending = self._notification(Notification.Status.PENDING)
        sent = self._notification(Notification.Status.SENT, sent_at=timezone.now())

        response = self._run_action([failed.pk, pending.pk, sent.pk])

        failed.refresh_from_db()
        pending.refresh_from_db()
        sent.refresh_from_db()
        self.assertEqual(failed.status, Notification.Status.SENT)
        self.assertEqual(pending.status, Notification.Status.PENDING)
        self.assertEqual(sent.status, Notification.Status.SENT)
        self.assertContains(response, "1 resent, 0 still failing, 2 skipped")

    @override_settings(
        NOTIFICATION_BACKEND="auctions.tests.support.RecordingBackend"
    )
    def test_other_pending_rows_not_in_the_selection_are_left_alone(self):
        selected = self._notification(Notification.Status.FAILED)
        untouched = self._notification(Notification.Status.PENDING)

        self._run_action([selected.pk])

        untouched.refresh_from_db()
        self.assertEqual(untouched.status, Notification.Status.PENDING)
