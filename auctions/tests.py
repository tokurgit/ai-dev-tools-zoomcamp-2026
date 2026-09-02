import uuid

from django.test import SimpleTestCase, TestCase
from django.apps import apps
from django.db import IntegrityError
from django.utils import timezone

from .models import Listing


class SmokeTest(SimpleTestCase):
    def test_auctions_app_is_installed(self):
        self.assertIn('auctions', [app.name for app in apps.get_app_configs()])


class ListingModelTest(TestCase):
    UUID_1 = uuid.UUID("1e548c7f-eba4-45f4-88c2-8742f1858d87")
    UUID_2 = uuid.UUID("2411af8f-b682-40f5-bb2a-896fef94c77f")

    def _make_listing(self, **kwargs):
        defaults = dict(
            source_id=self.UUID_1,
            title="Dzīvoklis Rīgā",
            initiated_by="ZTI",
            bailiff="Jānis Bērziņš",
            start_time=timezone.now(),
            end_time=timezone.now(),
            state="apstiprināta",
            start_price="50000.00",
            bid_step="500.00",
            raw_hash="a" * 64,
        )
        defaults.update(kwargs)
        return Listing.objects.create(**defaults)

    def test_listing_can_be_saved_and_retrieved(self):
        listing = self._make_listing()
        fetched = Listing.objects.get(pk=listing.pk)
        self.assertEqual(fetched.source_id, self.UUID_1)
        self.assertEqual(fetched.title, "Dzīvoklis Rīgā")
        self.assertEqual(fetched.raw_hash, "a" * 64)

    def test_source_id_is_unique(self):
        self._make_listing(source_id=self.UUID_2)
        with self.assertRaises(IntegrityError):
            self._make_listing(source_id=self.UUID_2)

    def test_nullable_fields_accept_none(self):
        listing = self._make_listing(
            source_id=self.UUID_2,
            area=None, valuation=None, last_bid=None,
            region_id=None, category_id=None,
        )
        fetched = Listing.objects.get(pk=listing.pk)
        self.assertIsNone(fetched.area)
        self.assertIsNone(fetched.last_bid)

    def test_negative_stage_is_valid(self):
        listing = self._make_listing(source_id=self.UUID_2, stage=-1)
        self.assertEqual(Listing.objects.get(pk=listing.pk).stage, -1)
