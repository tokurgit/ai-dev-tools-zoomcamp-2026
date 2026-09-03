import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from django.test import SimpleTestCase, override_settings

from auctions.ingest.fetch import (
    BROWSER_USER_AGENT,
    REFERER,
    FetchError,
    fetch_csv,
)
from auctions.ingest.parse import parse_listings, raw_hash

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "izsoles_sample.csv"
BAD_BYTES = FIXTURES / "izsoles_bad_bytes.csv"

PARSE_LOG = "auctions.ingest.parse"

# Column order the live feed emits (also the raw_hash pre-image order).
COLUMNS = [
    "title", "id", "initiated_by", "bailiff", "start_time", "end_time", "state",
    "region_id", "category_id", "office_id", "area", "valuation", "start_price",
    "bid_step", "last_bid", "stage", "type", "ownership_type", "usage_goal",
]


def parse(source):
    result = parse_listings(source)
    return list(result), result


class ParseListingsTest(SimpleTestCase):
    def test_yields_one_dict_per_data_row_and_counts_skips(self):
        records, result = parse(SAMPLE)
        # 11 data rows: 7 parse, 4 are malformed (bad col count, bad uuid,
        # empty id, bad decimal).
        self.assertEqual(result.total_rows, 11)
        self.assertEqual(len(records), 7)
        self.assertEqual(result.parsed_rows, 7)
        self.assertEqual(result.skipped_rows, 4)

    def test_clean_row_maps_to_listing_field_names(self):
        (clean, *_), _ = parse(SAMPLE)
        self.assertEqual(set(clean), {
            "source_id", "title", "initiated_by", "bailiff", "start_time",
            "end_time", "state", "region_id", "category_id", "office_id",
            "area", "valuation", "start_price", "bid_step", "last_bid", "stage",
            "type", "ownership_type", "raw_hash",
        })
        self.assertNotIn("usage_goal", clean)
        self.assertNotIn("id", clean)
        self.assertEqual(
            clean["source_id"], uuid.UUID("1e548c7f-eba4-45f4-88c2-8742f1858d87")
        )
        self.assertIsInstance(clean["source_id"], uuid.UUID)
        self.assertEqual(clean["title"], "Maltas iela 21 - 74, Rīga")
        self.assertEqual(clean["initiated_by"], "ZTI")
        self.assertEqual(clean["state"], "apstiprināta")
        self.assertEqual(clean["region_id"], 7)
        self.assertEqual(clean["category_id"], 3)
        self.assertEqual(clean["office_id"], "58")
        self.assertEqual(clean["area"], Decimal("53.42"))
        self.assertEqual(clean["valuation"], Decimal("19100"))
        self.assertEqual(clean["stage"], 1)

    def test_start_end_times_are_riga_local_aware(self):
        (clean, *_), _ = parse(SAMPLE)
        start = clean["start_time"]
        self.assertIsNotNone(start.tzinfo)
        # 2026-03-01 is winter -> Europe/Riga is UTC+2.
        self.assertEqual(
            start.astimezone(timezone.utc),
            datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            clean["end_time"].astimezone(timezone.utc),
            datetime(2026, 4, 1, 7, 5, 0, tzinfo=timezone.utc),
        )

    def test_blank_numeric_fields_become_none(self):
        records, _ = parse(SAMPLE)
        blank = records[1]
        for field in ("area", "valuation", "start_price", "bid_step",
                      "last_bid", "stage"):
            self.assertIsNone(blank[field], field)
        self.assertIsNone(blank["category_id"])

    def test_negative_stage_and_office_id_preserved(self):
        records, _ = parse(SAMPLE)
        row = records[2]
        self.assertEqual(row["stage"], -1)
        self.assertEqual(row["office_id"], "-590")

    def test_blank_region_id_becomes_none(self):
        records, _ = parse(SAMPLE)
        self.assertIsNone(records[3]["region_id"])
        self.assertEqual(records[3]["category_id"], 1)

    def test_integer_looking_decimal_values_are_valid(self):
        records, _ = parse(SAMPLE)
        row = records[3]
        self.assertEqual(row["valuation"], Decimal("7"))
        self.assertEqual(row["bid_step"], Decimal("0.5"))
        self.assertEqual(row["office_id"], "0")

    def test_embedded_newline_title_is_kept_whole(self):
        records, _ = parse(SAMPLE)
        row = records[4]
        self.assertIn("\n", row["title"])
        self.assertEqual(row["title"], "Rusova iela 32 - 12,\nRīga")

    def test_blank_title_passes_through_as_empty_string(self):
        records, _ = parse(SAMPLE)
        self.assertEqual(records[5]["title"], "")

    def test_overlong_title_truncated_to_500(self):
        records, _ = parse(SAMPLE)
        self.assertEqual(len(records[6]["title"]), 500)
        self.assertEqual(records[6]["title"], "Ā" * 500)

    def test_malformed_rows_are_skipped_logged_with_row_number(self):
        with self.assertLogs(PARSE_LOG, level="WARNING") as cm:
            _, result = parse(SAMPLE)
        self.assertEqual(result.skipped_rows, 4)
        joined = "\n".join(cm.output)
        self.assertIn("row 7: expected 19 columns, got 5", joined)
        self.assertIn("row 8: unparseable id 'not-a-uuid'", joined)
        self.assertIn("row 9: unparseable id ''", joined)
        self.assertIn("row 10:", joined)

    def test_undecodable_bytes_row_is_treated_as_malformed(self):
        with open(BAD_BYTES, "rb") as handle:
            with self.assertLogs(PARSE_LOG, level="WARNING") as cm:
                records, result = parse(handle)
        self.assertEqual(len(records), 1)
        self.assertEqual(result.skipped_rows, 1)
        self.assertIn("undecodable bytes", "\n".join(cm.output))

    def test_accepts_path_object(self):
        records, _ = parse(Path(SAMPLE))
        self.assertEqual(len(records), 7)

    def test_accepts_text_file_like_object(self):
        with open(SAMPLE, encoding="utf-8") as handle:
            records, _ = parse(handle)
        self.assertEqual(len(records), 7)

    def test_accepts_binary_file_like_object(self):
        with open(SAMPLE, "rb") as handle:
            records, _ = parse(handle)
        self.assertEqual(len(records), 7)

    def test_empty_input_yields_nothing(self):
        with self.assertLogs(PARSE_LOG, level="WARNING") as cm:
            records, result = parse(io.StringIO(""))
        self.assertEqual(records, [])
        self.assertEqual(result.total_rows, 0)
        self.assertIn("izsoles.csv is empty", cm.output[0])

    def test_unexpected_header_is_warned_but_rows_still_parse(self):
        stream = io.StringIO(
            "code,name\n"
            '"x",1e548c7f-eba4-45f4-88c2-8742f1858d87,ZTI,B,'
            "2026-03-01 10:00:00,2026-04-01 10:00:00,apstiprināta,"
            "7,3,58,1,1,1,1,1,1,Nekustamie īpašumi,owner,\n"
        )
        with self.assertLogs(PARSE_LOG, level="WARNING") as cm:
            records, _ = parse(stream)
        self.assertEqual(len(records), 1)
        self.assertIn("unexpected izsoles.csv header", cm.output[0])

    def test_raw_hash_is_sha256_of_raw_values_in_column_order(self):
        row = [
            "Maltas iela 21 - 74, Rīga",
            "1e548c7f-eba4-45f4-88c2-8742f1858d87", "ZTI", "Jānis Stepanovs",
            "2026-03-01 10:00:00", "2026-04-01 10:05:00", "apstiprināta",
            "7", "3", "58", "53.42", "19100", "19100", "1000", "25100", "1",
            "Nekustamie īpašumi", "owner", "",
        ]
        import hashlib

        expected = hashlib.sha256(
            "\x1f".join(row).encode("utf-8")
        ).hexdigest()
        self.assertEqual(raw_hash(row), expected)

        (clean, *_), _ = parse(SAMPLE)
        self.assertEqual(clean["raw_hash"], expected)


class FetchCsvTest(SimpleTestCase):
    def _transport(self, handler):
        return httpx.MockTransport(handler)

    def test_writes_body_to_dest_and_sends_browser_headers(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["ua"] = request.headers.get("User-Agent")
            seen["referer"] = request.headers.get("Referer")
            seen["cookie"] = request.headers.get("Cookie")
            return httpx.Response(200, content=b"title,id\nx,y\n")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "nested" / "izsoles.csv"
            returned = fetch_csv(
                dest, url="https://example.test/izsoles.csv",
                transport=self._transport(handler),
            )
            self.assertEqual(returned, dest)
            self.assertEqual(dest.read_bytes(), b"title,id\nx,y\n")

        self.assertEqual(seen["url"], "https://example.test/izsoles.csv")
        self.assertEqual(seen["ua"], BROWSER_USER_AGENT)
        self.assertEqual(seen["referer"], REFERER)
        self.assertIsNone(seen["cookie"])

    @override_settings(IZSOLES_FETCH_COOKIE="ci_session=abc; authstamp=1")
    def test_uses_settings_defaults_and_sends_cookie(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["cookie"] = request.headers.get("Cookie")
            return httpx.Response(200, content=b"data")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "izsoles.csv"
            with override_settings(
                IZSOLES_CSV_PATH=str(dest),
                IZSOLES_OPEN_DATA_URL="https://example.test/feed.csv",
            ):
                fetch_csv(transport=self._transport(handler))
            self.assertEqual(dest.read_bytes(), b"data")

        self.assertEqual(seen["url"], "https://example.test/feed.csv")
        self.assertEqual(seen["cookie"], "ci_session=abc; authstamp=1")

    def test_non_200_raises_fetch_error(self):
        def handler(request):
            return httpx.Response(403, content=b"Forbidden")

        with self.assertRaises(FetchError) as ctx:
            fetch_csv(
                "/nonexistent/izsoles.csv",
                url="https://example.test/x.csv",
                transport=self._transport(handler),
            )
        self.assertIn("HTTP 403", str(ctx.exception))

    def test_parser_module_does_not_import_httpx(self):
        import sys

        import auctions.ingest.parse as parse_mod

        self.assertFalse(hasattr(parse_mod, "httpx"))
        self.assertIn("auctions.ingest.parse", sys.modules)
