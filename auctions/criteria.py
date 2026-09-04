"""Machine-checkable shape of a ``FilterProfile.criteria`` dict.

Standard library only — this module imports **no** Django. It is the single
source for the ``criteria`` schema constants shared by
``accounts.models.FilterProfile.clean()`` (save-time validation) and
``auctions.matching`` (match-time validation), so the two can never drift.

Only the machine-checkable constants live here. The human-facing spec — the
AND/OR rules and the inclusive, decimal-string price-bound semantics — stays
in ``FilterProfile``'s docstring.
"""

#: criteria list-key -> the listing field it constrains.
LIST_DIMENSIONS = {
    "region_ids": "region_id",
    "category_ids": "category_id",
    "states": "state",
}

#: Keys whose value, when present, must be a JSON list.
LIST_KEYS = tuple(LIST_DIMENSIONS)

#: The only keys ``criteria`` may contain.
ALLOWED_KEYS = frozenset(LIST_KEYS) | {"price_min", "price_max"}
