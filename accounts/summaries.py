"""Human-readable summaries of a :class:`~accounts.models.FilterProfile`.

Two helpers, both pure read helpers used by the ``filterprofile_list`` view
(issue #12):

- :func:`summarize_criteria` turns a stored ``criteria`` dict into one line,
  resolving ``region_ids`` / ``category_ids`` to ``Region.name`` / ``Category.name``
  via the #3 reference tables and spelling out the price range and states.
- :func:`summarize_preferences` turns the notification-preference fields into
  one line.
"""

from auctions.models import Category, Region


def _names(model, ids):
    """Resolve reference-table PKs to a ``", "``-joined name string.

    Unknown / stale PKs (a reference row later removed) simply drop out.
    """
    by_id = {row.id: row.name for row in model.objects.filter(id__in=ids)}
    return ", ".join(by_id[i] for i in ids if i in by_id)


def summarize_criteria(criteria):
    """Return a one-line, human-readable summary of a ``criteria`` dict."""
    criteria = criteria or {}
    parts = []

    region_ids = criteria.get("region_ids") or []
    if region_ids:
        parts.append(f"Regions: {_names(Region, region_ids)}")

    category_ids = criteria.get("category_ids") or []
    if category_ids:
        parts.append(f"Categories: {_names(Category, category_ids)}")

    price_min = criteria.get("price_min")
    price_max = criteria.get("price_max")
    if price_min is not None and price_max is not None:
        parts.append(f"Price {price_min}–{price_max}")
    elif price_min is not None:
        parts.append(f"Price from {price_min}")
    elif price_max is not None:
        parts.append(f"Price up to {price_max}")

    states = criteria.get("states") or []
    if states:
        parts.append(f"States: {', '.join(states)}")

    if not parts:
        return "Matches every listing"
    return "; ".join(parts)


def summarize_preferences(profile):
    """Return a one-line summary of a profile's notification preferences."""
    events = []
    if profile.notify_new:
        events.append("new listings")
    if profile.notify_change:
        events.append("changes")
    if profile.notify_deadline:
        events.append(f"deadline in {profile.deadline_days}d")

    events_text = ", ".join(events) if events else "nothing"
    return f"Notify on {events_text}; {profile.get_delivery_display().lower()} delivery"
