import datetime
import uuid

from django.test import SimpleTestCase, TestCase
from django.apps import apps
from django.db import IntegrityError, models
from django.utils import timezone

from auctions.models import Category, Listing, Region


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
            region=None, category=None,
        )
        fetched = Listing.objects.get(pk=listing.pk)
        self.assertIsNone(fetched.area)
        self.assertIsNone(fetched.last_bid)
        self.assertIsNone(fetched.region)
        self.assertIsNone(fetched.category)

    def test_negative_stage_is_valid(self):
        listing = self._make_listing(source_id=self.UUID_2, stage=-1)
        self.assertEqual(Listing.objects.get(pk=listing.pk).stage, -1)

    def test_str_includes_source_id_and_title(self):
        listing = Listing(source_id=self.UUID_1, title="Dzīvoklis Rīgā")
        self.assertEqual(str(listing), f"{self.UUID_1}: Dzīvoklis Rīgā")

    def test_meta_ordering_is_most_recent_end_time_first(self):
        older = self._make_listing(
            source_id=self.UUID_1,
            end_time=timezone.now() - datetime.timedelta(days=1),
        )
        newer = self._make_listing(
            source_id=self.UUID_2,
            end_time=timezone.now() + datetime.timedelta(days=1),
        )
        self.assertEqual(list(Listing.objects.all()), [newer, older])


class ListingReferenceForeignKeyTest(TestCase):
    """#18 — region / category are SET_NULL ForeignKeys to the lookup tables."""

    UUID_1 = uuid.UUID("1e548c7f-eba4-45f4-88c2-8742f1858d87")

    def _make_listing(self, **kwargs):
        defaults = dict(
            source_id=self.UUID_1,
            title="Dzīvoklis Rīgā",
            initiated_by="ZTI",
            start_time=timezone.now(),
            end_time=timezone.now(),
            state="apstiprināta",
            raw_hash="a" * 64,
        )
        defaults.update(kwargs)
        return Listing.objects.create(**defaults)

    def test_region_and_category_are_nullable_set_null_foreign_keys(self):
        for name, target in (("region", Region), ("category", Category)):
            field = Listing._meta.get_field(name)
            self.assertIsInstance(field, models.ForeignKey)
            self.assertIs(field.related_model, target)
            self.assertTrue(field.null)
            self.assertTrue(field.blank)
            self.assertIs(field.remote_field.on_delete, models.SET_NULL)

    def test_deleting_region_nulls_the_fk_and_keeps_the_listing(self):
        region = Region.objects.create(id=1, name="Rīga")
        listing = self._make_listing(region=region)

        region.delete()

        listing.refresh_from_db()
        self.assertIsNone(listing.region)
        self.assertTrue(Listing.objects.filter(pk=listing.pk).exists())

    def test_deleting_category_nulls_the_fk_and_keeps_the_listing(self):
        category = Category.objects.create(id=7, name="Dzīvoklis")
        listing = self._make_listing(category=category)

        category.delete()

        listing.refresh_from_db()
        self.assertIsNone(listing.category)
        self.assertTrue(Listing.objects.filter(pk=listing.pk).exists())

    def test_select_related_traverses_to_the_label(self):
        region = Region.objects.create(id=2, name="Kurzeme")
        category = Category.objects.create(id=3, name="Zeme")
        self._make_listing(region=region, category=category)

        fetched = Listing.objects.select_related("region", "category").get(
            source_id=self.UUID_1
        )
        self.assertEqual(fetched.region.name, "Kurzeme")
        self.assertEqual(fetched.category.name, "Zeme")
