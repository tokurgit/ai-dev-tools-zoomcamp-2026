import io
import logging
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from auctions.models import Category, Region
from auctions.reference_data import ReferenceRow, parse_reference_csv

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ParseReferenceCsvTest(SimpleTestCase):
    def test_parses_id_name_pairs(self):
        rows = list(parse_reference_csv(io.StringIO("id,name\n1,Rīga\n2,Jelgava\n")))
        self.assertEqual(rows, [ReferenceRow(1, "Rīga"), ReferenceRow(2, "Jelgava")])

    def test_accepts_any_file_like_object(self):
        # A StringIO stands in for the fetched HTTP body #4 will pass.
        stream = io.StringIO('id,name\n10,"Uzņēmums, kura sastāvā ir īpašums"\n')
        rows = list(parse_reference_csv(stream))
        self.assertEqual(rows, [ReferenceRow(10, "Uzņēmums, kura sastāvā ir īpašums")])

    def test_quoted_labels_with_commas_and_utf8_load_intact(self):
        with (FIXTURES / "kategorija_sample.csv").open(encoding="utf-8") as f:
            rows = {r.id: r.name for r in parse_reference_csv(f)}
        self.assertEqual(rows[1], "Zeme / mežs")
        self.assertEqual(rows[10], "Uzņēmums, kura sastāvā ir nekustamais īpašums")

    def test_non_contiguous_ids_load(self):
        with (FIXTURES / "kategorija_sample.csv").open(encoding="utf-8") as f:
            ids = [r.id for r in parse_reference_csv(f)]
        self.assertNotIn(7, ids)
        self.assertNotIn(9, ids)
        self.assertEqual(ids, [1, 2, 3, 4, 8, 10, 22])

    def test_malformed_rows_are_skipped_with_warning(self):
        with (FIXTURES / "kategorija_malformed.csv").open(encoding="utf-8") as f:
            with self.assertLogs("auctions.reference_data", level="WARNING") as cm:
                rows = list(parse_reference_csv(f))
        # Only the two well-formed rows survive.
        self.assertEqual(rows, [
            ReferenceRow(1, "Zeme / mežs"),
            ReferenceRow(10, "Uzņēmums, kura sastāvā ir nekustamais īpašums"),
        ])
        # blank name, blank line, wrong column count, missing id, non-integer id
        self.assertEqual(len(cm.output), 5)

    def test_empty_file_yields_nothing(self):
        with self.assertLogs("auctions.reference_data", level="WARNING"):
            self.assertEqual(list(parse_reference_csv(io.StringIO(""))), [])


class LoadReferenceDataCommandTest(TestCase):
    def _load(self, *args, **overrides):
        opts = {
            "category_csv": str(FIXTURES / "kategorija_sample.csv"),
            "region_csv": str(FIXTURES / "region_sample.csv"),
            "stdout": io.StringIO(),
        }
        opts.update(overrides)
        call_command("load_reference_data", *args, **opts)

    def test_first_load_inserts_all_rows(self):
        self._load()
        self.assertEqual(Category.objects.count(), 7)
        self.assertEqual(Region.objects.count(), 5)
        self.assertEqual(Category.objects.get(pk=10).name,
                         "Uzņēmums, kura sastāvā ir nekustamais īpašums")
        self.assertEqual(Region.objects.get(pk=120).name, "Ārzemes")

    def test_second_load_is_a_no_op_on_counts(self):
        self._load()
        self._load()
        self.assertEqual(Category.objects.count(), 7)
        self.assertEqual(Region.objects.count(), 5)

    def test_changed_label_updates_in_place(self):
        Category.objects.create(id=1, name="Stale label")
        self._load()
        cat = Category.objects.get(pk=1)
        self.assertEqual(cat.name, "Zeme / mežs")
        self.assertEqual(Category.objects.filter(pk=1).count(), 1)

    def test_id_removed_from_csv_survives_reload(self):
        # 999 is referenced by a Listing but no longer in the CSV.
        Category.objects.create(id=999, name="Retired category")
        self._load()
        self.assertTrue(Category.objects.filter(pk=999).exists())
        self.assertEqual(Category.objects.get(pk=999).name, "Retired category")

    def test_malformed_row_skipped_rest_of_load_completes(self):
        with self.assertLogs("auctions.reference_data", level="WARNING"):
            self._load(category_csv=str(FIXTURES / "kategorija_malformed.csv"))
        self.assertEqual(Category.objects.count(), 2)
        self.assertTrue(Category.objects.filter(pk=1).exists())
        self.assertTrue(Category.objects.filter(pk=10).exists())

    def test_directory_argument_uses_default_filenames(self):
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(FIXTURES / "kategorija_sample.csv", tmp / "kategorija.csv")
        shutil.copy(FIXTURES / "region_sample.csv", tmp / "region.csv")

        self._load(str(tmp), category_csv=None, region_csv=None)
        self.assertEqual(Category.objects.count(), 7)
        self.assertEqual(Region.objects.count(), 5)

    def test_missing_file_raises_command_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command(
                "load_reference_data",
                category_csv=str(FIXTURES / "does_not_exist.csv"),
                region_csv=str(FIXTURES / "region_sample.csv"),
            )

    def test_command_makes_no_network_calls(self):
        import socket
        real = socket.socket

        def no_network(*a, **k):
            raise AssertionError("network call attempted")

        socket.socket = no_network
        try:
            self._load()
        finally:
            socket.socket = real
        self.assertEqual(Category.objects.count(), 7)


class ModelTest(TestCase):
    def test_str_returns_name(self):
        self.assertEqual(str(Category(id=1, name="Māja")), "Māja")
        self.assertEqual(str(Region(id=1, name="Rīga")), "Rīga")
