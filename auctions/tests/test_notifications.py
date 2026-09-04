"""Tests for :mod:`auctions.notifications` and the ``Notification`` model (#8)."""

import uuid
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import FilterProfile, User
from auctions.models import Listing, Notification
from auctions.notifications import queue_notifications


def _listing(**kwargs):
    defaults = dict(
        source_id=uuid.uuid4(),
        title="Dzīvoklis Rīgā",
        initiated_by="ZTI",
        bailiff="Jānis Bērziņš",
        start_time=timezone.now(),
        end_time=timezone.now(),
        state="apstiprināta",
        start_price="50000.00",
        raw_hash="a" * 64,
    )
    defaults.update(kwargs)
    return Listing.objects.create(**defaults)


class QueueNotificationsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")

    def _profile(self, name="p", **kwargs):
        return FilterProfile.objects.create(user=self.user, name=name, **kwargs)

    def test_match_creates_one_pending_row_with_alert_type_and_user(self):
        listing = _listing()
        profile = self._profile(notify_new=True)

        created = queue_notifications([listing], [], {listing: [profile]})

        self.assertEqual(len(created), 1)
        row = Notification.objects.get()
        self.assertEqual(row.alert_type, Notification.AlertType.NEW)
        self.assertEqual(row.status, Notification.Status.PENDING)
        self.assertEqual(row.user, self.user)
        self.assertEqual(row.filter_profile, profile)
        self.assertEqual(row.listing, listing)
        self.assertIsNone(row.sent_at)
        self.assertEqual(row.error, "")

    def test_return_value_is_the_list_of_created_notifications(self):
        listing = _listing()
        profile = self._profile(notify_new=True)

        created = queue_notifications([listing], [], {listing: [profile]})

        self.assertIsInstance(created, list)
        self.assertEqual(created, list(Notification.objects.all()))
        self.assertTrue(all(isinstance(n, Notification) for n in created))

    def test_updated_listing_creates_a_changed_row_when_notify_change(self):
        listing = _listing()
        profile = self._profile(notify_change=True)

        created = queue_notifications([], [listing], {listing: [profile]})

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].alert_type, Notification.AlertType.CHANGED)

    def test_running_twice_over_the_same_input_creates_rows_only_once(self):
        listing = _listing()
        profile = self._profile(notify_new=True, notify_change=True)
        matches = {listing: [profile]}

        first = queue_notifications([listing], [listing], matches)
        second = queue_notifications([listing], [listing], matches)

        self.assertEqual(len(first), 2)
        self.assertEqual(second, [])
        self.assertEqual(Notification.objects.count(), 2)

    def test_existing_notification_of_any_status_blocks_a_requeue(self):
        listing = _listing()
        profile = self._profile(notify_new=True)
        Notification.objects.create(
            user=self.user,
            filter_profile=profile,
            listing=listing,
            alert_type=Notification.AlertType.NEW,
            status=Notification.Status.SENT,
        )

        created = queue_notifications([listing], [], {listing: [profile]})

        self.assertEqual(created, [])
        self.assertEqual(Notification.objects.count(), 1)

    def test_notify_new_false_yields_no_new_row(self):
        listing = _listing()
        profile = self._profile(notify_new=False)

        created = queue_notifications([listing], [], {listing: [profile]})

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_notify_change_false_yields_no_changed_row(self):
        listing = _listing()
        profile = self._profile(notify_change=False)

        created = queue_notifications([], [listing], {listing: [profile]})

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_listing_in_created_and_updated_makes_no_two_rows_of_a_type(self):
        listing = _listing()
        profile = self._profile(notify_new=True, notify_change=True)

        created = queue_notifications([listing], [listing], {listing: [profile]})

        self.assertEqual(len(created), 2)
        by_type = sorted(n.alert_type for n in created)
        self.assertEqual(by_type, ["changed", "new"])
        self.assertEqual(
            Notification.objects.filter(alert_type="new").count(), 1
        )
        self.assertEqual(
            Notification.objects.filter(alert_type="changed").count(), 1
        )

    def test_same_listing_twice_in_one_list_is_deduped_within_the_run(self):
        listing = _listing()
        profile = self._profile(notify_new=True)

        created = queue_notifications(
            [listing, listing], [], {listing: [profile]}
        )

        self.assertEqual(len(created), 1)

    def test_user_is_denormalised_from_the_profile_not_the_caller(self):
        bob = User.objects.create_user("bob", password="pw")
        listing = _listing()
        profile = FilterProfile.objects.create(
            user=bob, name="bobs", notify_new=True
        )

        created = queue_notifications([listing], [], {listing: [profile]})

        self.assertEqual(created[0].user, bob)

    def test_listing_with_no_matching_profiles_creates_nothing(self):
        listing = _listing()

        created = queue_notifications([listing], [], {})

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_empty_inputs_return_an_empty_list(self):
        self.assertEqual(queue_notifications([], [], {}), [])
        self.assertFalse(Notification.objects.exists())

    def test_multiple_profiles_and_listings_are_all_queued(self):
        l1, l2 = _listing(), _listing()
        p1 = self._profile("p1", notify_new=True)
        p2 = self._profile("p2", notify_new=True, notify_change=True)

        created = queue_notifications(
            [l1], [l2], {l1: [p1, p2], l2: [p2]}
        )

        self.assertEqual(len(created), 3)
        self.assertEqual(
            {(n.listing_id, n.filter_profile_id, n.alert_type) for n in created},
            {
                (l1.pk, p1.pk, "new"),
                (l1.pk, p2.pk, "new"),
                (l2.pk, p2.pk, "changed"),
            },
        )

    def test_insert_is_atomic_a_mid_batch_failure_rolls_back(self):
        listing = _listing()
        profile = self._profile(notify_new=True)
        real_bulk_create = Notification.objects.bulk_create

        def flaky_bulk_create(objs, *args, **kwargs):
            real_bulk_create(objs[:1])
            raise RuntimeError("boom")

        with mock.patch.object(
            Notification.objects, "bulk_create", flaky_bulk_create
        ):
            with self.assertRaises(RuntimeError):
                queue_notifications([listing], [], {listing: [profile]})

        self.assertEqual(Notification.objects.count(), 0)


class NotificationModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("carol", password="pw")

    def _row(self, **kwargs):
        listing = _listing()
        profile = FilterProfile.objects.create(user=self.user, name="p")
        defaults = dict(
            user=self.user,
            filter_profile=profile,
            listing=listing,
            alert_type=Notification.AlertType.NEW,
        )
        defaults.update(kwargs)
        return Notification.objects.create(**defaults)

    def test_defaults_are_pending_blank_error_and_null_sent_at(self):
        row = self._row()
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.error, "")
        self.assertIsNone(row.sent_at)
        self.assertIsNotNone(row.created_at)

    def test_str_mentions_user_alert_type_and_listing(self):
        row = self._row()
        self.assertEqual(
            str(row), f"{self.user} · new · {row.listing_id}"
        )

    def test_unique_constraint_on_profile_listing_alert_type(self):
        row = self._row()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Notification.objects.create(
                    user=self.user,
                    filter_profile=row.filter_profile,
                    listing=row.listing,
                    alert_type=Notification.AlertType.NEW,
                )

    def test_deleting_the_profile_nulls_filter_profile_and_keeps_the_row(self):
        row = self._row()
        row.filter_profile.delete()
        row.refresh_from_db()
        self.assertIsNone(row.filter_profile)
        self.assertEqual(row.user, self.user)
        self.assertTrue(Notification.objects.filter(pk=row.pk).exists())

    def test_deleting_the_user_cascades(self):
        row = self._row()
        row.user.delete()
        self.assertFalse(Notification.objects.filter(pk=row.pk).exists())

    def test_deleting_the_listing_cascades(self):
        row = self._row()
        row.listing.delete()
        self.assertFalse(Notification.objects.filter(pk=row.pk).exists())
