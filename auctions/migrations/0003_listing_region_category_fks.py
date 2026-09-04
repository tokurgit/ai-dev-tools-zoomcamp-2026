"""Convert Listing.region_id / Listing.category_id from loose integer codes to
ForeignKeys to the Region / Category reference tables (#18).

Data-preserving: the existing integer values live in the ``region_id`` /
``category_id`` columns. RenameField moves each to a temporary name, then
AlterField turns it into a ForeignKey whose attname is again ``region_id`` /
``category_id`` — so the column keeps its data and its final name. Codes with
no matching reference row are simply left as-is; the FK is not validated on
existing rows, and the import path (#5) is responsible for resolving a code to
a real row or storing NULL.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auctions", "0002_category_region"),
    ]

    operations = [
        migrations.RenameField(
            model_name="listing", old_name="region_id", new_name="region"
        ),
        migrations.RenameField(
            model_name="listing", old_name="category_id", new_name="category"
        ),
        migrations.AlterField(
            model_name="listing",
            name="region",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="auctions.region",
            ),
        ),
        migrations.AlterField(
            model_name="listing",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="auctions.category",
            ),
        ),
    ]
