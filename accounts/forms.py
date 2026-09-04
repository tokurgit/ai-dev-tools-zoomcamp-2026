"""Forms for the ``accounts`` app.

:class:`FilterProfileForm` (issue #12) is the create form for
:class:`~accounts.models.FilterProfile`. It is a ``ModelForm`` that exposes
only ``name`` as a model field and adds discrete, user-friendly fields
(``regions``, ``categories``, ``price_min``, ``price_max``, ``states``) which
:meth:`FilterProfileForm.clean` serialises into the ``criteria`` JSON shape
pinned by issue #6 — ``{region_ids, category_ids, price_min, price_max,
states}`` — omitting any empty key.

``user`` is never a form field: the view passes it to ``__init__`` and it is
bound to the instance server-side.
"""

from decimal import Decimal

from django import forms

from accounts.models import FilterProfile
from auctions.models import Category, Listing, Region

#: Always offered as a ``states`` choice even when no listing currently has it —
#: it is the state a fresh import lands real-estate auctions in and the one a
#: brand-new profile most often wants to watch for. Every other choice is
#: derived from the distinct ``Listing.state`` values present in the database.
ALWAYS_OFFERED_STATE = "apstiprināta"


def state_choices():
    """``(value, label)`` choices for the ``states`` field.

    The distinct ``Listing.state`` values currently in the database, unioned
    with :data:`ALWAYS_OFFERED_STATE`, sorted, blanks dropped.
    """
    values = set(Listing.objects.values_list("state", flat=True).distinct())
    values.add(ALWAYS_OFFERED_STATE)
    return [(s, s) for s in sorted(values) if s]


class FilterProfileForm(forms.ModelForm):
    regions = forms.ModelMultipleChoiceField(
        queryset=Region.objects.all(), required=False
    )
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(), required=False
    )
    price_min = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=14, decimal_places=2
    )
    price_max = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=14, decimal_places=2
    )
    states = forms.MultipleChoiceField(required=False)

    class Meta:
        model = FilterProfile
        fields = ["name"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.instance.user = user
        self.fields["states"].choices = state_choices()

    def clean(self):
        cleaned = super().clean()

        regions = cleaned.get("regions")
        categories = cleaned.get("categories")
        price_min = cleaned.get("price_min")
        price_max = cleaned.get("price_max")
        states = cleaned.get("states")

        if (
            price_min is not None
            and price_max is not None
            and price_min > price_max
        ):
            raise forms.ValidationError(
                "price_min must not be greater than price_max."
            )

        criteria = {}
        if regions:
            criteria["region_ids"] = sorted(r.id for r in regions)
        if categories:
            criteria["category_ids"] = sorted(c.id for c in categories)
        if price_min is not None:
            criteria["price_min"] = f"{price_min:.2f}"
        if price_max is not None:
            criteria["price_max"] = f"{price_max:.2f}"
        if states:
            criteria["states"] = list(states)

        if not criteria:
            raise forms.ValidationError(
                "Set at least one of regions, categories, a price bound, or "
                "states — an empty filter would match everything."
            )

        self.instance.criteria = criteria
        return cleaned
