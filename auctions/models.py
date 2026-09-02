from django.db import models


class Listing(models.Model):
    # Source identifier — UUID from izsoles.csv (field name: id)
    source_id = models.UUIDField(unique=True)

    title = models.CharField(max_length=500)
    initiated_by = models.CharField(max_length=20)  # "ZTI", "MPA", or "LegalPerson"
    bailiff = models.CharField(max_length=255, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    state = models.CharField(max_length=100)

    # Reference code fields — FKs added in task 3 when reference models exist
    region_id = models.IntegerField(null=True, blank=True)
    category_id = models.IntegerField(null=True, blank=True)
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
