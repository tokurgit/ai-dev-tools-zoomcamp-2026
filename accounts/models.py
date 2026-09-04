from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models

from auctions.criteria import ALLOWED_KEYS, LIST_KEYS


class User(AbstractUser):
    """Project user.

    A straight subclass of ``AbstractUser`` with no extra fields yet. It exists
    so ``AUTH_USER_MODEL`` points at an app-owned model from the start and future
    profile/preference fields have a home without another migration dance.
    """


class FilterProfile(models.Model):
    """A user's saved auction search: match ``criteria`` plus notification prefs.

    ``criteria`` is a JSON object with a fixed shape. Every key is optional::

        {
            "region_ids":   [7, 96],            # list[int]  — Region PKs
            "category_ids": [1, 2, 18],          # list[int]  — Category PKs
            "price_min":    "10000.00",          # str        — decimal string
            "price_max":    "50000.00",          # str        — decimal string
            "states":       ["apstiprināta"]     # list[str]  — Listing.state values
        }

    Semantics (read by #7 matching and #12 forms):

    - **Keys are ANDed.** A listing must satisfy every present key.
    - **List values are ORed.** ``region_ids: [7, 96]`` matches a listing whose
      region is 7 *or* 96.
    - **Absent key or empty list = unconstrained** on that dimension.
    - ``{}`` matches every candidate listing (i.e. every real-estate listing
      from 2026 onwards — the import filter in #5 is the outer bound).
    - ``price_min`` / ``price_max`` are **inclusive** bounds compared against
      ``Listing.start_price``. They are stored as strings holding decimals and
      compared as ``Decimal``. ``price_min`` alone means "at least"; ``price_max``
      alone means "at most".
    - ``states`` is ORed the same way and compared to ``Listing.state``.

    ``clean()`` enforces the shape: it rejects unknown keys, non-list values for
    ``region_ids`` / ``category_ids`` / ``states``, and ``price_min`` greater
    than ``price_max``.
    """

    #: The only keys ``criteria`` may contain. Defined in the model-free
    #: :mod:`auctions.criteria` so ``clean()`` and ``auctions.matching`` share
    #: one source and cannot drift.
    ALLOWED_CRITERIA_KEYS = ALLOWED_KEYS
    #: Keys whose value, when present, must be a JSON list.
    LIST_CRITERIA_KEYS = LIST_KEYS

    class Delivery(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        DIGEST = "digest", "Digest"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="filter_profiles",
    )
    name = models.CharField(max_length=255)
    criteria = models.JSONField(default=dict, blank=True)

    notify_new = models.BooleanField(default=True)
    notify_change = models.BooleanField(default=False)
    notify_deadline = models.BooleanField(default=False)
    deadline_days = models.PositiveSmallIntegerField(default=3)
    delivery = models.CharField(
        max_length=9, choices=Delivery.choices, default=Delivery.DIGEST
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_filter_profile_name_per_user"
            )
        ]

    def __str__(self):
        return f"{self.user} – {self.name}"

    def clean(self):
        super().clean()
        criteria = self.criteria or {}

        unknown = set(criteria) - self.ALLOWED_CRITERIA_KEYS
        if unknown:
            raise ValidationError(
                {"criteria": f"Unknown criteria key(s): {', '.join(sorted(unknown))}"}
            )

        for key in self.LIST_CRITERIA_KEYS:
            if key in criteria and not isinstance(criteria[key], list):
                raise ValidationError({"criteria": f"{key!r} must be a list"})

        price_min = criteria.get("price_min")
        price_max = criteria.get("price_max")
        if price_min is not None and price_max is not None:
            try:
                bounds_inverted = Decimal(str(price_min)) > Decimal(str(price_max))
            except InvalidOperation:
                raise ValidationError(
                    {"criteria": "price_min / price_max must be decimal strings"}
                )
            if bounds_inverted:
                raise ValidationError(
                    {"criteria": "price_min must not be greater than price_max"}
                )
