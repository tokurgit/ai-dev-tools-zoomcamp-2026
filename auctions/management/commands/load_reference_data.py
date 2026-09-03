"""(Re)load the ``Category`` and ``Region`` lookup tables from the reference CSVs.

Idempotent: keyed on the CSV ``id`` via ``update_or_create``. Re-running updates
changed labels in place and never deletes rows whose ``id`` has dropped out of
the CSV (a ``Listing`` may still reference them). Makes no network calls.

Default source is the ``data/`` directory at the repo root, expecting
``kategorija.csv`` and ``region.csv`` (see ``data/README.md``).
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from auctions.models import Category, Region
from auctions.reference_data import parse_reference_csv

DEFAULT_DIR = Path(settings.BASE_DIR) / "data"
CATEGORY_FILENAME = "kategorija.csv"
REGION_FILENAME = "region.csv"


class Command(BaseCommand):
    help = (
        "Load the Category and Region lookup tables from kategorija.csv and "
        "region.csv. Idempotent; makes no network calls."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            nargs="?",
            default=str(DEFAULT_DIR),
            help=(
                "Directory holding kategorija.csv and region.csv "
                f"(default: {DEFAULT_DIR})."
            ),
        )
        parser.add_argument(
            "--category-csv",
            help="Path to the category CSV, overriding <source>/kategorija.csv.",
        )
        parser.add_argument(
            "--region-csv",
            help="Path to the region CSV, overriding <source>/region.csv.",
        )

    def handle(self, *args, **options):
        source = Path(options["source"])
        category_csv = Path(options["category_csv"]) if options["category_csv"] else source / CATEGORY_FILENAME
        region_csv = Path(options["region_csv"]) if options["region_csv"] else source / REGION_FILENAME

        for label, path in (("category", category_csv), ("region", region_csv)):
            if not path.is_file():
                raise CommandError(f"{label} CSV not found: {path}")

        created, updated = self._load(Category, category_csv)
        self.stdout.write(
            self.style.SUCCESS(f"Category: {created} created, {updated} updated")
        )
        created, updated = self._load(Region, region_csv)
        self.stdout.write(
            self.style.SUCCESS(f"Region: {created} created, {updated} updated")
        )

    @transaction.atomic
    def _load(self, model, path):
        created = updated = 0
        with path.open(encoding="utf-8", newline="") as fileobj:
            for row in parse_reference_csv(fileobj):
                _, was_created = model.objects.update_or_create(
                    id=row.id, defaults={"name": row.name}
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
        return created, updated
