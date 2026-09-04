"""Tests for :func:`auctions.notifications.queue_deadline_notifications` (#19)."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import FilterProfile, User
from auctions.models import Listing, Notification, Region
from auctions.notifications import queue_deadline_notifications


def _listing(**kwargs):
    defaults = dict(
        source_id=uuid.uuid4(),
        title="Dzīvoklis Rīgā",
        initiated_by="ZTI",
        bailiff="Jānis Bērziņš",
        start_time=timezone.now(),
        end_time=timezone.now() + timedelta(days=2),
        state="apstiprināta",
        start_price="50000.00",
        raw_hash="a" * 64,
    )
    defaults.update(kwargs)
    return Listing.objects.create(**defaults)


class QueueDeadlineNotificationsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")

    def _now(self):
        return timezone.now()

    def test_listing_two_days_out_with_covering_profile_creates_one_row(self):
        now = self._now()
        listing = _listing(end_time=now + timedelta(days=2))
        profile = FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=2
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(len(created), 1)
        row = Notification.objects.get()
        self.assertEqual(row.alert_type, Notification.AlertType.DEADLINE)
        self.assertEqual(row.status, Notification.Status.PENDING)
        self.assertEqual(row.user, self.user)
        self.assertEqual(row.filter_profile, profile)
        self.assertEqual(row.listing, listing)

    def test_listing_thirty_days_out_is_out_of_range_for_a_three_day_profile(self):
        now = self._now()
        _listing(end_time=now + timedelta(days=30))
        FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=3
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_listing_thirty_days_out_is_caught_by_a_thirty_day_profile(self):
        now = self._now()
        listing = _listing(end_time=now + timedelta(days=30))
        profile = FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=30
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].filter_profile, profile)
        self.assertEqual(created[0].listing, listing)

    def test_second_run_over_the_same_state_creates_no_new_rows(self):
        now = self._now()
        _listing(end_time=now + timedelta(days=2))
        FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=3
        )

        first = queue_deadline_notifications(now=now)
        second = queue_deadline_notifications(now=now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(Notification.objects.count(), 1)

    def test_notify_deadline_false_yields_no_row(self):
        now = self._now()
        _listing(end_time=now + timedelta(days=2))
        FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=False, deadline_days=3
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_listing_already_past_end_time_is_never_considered(self):
        now = self._now()
        _listing(end_time=now - timedelta(days=1))
        FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=30
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_listing_not_in_apstiprinata_state_is_never_considered(self):
        now = self._now()
        _listing(end_time=now + timedelta(days=1), state="pabeigta")
        FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=30
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_matching_still_applies_a_non_matching_region_yields_no_row(self):
        now = self._now()
        riga = Region.objects.create(id=1, name="Rīga")
        vidzeme = Region.objects.create(id=2, name="Vidzeme")
        listing = _listing(end_time=now + timedelta(days=2), region=riga)
        FilterProfile.objects.create(
            user=self.user,
            name="p",
            notify_deadline=True,
            deadline_days=3,
            criteria={"region_ids": [vidzeme.pk]},
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(created, [])
        self.assertFalse(Notification.objects.exists())

    def test_matching_region_criteria_still_yields_a_row_when_it_matches(self):
        now = self._now()
        riga = Region.objects.create(id=1, name="Rīga")
        listing = _listing(end_time=now + timedelta(days=2), region=riga)
        profile = FilterProfile.objects.create(
            user=self.user,
            name="p",
            notify_deadline=True,
            deadline_days=3,
            criteria={"region_ids": [riga.pk]},
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].filter_profile, profile)
        self.assertEqual(created[0].listing, listing)

    def test_fractional_days_round_up_two_point_five_days_needs_deadline_days_three(self):
        now = self._now()
        listing = _listing(end_time=now + timedelta(days=2, hours=12))
        short_profile = FilterProfile.objects.create(
            user=self.user, name="short", notify_deadline=True, deadline_days=2
        )
        covering_profile = FilterProfile.objects.create(
            user=self.user, name="covering", notify_deadline=True, deadline_days=3
        )

        created = queue_deadline_notifications(now=now)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].filter_profile, covering_profile)

    def test_default_now_is_used_when_omitted(self):
        _listing(end_time=timezone.now() + timedelta(days=1))
        FilterProfile.objects.create(
            user=self.user, name="p", notify_deadline=True, deadline_days=3
        )

        created = queue_deadline_notifications()

        self.assertEqual(len(created), 1)

    def test_no_eligible_listings_or_profiles_returns_an_empty_list(self):
        self.assertEqual(queue_deadline_notifications(now=self._now()), [])
        self.assertFalse(Notification.objects.exists())
