"""Turn the day's matcher results into ``pending`` :class:`Notification` rows.

:func:`queue_notifications` is the bridge between the import + match step (#5 /
#7) and the send step (#9). It inserts one ``pending`` notification per
(filter profile, listing, alert type) that does not already have one — of *any*
status — and nothing else: no email is sent, no row is marked ``sent``.

Idempotent: running it twice over the same input inserts rows only once, both
against what is already in the database and against duplicates within the run
itself.
"""

import dataclasses

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.models import FilterProfile
from auctions.email import get_backend
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


@dataclasses.dataclass(frozen=True)
class DispatchResult:
    """Outcome of one :func:`dispatch_pending` run.

    ``emails`` is the number of emails attempted (one per batch); ``sent`` and
    ``failed`` count *notification rows*, not emails.
    """

    emails: int
    sent: int
    failed: int


def batch_notifications(notifications):
    """Split pending notifications into per-email batches — the #14 seam.

    Grouping:

    * every row from a ``delivery="digest"`` profile collapses into **one**
      batch per recipient user;
    * every row whose ``filter_profile`` is ``NULL`` (the profile was deleted,
      #13) is **treated as digest** and joins that same per-user batch — the
      user still owns the row and should still hear about the listing;
    * every row from a ``delivery="immediate"`` profile becomes **its own**
      batch — one email per notification (per listing), not per profile. A user
      with two immediate notifications gets two emails.

    Returns a list of lists — each inner list is the rows for one email — in
    order of first appearance.
    """
    batches = {}
    for note in notifications:
        profile = note.filter_profile
        if (
            profile is not None
            and profile.delivery == FilterProfile.Delivery.IMMEDIATE
        ):
            key = ("immediate", note.pk)
        else:
            key = ("digest", note.user_id)
        batches.setdefault(key, []).append(note)
    return list(batches.values())


def _listing_url(listing):
    return settings.LISTING_URL_TEMPLATE.format(source_id=listing.source_id)


def _render_email(recipient, rows):
    """Render the (subject, body) plain-text pair for one batch."""
    items = [
        {
            "title": row.listing.title or "(untitled listing)",
            "price": (
                row.listing.start_price
                if row.listing.start_price is not None
                else "n/a"
            ),
            "end_time": row.listing.end_time,
            "url": _listing_url(row.listing),
            "profile": (
                row.filter_profile.name
                if row.filter_profile is not None
                else "(deleted filter)"
            ),
            "alert_type": row.get_alert_type_display(),
        }
        for row in rows
    ]
    context = {
        "recipient": recipient.get_full_name() or recipient.get_username(),
        "count": len(items),
        "items": items,
    }
    subject = render_to_string("email/notification_subject.txt", context).strip()
    body = render_to_string("email/notification_body.txt", context)
    return subject, body


def _finish_batch(rows, status, *, sent_at=None, error=""):
    """Flip one batch's rows to *status*, isolated in its own transaction."""
    with transaction.atomic():
        Notification.objects.filter(pk__in=[row.pk for row in rows]).update(
            status=status, sent_at=sent_at, error=error
        )


#: Statuses :func:`dispatch_pending` picks up on each run. ``pending`` is a
#: freshly queued row; ``failed`` is a row whose last send attempt errored —
#: it is retried unconditionally (no attempt cap), so a transient provider
#: outage clears itself the next run. ``sent`` rows are terminal and never
#: re-selected, which is what makes an immediate re-run a no-op.
DISPATCHABLE_STATUSES = (Notification.Status.PENDING, Notification.Status.FAILED)


def dispatch_pending(backend=None, queryset=None):
    """Send pending/failed notifications as email; return a :class:`DispatchResult`.

    Selects rows whose ``status`` is in :data:`DISPATCHABLE_STATUSES`
    (``pending`` or ``failed``), with ``select_related`` on user / filter
    profile / listing, groups them into email batches with
    :func:`batch_notifications`, and sends one email per batch through
    *backend* (defaults to :func:`auctions.email.get_backend`, resolved up front
    so a bad ``NOTIFICATION_BACKEND`` fails before any row is touched).

    *queryset*, when given, scopes the run to that subset of rows (still
    filtered down to :data:`DISPATCHABLE_STATUSES` — passing a queryset that
    includes ``sent`` rows just means those are ignored) instead of every
    dispatchable row in the table. This is the seam the admin's "Resend
    selected" action (#15) uses to re-send a chosen set of ``failed`` rows
    without touching the rest of the pending queue. ``None`` (the default)
    keeps today's behaviour: every pending/failed row.

    On a successful ``send()`` every row in that batch becomes ``sent`` with
    ``sent_at`` set and ``error`` cleared. On failure the batch's rows become
    ``failed`` with ``error`` set to the exception message, and the remaining
    batches still go out. Each batch's DB update runs in its own transaction, so
    one batch failing cannot corrupt another.

    Re-running straight after a success does nothing — the rows are ``sent`` and
    no longer selected. A ``failed`` row **is** re-selected on the next run, so
    running again is the whole retry story.
    """
    if backend is None:
        backend = get_backend()
    if queryset is None:
        queryset = Notification.objects.all()

    pending = list(
        queryset.filter(status__in=DISPATCHABLE_STATUSES)
        .select_related("user", "filter_profile", "listing")
        .order_by("pk")
    )

    emails = sent = failed = 0
    for rows in batch_notifications(pending):
        emails += 1
        recipient = rows[0].user
        subject, body = _render_email(recipient, rows)
        try:
            backend.send(recipient.email, subject, body)
        except Exception as exc:  # any backend failure fails just this batch
            _finish_batch(rows, Notification.Status.FAILED, error=str(exc))
            failed += len(rows)
        else:
            _finish_batch(
                rows, Notification.Status.SENT, sent_at=timezone.now()
            )
            sent += len(rows)
    return DispatchResult(emails=emails, sent=sent, failed=failed)
