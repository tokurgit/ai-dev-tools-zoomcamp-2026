"""Tests for :mod:`auctions.ingest.importer` (issue #5)."""

import csv
import io
import uuid
from unittest import mock

from django.test import TestCase

from auctions.ingest.importer import CUTOFF, import_listings
from auctions.ingest.parse import EXPECTED_COLUMNS, parse_listings
from auctions.models import Category, Listing, Region

REAL_ESTATE = "Nekustamie īpašumi"
IMPORTER_LOG = "auctions.ingest.importer"

# Stable UUIDs so a row keeps its identity across runs.
UUID_A = "1e548c7f-eba4-45f4-88c2-8742f1858d87"
UUID_B = "2411af8f-b682-40f5-bb2a-896fef94c77f"
UUID_C = "31de7869-c74b-4f0c-b196-e25a3ff8a7ea"
UUID_D = "44451c43-4ecb-47bd-b5e3-6a471a12175e"


def build_row(**overrides):
    """A syntactically valid, qualifying izsoles.csv data row as a dict."""
    row = {
        "title": "Kāda iela 1 - 2, Rīga",
        "id": str(uuid.uuid4()),
        "initiated_by": "ZTI",
        "bailiff": "Jānis Bērziņš",
        "start_time": "2026-03-01 10:00:00",
        "end_time": "2026-04-01 10:00:00",
        "state": "apstiprināta",
        "region_id": "1",
        "category_id": "3",
        "office_id": "58",
        "area": "53.42",
        "valuation": "19100",
        "start_price": "19100",
        "bid_step": "1000",
        "last_bid": "25100",
        "stage": "1",
        "type": REAL_ESTATE,
        "ownership_type": "owner",
        "usage_goal": "",
    }
    row.update(overrides)
    return row


def make_csv(rows):
    """Serialise *rows* (dicts) to a CSV file-like object the parser accepts."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPECTED_COLUMNS)
    for row in rows:
        writer.writerow([row[column] for column in EXPECTED_COLUMNS])
    buffer.seek(0)
    return buffer


def run_import(rows):
    return import_listings(parse_listings(make_csv(rows)))


class ImportListingsTest(TestCase):
    def setUp(self):
        Region.objects.create(id=1, name="Rīga")
        Category.objects.create(id=3, name="Māja")

    def test_first_run_inserts_every_qualifying_row(self):
        rows = [
            build_row(id=UUID_A),
            build_row(id=UUID_B, region_id="121", category_id="23"),
            build_row(id=UUID_C, region_id=""),
        ]

        result = run_import(rows)

        self.assertEqual({l.source_id for l in result.created},
                         {uuid.UUID(UUID_A), uuid.UUID(UUID_B), uuid.UUID(UUID_C)})
        self.assertEqual(result.updated, [])
        self.assertEqual(Listing.objects.count(), 3)

        a = Listing.objects.get(source_id=UUID_A)
        self.assertEqual(a.region_id, 1)
        self.assertEqual(a.category_id, 3)
        self.assertEqual(a.region.name, "Rīga")

    def test_unknown_and_blank_reference_codes_resolve_to_null(self):
        # Live cases from izsoles.csv 2026-09-02.
        rows = [
            build_row(id=UUID_A, region_id="121", category_id="23"),
            build_row(id=UUID_B, region_id="124", category_id="30"),
            build_row(id=UUID_C, region_id="", category_id="3"),
        ]

        result = run_import(rows)

        self.assertEqual(len(result.created), 3)
        for listing in Listing.objects.filter(source_id__in=[UUID_A, UUID_B]):
            self.assertIsNone(listing.region)
            self.assertIsNone(listing.category)
        blank = Listing.objects.get(source_id=UUID_C)
        self.assertIsNone(blank.region)
        self.assertEqual(blank.category_id, 3)

    def test_reruning_identical_csv_writes_nothing(self):
        rows = [build_row(id=UUID_A), build_row(id=UUID_B)]
        run_import(rows)
        pks = {l.source_id: l.pk for l in Listing.objects.all()}

        result = run_import(rows)

        self.assertEqual(result.created, [])
        self.assertEqual(result.updated, [])
        self.assertEqual(Listing.objects.count(), 2)
        self.assertEqual({l.source_id: l.pk for l in Listing.objects.all()}, pks)

    def test_changed_row_is_updated_in_place_and_only_in_updated(self):
        run_import([build_row(id=UUID_A, start_price="19100")])
        original = Listing.objects.get(source_id=UUID_A)

        result = run_import([build_row(id=UUID_A, start_price="18000")])

        self.assertEqual(result.created, [])
        self.assertEqual([l.source_id for l in result.updated], [uuid.UUID(UUID_A)])
        updated = Listing.objects.get(source_id=UUID_A)
        self.assertEqual(updated.pk, original.pk)
        self.assertEqual(updated.source_id, original.source_id)
        self.assertEqual(str(updated.start_price), "18000.00")
        self.assertNotEqual(updated.raw_hash, original.raw_hash)

        # ...and stays put on a third, unchanged run.
        again = run_import([build_row(id=UUID_A, start_price="18000")])
        self.assertEqual((again.created, again.updated), ([], []))

    def test_source_id_new_on_a_later_run_appears_in_created(self):
        run_import([build_row(id=UUID_A)])

        result = run_import([build_row(id=UUID_A), build_row(id=UUID_B)])

        self.assertEqual([l.source_id for l in result.created], [uuid.UUID(UUID_B)])
        self.assertEqual(result.updated, [])
        self.assertEqual(Listing.objects.count(), 2)

    def test_non_real_estate_rows_are_skipped_and_counted(self):
        result = run_import([
            build_row(id=UUID_A),
            build_row(id=UUID_B, type="Kustamā manta"),
        ])

        self.assertEqual(result.skipped_not_real_estate, 1)
        self.assertEqual(len(result.created), 1)
        self.assertFalse(Listing.objects.filter(source_id=UUID_B).exists())

    def test_pre_2026_rows_are_skipped_and_counted(self):
        result = run_import([
            build_row(id=UUID_A),
            build_row(id=UUID_B, start_time="2025-12-31 23:59:59"),
        ])

        self.assertEqual(result.skipped_pre_2026, 1)
        self.assertEqual(len(result.created), 1)
        self.assertFalse(Listing.objects.filter(source_id=UUID_B).exists())

    def test_2026_cutoff_boundary_is_inclusive(self):
        result = run_import([
            build_row(id=UUID_A, start_time="2026-01-01 00:00:00"),
        ])

        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.skipped_pre_2026, 0)

    def test_listing_absent_from_current_csv_is_left_untouched(self):
        run_import([build_row(id=UUID_A), build_row(id=UUID_B)])
        b_pk = Listing.objects.get(source_id=UUID_B).pk

        result = run_import([build_row(id=UUID_A)])

        self.assertEqual((result.created, result.updated), ([], []))
        self.assertTrue(Listing.objects.filter(pk=b_pk).exists())
        self.assertEqual(Listing.objects.count(), 2)

    def test_empty_title_is_accepted(self):
        run_import([build_row(id=UUID_A, title="")])

        self.assertEqual(Listing.objects.get(source_id=UUID_A).title, "")

    def test_office_id_is_stored_as_is(self):
        run_import([build_row(id=UUID_A, office_id="-590")])

        self.assertEqual(Listing.objects.get(source_id=UUID_A).office_id, "-590")

    def test_skip_counts_are_logged(self):
        with self.assertLogs(IMPORTER_LOG, level="INFO") as cm:
            run_import([
                build_row(id=UUID_A),
                build_row(id=UUID_B, type="Kustamā manta"),
                build_row(id=UUID_C, start_time="2020-01-01 10:00:00"),
            ])

        self.assertIn("1 created", "\n".join(cm.output))
        self.assertIn("1 skipped (not real estate)", "\n".join(cm.output))
        self.assertIn("1 skipped (pre-2026)", "\n".join(cm.output))

    def test_run_is_atomic_a_mid_run_failure_rolls_back(self):
        rows = [build_row(id=UUID_A), build_row(id=UUID_B), build_row(id=UUID_C)]
        real_save = Listing.save
        calls = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real_save(self, *args, **kwargs)

        with mock.patch.object(Listing, "save", flaky_save):
            with self.assertRaises(RuntimeError):
                run_import(rows)

        self.assertEqual(Listing.objects.count(), 0)

    def test_cutoff_constant_is_the_documented_boundary(self):
        self.assertEqual(CUTOFF.year, 2026)
        self.assertEqual((CUTOFF.month, CUTOFF.day, CUTOFF.hour, CUTOFF.minute),
                         (1, 1, 0, 0))
        self.assertEqual(CUTOFF.tzinfo.key, "Europe/Riga")
