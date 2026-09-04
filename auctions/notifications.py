"""Turn the day's matcher results into ``pending`` :class:`Notification` rows.

:func:`queue_notifications` is the bridge between the import + match step (#5 /
#7) and the send step (#9). It inserts one ``pending`` notification per
(filter profile, listing, alert type) that does not already have one — of *any*
status — and nothing else: no email is sent, no row is marked ``sent``.

Idempotent: running it twice over the same input inserts rows only once, both
against what is already in the database and against duplicates within the run
itself.
"""

from django.db import transaction

from auctions.models import Notification


def queue_notifications(created, updated, matches):
    """Insert ``pending`` notifications for the matched listings; return them.

    ``created`` and ``updated`` are the ``Listing`` lists from
    :class:`auctions.ingest.importer.ImportResult`. ``matches`` maps each of
    those listings to the profiles :func:`auctions.matching.match_profiles`
    returned for it — ``dict[Listing, list[FilterProfile]]`` keyed by the
    ``Listing`` object (the shape the orchestrator #10 builds by walking
    ``result.created + result.updated`` and calling ``match_profiles`` per
    listing). A listing missing from the mapping is treated as "no matches".

    Per matched pair:

    * a ``created`` listing × profile with ``notify_new`` → a ``new`` row,
    * an ``updated`` listing × profile with ``notify_change`` → a ``changed`` row.

    ``user`` is copied from ``filter_profile.user``. Any triple that already has
    a ``Notification`` (any status) is skipped silently, as is a repeat of the
    same triple within this run. The insert is a single batched
    ``bulk_create`` inside a transaction, so a mid-run failure leaves no
    partial batch.

    Returns the list of :class:`Notification` objects actually created.
    """
    # (filter_profile.pk, listing.pk, alert_type) -> (profile, listing, alert_type)
    # dict membership dedups repeats within the run (e.g. a listing that shows
    # up in both `created` and `updated` for one profile, or twice in one list).
    planned = {}
    for listings, alert_type, pref in (
        (created, Notification.AlertType.NEW, "notify_new"),
        (updated, Notification.AlertType.CHANGED, "notify_change"),
    ):
        for listing in listings:
            for profile in matches.get(listing, ()):
                if getattr(profile, pref):
                    planned.setdefault(
                        (profile.pk, listing.pk, alert_type),
                        (profile, listing, alert_type),
                    )

    listing_ids = {listing_pk for _, listing_pk, _ in planned}
    already = set(
        Notification.objects.filter(listing_id__in=listing_ids).values_list(
            "filter_profile_id", "listing_id", "alert_type"
        )
    )
    to_create = [
        Notification(
            user=profile.user,
            filter_profile=profile,
            listing=listing,
            alert_type=alert_type,
            status=Notification.Status.PENDING,
        )
        for key, (profile, listing, alert_type) in planned.items()
        if key not in already
    ]

    with transaction.atomic():
        Notification.objects.bulk_create(to_create)
    return to_create
