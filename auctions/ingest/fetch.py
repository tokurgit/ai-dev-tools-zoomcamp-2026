"""Best-effort HTTP refresh of the local ``izsoles.csv``.

This is **not** the primary input path — an operator normally drops the daily
file at ``settings.IZSOLES_CSV_PATH`` and :mod:`auctions.ingest.parse` reads it
from there. :func:`fetch_csv` simply overwrites that local file from the
open-data URL when it is available.

The open-data endpoint 403s a plain request; it needs a browser-like
``User-Agent`` and ``Referer`` and, in practice, live session cookies (supplied
via ``settings.IZSOLES_FETCH_COOKIE`` / the ``IZSOLES_FETCH_COOKIE`` env var).
Making the scheduled fetch reliable against bot detection is deployment work
(issues #16 / #17); this helper just does the request cleanly and fails loudly.

The parser never calls this, and the test suite never exercises it over real
HTTP.
"""

import logging
from pathlib import Path

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

#: Sent so the open-data nginx does not 403 the request outright.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REFERER = "https://izsoles.ta.gov.lv/"
DEFAULT_TIMEOUT = 30.0


class FetchError(RuntimeError):
    """The CSV could not be fetched (network failure or non-200 response)."""


def fetch_csv(dest_path=None, *, url=None, cookie=None, timeout=DEFAULT_TIMEOUT,
              transport=None):
    """Download the open-data CSV to *dest_path*, returning the written path.

    Falls back to ``settings.IZSOLES_CSV_PATH`` / ``settings.IZSOLES_OPEN_DATA_URL``
    / ``settings.IZSOLES_FETCH_COOKIE``. Raises :class:`FetchError` on a non-200
    response. *transport* is an injection seam for tests (an ``httpx`` transport);
    production leaves it ``None`` for the real network transport.
    """
    dest_path = Path(dest_path) if dest_path is not None else Path(settings.IZSOLES_CSV_PATH)
    url = url if url is not None else settings.IZSOLES_OPEN_DATA_URL
    cookie = cookie if cookie is not None else settings.IZSOLES_FETCH_COOKIE

    headers = {"User-Agent": BROWSER_USER_AGENT, "Referer": REFERER}
    if cookie:
        headers["Cookie"] = cookie

    logger.info("fetching izsoles.csv from %s", url)
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(url, headers=headers)

    if response.status_code != 200:
        raise FetchError(
            f"izsoles.csv fetch failed: HTTP {response.status_code} from {url}"
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(response.content)
    logger.info("wrote %d bytes to %s", len(response.content), dest_path)
    return dest_path
