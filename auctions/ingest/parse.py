r"""Parse a local ``izsoles.csv`` into :class:`~auctions.models.Listing` records.

An operator drops the daily ``izsoles.csv`` at ``settings.IZSOLES_CSV_PATH``
(see :mod:`auctions.ingest.fetch` for the optional HTTP refresh). This module
turns that file into an iterator of validated ``dict`` records — one per data
row — keyed by ``Listing`` field names, ready for the importer (issue #5) to
persist. **No filtering happens here** (real-estate-only / 2026-onwards is #5's
job); every parseable row is yielded.

Usage::

    result = parse_listings(path_or_fileobj)
    for record in result:
        ...
    print(result.skipped_rows, "rows skipped")

``parse_listings`` accepts a filesystem path (``str`` / ``os.PathLike``) or any
text- or binary-mode file-like object.

Column mapping
--------------
The live feed has 19 columns (verified 2026-09-02)::

    title,id,initiated_by,bailiff,start_time,end_time,state,region_id,
    category_id,office_id,area,valuation,start_price,bid_step,last_bid,stage,
    type,ownership_type,usage_goal

* CSV ``id`` -> ``source_id``, parsed to a :class:`uuid.UUID`. A row whose
  ``id`` is empty or unparseable is skipped and counted.
* ``usage_goal`` is dropped (100% empty in the live feed).
* ``start_time`` / ``end_time`` (``"YYYY-MM-DD HH:MM:SS"``, naive) are read as
  **Europe/Riga** local time and returned as timezone-aware datetimes.
* ``region_id`` / ``category_id`` -> ``int`` or ``None`` when blank.
* ``stage`` -> ``int`` or ``None`` when blank (negative values like ``-1`` are
  preserved).
* ``area`` / ``valuation`` / ``start_price`` / ``bid_step`` / ``last_bid`` ->
  :class:`decimal.Decimal` or ``None`` when blank.
* ``office_id`` -> stripped ``str`` (the feed has integer and negative values).
* ``title`` longer than 500 chars is truncated to 500; an empty ``title`` is
  passed through as ``""``.

``raw_hash``
-----------
Every record carries a ``raw_hash``: the SHA-256 hex digest of the row's raw
field values, in CSV column order (all 19), joined by a ``\x1f`` (unit
separator) byte and encoded as UTF-8. The importer (#5) and the change-detector
(#2) compare against this exact definition — do not change it without updating
both.

Robustness
----------
Parsing uses the :mod:`csv` module, so embedded newlines inside quoted fields
(live titles contain them) are handled. The file is read as UTF-8; undecodable
bytes are replaced and any row that then contains a replacement character is
treated as malformed. A malformed row (wrong column count, undecodable bytes,
an unparseable number or datetime) is skipped, logged at ``WARNING`` with its
data-row number, and does not abort the parse.
"""

import csv
import io
import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

#: CSV columns in the exact order the live feed emits them (verified 2026-09-02).
EXPECTED_COLUMNS = [
    "title", "id", "initiated_by", "bailiff", "start_time", "end_time", "state",
    "region_id", "category_id", "office_id", "area", "valuation", "start_price",
    "bid_step", "last_bid", "stage", "type", "ownership_type", "usage_goal",
]

#: Separator used when building the ``raw_hash`` pre-image (ASCII unit separator).
RAW_HASH_SEPARATOR = "\x1f"

_TITLE_MAX_LENGTH = 500
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_RIGA = ZoneInfo("Europe/Riga")
_REPLACEMENT_CHAR = "�"


class ParseResult:
    """Iterator of record dicts that also tallies rows seen / parsed / skipped.

    Iterate it to consume the records; read :attr:`skipped_rows` (and the
    siblings) once iteration is finished.
    """

    def __init__(self, rows):
        self._rows = rows
        self.total_rows = 0
        self.parsed_rows = 0
        self.skipped_rows = 0

    def __iter__(self):
        for rownum, values in self._rows:
            self.total_rows += 1
            record = _parse_row(rownum, values)
            if record is None:
                self.skipped_rows += 1
                continue
            self.parsed_rows += 1
            yield record


def parse_listings(source):
    """Return a :class:`ParseResult` over the data rows of *source*.

    *source* is a filesystem path (``str`` / ``os.PathLike``) or any text- or
    binary-mode file-like object.
    """
    return ParseResult(_iter_rows(_load_text(source)))


def raw_hash(values):
    """SHA-256 hex digest of *values* joined per the ``raw_hash`` definition."""
    pre_image = RAW_HASH_SEPARATOR.join(values).encode("utf-8")
    return sha256(pre_image).hexdigest()


def _load_text(source):
    """Read *source* fully and return its decoded text (UTF-8, errors replaced)."""
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as handle:
            return handle.read().decode("utf-8", errors="replace")
    data = source.read()
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _iter_rows(text):
    """Yield ``(rownum, values)`` for each CSV data row (header consumed)."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        logger.warning("izsoles.csv is empty")
        return
    if header != EXPECTED_COLUMNS:
        logger.warning("unexpected izsoles.csv header: %r", header)
    for rownum, values in enumerate(reader, start=1):
        yield rownum, values


def _parse_row(rownum, values):
    """Return a record dict for one row, or ``None`` if the row is malformed."""
    if len(values) != len(EXPECTED_COLUMNS):
        logger.warning(
            "row %d: expected %d columns, got %d, skipping row",
            rownum, len(EXPECTED_COLUMNS), len(values),
        )
        return None
    if any(_REPLACEMENT_CHAR in value for value in values):
        logger.warning("row %d: undecodable bytes, skipping row", rownum)
        return None

    row = dict(zip(EXPECTED_COLUMNS, values))

    raw_id = row["id"].strip()
    try:
        source_id = uuid.UUID(raw_id)
    except ValueError:
        logger.warning(
            "row %d: unparseable id %r, skipping row", rownum, raw_id
        )
        return None

    try:
        record = {
            "source_id": source_id,
            "title": _truncate(row["title"]),
            "initiated_by": row["initiated_by"],
            "bailiff": row["bailiff"],
            "start_time": _parse_datetime(row["start_time"]),
            "end_time": _parse_datetime(row["end_time"]),
            "state": row["state"],
            "region_id": _int_or_none(row["region_id"]),
            "category_id": _int_or_none(row["category_id"]),
            "office_id": row["office_id"].strip(),
            "area": _decimal_or_none(row["area"]),
            "valuation": _decimal_or_none(row["valuation"]),
            "start_price": _decimal_or_none(row["start_price"]),
            "bid_step": _decimal_or_none(row["bid_step"]),
            "last_bid": _decimal_or_none(row["last_bid"]),
            "stage": _int_or_none(row["stage"]),
            "type": row["type"],
            "ownership_type": row["ownership_type"],
            "raw_hash": raw_hash(values),
        }
    except (ValueError, ArithmeticError) as exc:
        logger.warning("row %d: %s, skipping row", rownum, exc)
        return None
    return record


def _truncate(value):
    if len(value) > _TITLE_MAX_LENGTH:
        return value[:_TITLE_MAX_LENGTH]
    return value


def _parse_datetime(value):
    naive = datetime.strptime(value.strip(), _DATETIME_FORMAT)
    return naive.replace(tzinfo=_RIGA)


def _int_or_none(value):
    value = value.strip()
    if not value:
        return None
    return int(value)


def _decimal_or_none(value):
    value = value.strip()
    if not value:
        return None
    return Decimal(value)
