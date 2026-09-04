"""Tests for :mod:`auctions.notifications` and the ``Notification`` model (#8)."""

import uuid
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import FilterProfile, User
from auctions.models import Listing, Notification
from auctions.notifications import (
    DispatchResult,
    batch_notifications,
    dispatch_pending,
    queue_notifications,
)
from auctions.tests.support import RecordingBackend


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


class DispatchPendingTest(TestCase):
    """`dispatch_pending` + `batch_notifications` (#9)."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.test", password="pw"
        )
        cls.bob = User.objects.create_user(
            "bob", email="bob@example.test", password="pw"
        )

    def _profile(self, user, name, **kwargs):
        return FilterProfile.objects.create(user=user, name=name, **kwargs)

    def _pending(self, user, *, profile=None, listing=None,
                 alert_type=Notification.AlertType.NEW, **listing_kwargs):
        if profile is None:
            profile = self._profile(user, f"profile-{Notification.objects.count()}")
        if listing is None:
            listing = _listing(**listing_kwargs)
        return Notification.objects.create(
            user=user,
            filter_profile=profile,
            listing=listing,
            alert_type=alert_type,
        )

    # --- the issue's Tests section --------------------------------------

    def test_all_digest_three_rows_two_users_two_emails_all_sent(self):
        self._pending(self.alice)
        self._pending(self.alice)
        self._pending(self.bob)

        backend = RecordingBackend()
        result = dispatch_pending(backend)

        self.assertEqual(len(backend.messages), 2)
        self.assertEqual(
            {m.to for m in backend.messages},
            {"alice@example.test", "bob@example.test"},
        )
        self.assertEqual(result, DispatchResult(emails=2, sent=3, failed=0))
        rows = Notification.objects.all()
        self.assertEqual([r.status for r in rows], ["sent"] * 3)
        self.assertTrue(all(r.sent_at is not None for r in rows))
        self.assertTrue(all(r.error == "" for r in rows))

    def test_one_failing_batch_does_not_stop_the_others(self):
        self._pending(self.alice)
        self._pending(self.bob)

        backend = RecordingBackend(fail_for={"bob@example.test"})
        result = dispatch_pending(backend)

        self.assertEqual([m.to for m in backend.messages], ["alice@example.test"])
        self.assertEqual(result, DispatchResult(emails=2, sent=1, failed=1))

        alice_row = Notification.objects.get(user=self.alice)
        self.assertEqual(alice_row.status, "sent")
        self.assertIsNotNone(alice_row.sent_at)

        bob_row = Notification.objects.get(user=self.bob)
        self.assertEqual(bob_row.status, "failed")
        self.assertIn("provider rejected bob@example.test", bob_row.error)
        self.assertIsNone(bob_row.sent_at)

    def test_one_user_two_profiles_yields_a_single_email_naming_both(self):
        p1 = self._profile(self.alice, "Riga flats")
        p2 = self._profile(self.alice, "Jurmala land")
        self._pending(self.alice, profile=p1)
        self._pending(self.alice, profile=p2, alert_type=Notification.AlertType.CHANGED)

        backend = RecordingBackend()
        dispatch_pending(backend)

        self.assertEqual(len(backend.messages), 1)
        body = backend.messages[0].body
        self.assertIn("Riga flats", body)
        self.assertIn("Jurmala land", body)
        self.assertIn("(New)", body)
        self.assertIn("(Changed)", body)

    def test_rerun_after_success_sends_nothing(self):
        self._pending(self.alice)
        dispatch_pending(RecordingBackend())

        backend = RecordingBackend()
        result = dispatch_pending(backend)

        self.assertEqual(backend.messages, [])
        self.assertEqual(result, DispatchResult(emails=0, sent=0, failed=0))

    def test_failed_row_is_reselected_and_cleared_on_the_next_run(self):
        self._pending(self.alice)
        dispatch_pending(RecordingBackend(fail_for={"alice@example.test"}))
        self.assertEqual(Notification.objects.get().status, "failed")

        backend = RecordingBackend()
        dispatch_pending(backend)

        self.assertEqual(len(backend.messages), 1)
        row = Notification.objects.get()
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.error, "")
        self.assertIsNotNone(row.sent_at)

    def test_queryset_param_scopes_dispatch_to_only_those_rows(self):
        scoped = self._pending(self.alice)
        other = self._pending(self.bob)

        backend = RecordingBackend()
        result = dispatch_pending(
            backend, queryset=Notification.objects.filter(pk=scoped.pk)
        )

        self.assertEqual(result, DispatchResult(emails=1, sent=1, failed=0))
        scoped.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(scoped.status, "sent")
        self.assertEqual(other.status, "pending")

    def test_queryset_param_is_still_filtered_to_dispatchable_statuses(self):
        failed = self._pending(self.alice)
        failed.status = Notification.Status.FAILED
        failed.save()
        already_sent = self._pending(self.alice)
        already_sent.status = Notification.Status.SENT
        already_sent.sent_at = timezone.now()
        already_sent.save()

        backend = RecordingBackend()
        result = dispatch_pending(
            backend,
            queryset=Notification.objects.filter(
                pk__in=[failed.pk, already_sent.pk]
            ),
        )

        # Only the `failed` row was dispatchable; the already-`sent` row was
        # filtered out internally and not re-sent.
        self.assertEqual(result, DispatchResult(emails=1, sent=1, failed=0))
        failed.refresh_from_db()
        self.assertEqual(failed.status, "sent")

    def test_uses_the_configured_backend_when_none_is_passed(self):
        self._pending(self.alice)
        with override_settings(
            NOTIFICATION_BACKEND="auctions.tests.support.RecordingBackend"
        ):
            result = dispatch_pending()
        self.assertEqual(result, DispatchResult(emails=1, sent=1, failed=0))
        self.assertEqual(Notification.objects.get().status, "sent")

    # --- batching seam (#14) ------------------------------------------

    def test_each_immediate_notification_is_its_own_email_digest_shares_one(self):
        imm1 = self._profile(self.alice, "i1", delivery=FilterProfile.Delivery.IMMEDIATE)
        imm2 = self._profile(self.alice, "i2", delivery=FilterProfile.Delivery.IMMEDIATE)
        dig = self._profile(self.alice, "d", delivery=FilterProfile.Delivery.DIGEST)
        self._pending(self.alice, profile=imm1)
        self._pending(self.alice, profile=imm1)
        self._pending(self.alice, profile=imm2)
        self._pending(self.alice, profile=dig)

        backend = RecordingBackend()
        result = dispatch_pending(backend)

        # 3 immediate rows = 3 emails (one per notification), + 1 shared digest.
        self.assertEqual(len(backend.messages), 4)
        self.assertEqual(result, DispatchResult(emails=4, sent=4, failed=0))

    def test_digest_profile_with_two_pending_rows_sends_one_email(self):
        dig = self._profile(self.alice, "d", delivery=FilterProfile.Delivery.DIGEST)
        self._pending(self.alice, profile=dig)
        self._pending(self.alice, profile=dig)

        backend = RecordingBackend()
        result = dispatch_pending(backend)

        self.assertEqual(len(backend.messages), 1)
        self.assertEqual(result, DispatchResult(emails=1, sent=2, failed=0))

    def test_immediate_profile_with_two_pending_rows_sends_two_emails(self):
        imm = self._profile(
            self.alice, "i", delivery=FilterProfile.Delivery.IMMEDIATE
        )
        self._pending(self.alice, profile=imm)
        self._pending(self.alice, profile=imm)

        backend = RecordingBackend()
        result = dispatch_pending(backend)

        self.assertEqual(len(backend.messages), 2)
        self.assertEqual(result, DispatchResult(emails=2, sent=2, failed=0))

    def test_null_filter_profile_row_is_batched_as_digest_for_that_user(self):
        doomed = self._profile(self.alice, "to-be-deleted")
        keep = self._profile(self.alice, "kept")
        orphan = self._pending(self.alice, profile=doomed)
        self._pending(self.alice, profile=keep)
        doomed.delete()
        orphan.refresh_from_db()
        self.assertIsNone(orphan.filter_profile)

        backend = RecordingBackend()
        dispatch_pending(backend)

        self.assertEqual(len(backend.messages), 1)
        self.assertIn("(deleted filter)", backend.messages[0].body)
        self.assertEqual(Notification.objects.filter(status="sent").count(), 2)

    def test_batch_notifications_folds_digest_per_user_splits_immediate_per_row(self):
        p_a = self._profile(self.alice, "a")
        p_b_imm = self._profile(
            self.bob, "b", delivery=FilterProfile.Delivery.IMMEDIATE
        )
        n1 = self._pending(self.alice, profile=p_a)
        n2 = self._pending(self.bob, profile=p_b_imm)
        n3 = self._pending(self.bob, profile=p_b_imm)

        rows = list(
            Notification.objects.select_related("user", "filter_profile").order_by("pk")
        )
        batches = batch_notifications(rows)

        # alice's digest row folds into one batch; each of bob's immediate rows
        # is its own batch.
        self.assertEqual(
            [[n.pk for n in b] for b in batches], [[n1.pk], [n2.pk], [n3.pk]]
        )

    def test_no_pending_rows_is_a_no_op(self):
        self.assertEqual(batch_notifications([]), [])
        result = dispatch_pending(RecordingBackend())
        self.assertEqual(result, DispatchResult(emails=0, sent=0, failed=0))

    # --- email body content -----------------------------------------

    def test_body_lists_title_price_end_time_and_link_per_listing(self):
        source_id = uuid.uuid4()
        listing = _listing(
            title="Skolas iela 1, Rīga",
            start_price="12345.67",
            source_id=source_id,
            end_time=timezone.now().replace(year=2035),
        )
        self._pending(self.alice, listing=listing)

        backend = RecordingBackend()
        dispatch_pending(backend)

        body = backend.messages[0].body
        self.assertIn("Skolas iela 1, Rīga", body)
        self.assertIn("12345.67", body)
        self.assertIn("2035", body)
        self.assertIn(
            f"https://izsoles.ta.gov.lv/izsole/{source_id}", body
        )

    def test_body_handles_untitled_listing_and_missing_price(self):
        listing = _listing(title="", start_price=None)
        self._pending(self.alice, listing=listing)

        backend = RecordingBackend()
        dispatch_pending(backend)

        body = backend.messages[0].body
        self.assertIn("(untitled listing)", body)
        self.assertIn("n/a", body)

    def test_greeting_uses_full_name_when_the_user_has_one(self):
        self.alice.first_name = "Alice"
        self.alice.last_name = "Anderson"
        self.alice.save()
        self._pending(self.alice)

        backend = RecordingBackend()
        dispatch_pending(backend)

        self.assertIn("Hi Alice Anderson,", backend.messages[0].body)

    def test_greeting_falls_back_to_username(self):
        self._pending(self.bob)

        backend = RecordingBackend()
        dispatch_pending(backend)

        self.assertIn("Hi bob,", backend.messages[0].body)
