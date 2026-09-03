"""Parsing helpers for the reference-data CSVs (``kategorija.csv``, ``region.csv``).

Both files share the same shape: a header ``id,name`` followed by data rows with
a UTF-8 Latvian label that may be quoted and contain commas.

:func:`parse_reference_csv` accepts any text file-like object (an open file, an
``io.StringIO``, a decoded HTTP response body), so #4 can feed it a fetched
stream without the management command being rewritten.
"""

import csv
import logging

logger = logging.getLogger(__name__)


class ReferenceRow:
    """A single validated ``(id, name)`` pair from a reference CSV."""

    __slots__ = ("id", "name")

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __repr__(self):
        return f"ReferenceRow(id={self.id!r}, name={self.name!r})"

    def __eq__(self, other):
        return (
            isinstance(other, ReferenceRow)
            and self.id == other.id
            and self.name == other.name
        )


def parse_reference_csv(fileobj):
    """Yield :class:`ReferenceRow` for each valid data row in *fileobj*.

    *fileobj* is any iterable of text lines (an open file in text mode,
    ``io.StringIO``, etc.). Malformed rows — blank lines, a missing/blank
    ``name``, a non-integer ``id``, the wrong column count — are skipped with a
    logged warning; parsing continues with the remaining rows.
    """
    reader = csv.reader(fileobj)

    try:
        header = next(reader)
    except StopIteration:
        logger.warning("reference CSV is empty")
        return

    if [c.strip().lower() for c in header] != ["id", "name"]:
        logger.warning("unexpected reference CSV header: %r", header)

    for lineno, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            logger.warning("line %d: blank row, skipping", lineno)
            continue
        if len(row) != 2:
            logger.warning(
                "line %d: expected 2 columns, got %d (%r), skipping",
                lineno, len(row), row,
            )
            continue

        raw_id, name = row[0].strip(), row[1].strip()
        if not raw_id:
            logger.warning("line %d: missing id, skipping", lineno)
            continue
        if not name:
            logger.warning("line %d: missing name for id %r, skipping", lineno, raw_id)
            continue
        try:
            row_id = int(raw_id)
        except ValueError:
            logger.warning("line %d: non-integer id %r, skipping", lineno, raw_id)
            continue

        yield ReferenceRow(id=row_id, name=name)
