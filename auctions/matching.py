"""Decide which saved filter profiles a listing matches.

Pure Python — standard library plus :mod:`decimal` only. This module imports no
Django models and touches no database so the orchestration command (#10) and
unit tests can reuse it freely.

``match_profiles(listing, profiles)`` returns the subset of ``profiles`` whose
``criteria`` the ``listing`` satisfies, in input order, each profile evaluated
independently.

Both arguments are duck-typed:

- ``listing`` is a ``Listing`` instance *or* a plain mapping exposing
  ``region_id``, ``category_id``, ``start_price`` and ``state``.
- each profile is an object *or* a mapping exposing ``criteria`` (a dict).

The ``criteria`` schema and its semantics are pinned by
``accounts.models.FilterProfile`` (issue #6). The machine-checkable constants
are imported from :mod:`auctions.criteria` (model-free, stdlib only) so this
module and the model share one definition and cannot drift. The semantics:

- **Keys are ANDed** — a profile matches only if every present constraint holds.
- **List values are ORed** — ``region_ids: [7, 96]`` matches region 7 or 96.
- **Absent key or empty list = unconstrained** on that dimension.
- ``criteria == {}`` (or all keys absent) matches every listing.
- A listing dimension that is ``None`` fails a non-empty constraint on it.
- ``price_min`` / ``price_max`` are inclusive bounds, parsed to ``Decimal``;
  ``start_price is None`` fails any price constraint; either bound works alone.

Invalid ``criteria`` (an unknown key, a list-field that is not a list, a
non-decimal price string, or ``price_min`` greater than ``price_max``) raises a
plain ``ValueError`` — mirroring #6's ``clean()`` rejection rules, but without
Django's ``ValidationError`` since this module is model-free.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from auctions.criteria import ALLOWED_KEYS as ALLOWED_CRITERIA_KEYS
from auctions.criteria import LIST_DIMENSIONS as _LIST_DIMENSIONS


def _get(obj, key):
    """Read ``key`` from ``obj`` whether it is a mapping or a plain object."""
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _parse_price(value, label):
    """Parse a criteria price bound to ``Decimal`` (or ``None`` when absent)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label} must be a decimal string") from None


def _validate(criteria):
    """Reject a malformed ``criteria`` dict; return its parsed price bounds."""
    unknown = set(criteria) - ALLOWED_CRITERIA_KEYS
    if unknown:
        raise ValueError(f"Unknown criteria key(s): {', '.join(sorted(unknown))}")

    for key in _LIST_DIMENSIONS:
        if key in criteria and not isinstance(criteria[key], list):
            raise ValueError(f"{key!r} must be a list")

    price_min = _parse_price(criteria.get("price_min"), "price_min")
    price_max = _parse_price(criteria.get("price_max"), "price_max")
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ValueError("price_min must not be greater than price_max")

    return price_min, price_max


def _listing_matches(listing, criteria):
    """Return whether one ``listing`` satisfies one ``criteria`` dict."""
    price_min, price_max = _validate(criteria)

    for crit_key, field in _LIST_DIMENSIONS.items():
        allowed = criteria.get(crit_key)
        if not allowed:
            continue
        value = _get(listing, field)
        if value is None or value not in allowed:
            return False

    if price_min is not None or price_max is not None:
        start_price = _get(listing, "start_price")
        if start_price is None:
            return False
        start_price = Decimal(str(start_price))
        if price_min is not None and start_price < price_min:
            return False
        if price_max is not None and start_price > price_max:
            return False

    return True


def match_profiles(listing, profiles):
    """Return the profiles from ``profiles`` that ``listing`` matches, in order.

    ``listing`` is a ``Listing`` instance or a mapping with ``region_id``,
    ``category_id``, ``start_price`` and ``state``. ``profiles`` is any iterable
    of objects/dicts exposing ``criteria``. Raises ``ValueError`` on a malformed
    ``criteria``.
    """
    matched = []
    for profile in profiles:
        criteria = _get(profile, "criteria") or {}
        if _listing_matches(listing, criteria):
            matched.append(profile)
    return matched
