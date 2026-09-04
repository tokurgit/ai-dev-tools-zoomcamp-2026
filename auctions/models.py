from django.conf import settings
from django.db import models


class Category(models.Model):
    """Auction category lookup — mirrors ``kategorija.csv`` from the open-data feed."""

    id = models.IntegerField(primary_key=True)  # the CSV `id`
    name = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["id"]

    def __str__(self):
        return self.name


class Region(models.Model):
    """Region lookup — mirrors ``region.csv`` from the open-data feed."""

    id = models.IntegerField(primary_key=True)  # the CSV `id`
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class Listing(models.Model):
    # Source identifier — UUID from izsoles.csv (field name: id)
    source_id = models.UUIDField(unique=True)

    title = models.CharField(max_length=500, blank=True)
    initiated_by = models.CharField(max_length=20)  # "ZTI", "MPA", or "LegalPerson"
    bailiff = models.CharField(max_length=255, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    state = models.CharField(max_length=100)

    # Reference FKs — the CSV carries integer codes; unknown codes resolve to NULL.
    region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.SET_NULL
    )
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL
    )
    # No reference model for offices/bailiffs yet — stays a plain code (see #18).
    office_id = models.CharField(max_length=50, blank=True)

    area = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valuation = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    start_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    bid_step = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    last_bid = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    # -1 is a valid stage value in the live data
    stage = models.SmallIntegerField(null=True, blank=True)
    type = models.CharField(max_length=100, blank=True)
    ownership_type = models.CharField(max_length=20, blank=True)  # "owner" or "rent"

    # SHA-256 hash of the raw CSV row — used to detect changes on re-import
    raw_hash = models.CharField(max_length=64, db_index=True)

    class Meta:
        ordering = ["-end_time"]

    def __str__(self):
        return f"{self.source_id}: {self.title}"


class Notification(models.Model):
    """One queued alert: a listing matched a user's filter profile.

    Rows are written by :func:`auctions.notifications.queue_notifications` in
    ``pending`` state; sending them and flipping ``status`` is issue #9.

    ``filter_profile`` is ``SET_NULL`` so a notification the user may still open
    survives deletion of the profile that generated it (#13); ``user`` (a
    denormalised copy of ``filter_profile.user``, set by the queuing function,
    never user-supplied) and ``listing`` stay the anchors after that. The
    ``UniqueConstraint`` on (``filter_profile``, ``listing``, ``alert_type``)
    keeps a profile to at most one notification of each type per listing; once
    ``filter_profile`` is ``NULL`` the row is historical and no longer takes
    part in dedup.
    """

    class AlertType(models.TextChoices):
        NEW = "new", "New"
        CHANGED = "changed", "Changed"
        DEADLINE = "deadline", "Deadline"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    filter_profile = models.ForeignKey(
        "accounts.FilterProfile",
        null=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    alert_type = models.CharField(max_length=8, choices=AlertType.choices)
    status = models.CharField(
        max_length=7, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["filter_profile", "listing", "alert_type"],
                name="unique_notification_per_profile_listing_type",
            )
        ]

    def __str__(self):
        return f"{self.user} · {self.alert_type} · {self.listing_id}"
