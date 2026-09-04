r"""Persist parsed ``izsoles.csv`` records into :class:`~auctions.models.Listing`
rows and report which listings are new and which changed (issue #5).

``import_listings`` consumes the iterable of record dicts produced by
:func:`auctions.ingest.parse.parse_listings`, filters it to the listings this
project cares about, upserts the survivors keyed on ``Listing.source_id`` and
returns an :class:`ImportResult` carrying:

* ``created`` — :class:`Listing` objects inserted on this run,
* ``updated`` — existing :class:`Listing` objects whose stored ``raw_hash`` no
  longer matched the incoming row (updated in place; same ``pk`` / ``source_id``),
* ``skipped_not_real_estate`` / ``skipped_pre_2026`` — counts of rows dropped by
  the two filters (also logged at ``INFO``).

Module name
-----------
Issue #5 suggests ``auctions/ingest/import.py``, but ``import`` is a Python
keyword and the module could never be imported — this file is ``importer.py``
instead.

Filtering
---------
* Rows whose ``type`` is not ``"Nekustamie īpašumi"`` are skipped.
* Rows whose ``start_time`` is before ``2026-01-01 00:00 Europe/Riga`` are
  skipped. The boundary is inclusive: ``start_time >= 2026-01-01 00:00
  Europe/Riga`` qualifies.

A skipped row never creates or updates a ``Listing``.

Reference codes
---------------
The parser yields ``region_id`` / ``category_id`` as ``int`` / ``None``. This
module resolves each code to the matching :class:`~auctions.models.Region` /
:class:`~auctions.models.Category` primary key; a code with no matching
reference row (or a blank one) stores ``NULL`` for that FK and does not raise.
``office_id`` has no reference model and is stored as-is.

Change detection
----------------
``raw_hash`` (defined in :mod:`auctions.ingest.parse`) is the only change key:
an incoming row whose hash equals the stored one is left completely untouched
(no write), so re-importing an unchanged CSV produces two empty lists.

Consistency
-----------
All writes for one run happen inside a single ``transaction.atomic`` block; an
abort mid-run leaves the table as it was before the run.

Out of scope (see issue #5): listings that disappear from the feed are left
untouched — never deleted, never flagged.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction

from auctions.models import Category, Listing, Region

logger = logging.getLogger(__name__)

#: Only real-estate auctions are imported (``type`` column value).
REAL_ESTATE_TYPE = "Nekustamie īpašumi"

#: Auctions starting before this instant are ignored (inclusive lower bound).
CUTOFF = datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("Europe/Riga"))

#: Record keys copied verbatim onto a ``Listing`` (``source_id``, the reference
#: FKs and ``raw_hash`` are handled separately).
_COPY_FIELDS = (
    "title", "initiated_by", "bailiff", "start_time", "end_time", "state",
    "office_id", "area", "valuation", "start_price", "bid_step", "last_bid",
    "stage", "type", "ownership_type",
)


@dataclass
class ImportResult:
    """Outcome of one :func:`import_listings` run."""

    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    skipped_not_real_estate: int = 0
    skipped_pre_2026: int = 0


def import_listings(records):
    """Upsert *records* into ``Listing`` and return an :class:`ImportResult`."""
    result = ImportResult()
    qualifying = []
    for record in records:
        if record["type"] != REAL_ESTATE_TYPE:
            result.skipped_not_real_estate += 1
            continue
        if record["start_time"] < CUTOFF:
            result.skipped_pre_2026 += 1
            continue
        qualifying.append(record)

    region_ids = set(Region.objects.values_list("pk", flat=True))
    category_ids = set(Category.objects.values_list("pk", flat=True))
    existing = Listing.objects.in_bulk(
        [record["source_id"] for record in qualifying], field_name="source_id"
    )

    with transaction.atomic():
        for record in qualifying:
            listing = existing.get(record["source_id"])
            if listing is None:
                listing = Listing(source_id=record["source_id"])
                _apply(listing, record, region_ids, category_ids)
                listing.save()
                result.created.append(listing)
            elif listing.raw_hash != record["raw_hash"]:
                _apply(listing, record, region_ids, category_ids)
                listing.save()
                result.updated.append(listing)

    logger.info(
        "import_listings: %d created, %d updated, %d skipped (not real estate), "
        "%d skipped (pre-2026)",
        len(result.created), len(result.updated),
        result.skipped_not_real_estate, result.skipped_pre_2026,
    )
    return result


def _apply(listing, record, region_ids, category_ids):
    """Copy *record* onto *listing*, resolving the reference-code FKs."""
    for name in _COPY_FIELDS:
        setattr(listing, name, record[name])
    region_code = record["region_id"]
    listing.region_id = region_code if region_code in region_ids else None
    category_code = record["category_id"]
    listing.category_id = (
        category_code if category_code in category_ids else None
    )
    listing.raw_hash = record["raw_hash"]
