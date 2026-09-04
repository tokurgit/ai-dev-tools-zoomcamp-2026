"""Unit tests for ``auctions.matching`` — no database, no Django models.

Listings and profiles are duck-typed, so the tests exercise both plain mappings
and attribute-style objects (``SimpleNamespace`` stands in for a ``Listing`` /
``FilterProfile`` instance).
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from auctions.matching import match_profiles


def _listing(**kwargs):
    """A listing as an attribute-style object (like a ``Listing`` instance)."""
    base = dict(region_id=7, category_id=1, start_price="25000.00", state="apstiprināta")
    base.update(kwargs)
    return SimpleNamespace(**base)


def _profile(criteria):
    """A profile as an attribute-style object exposing ``.criteria``."""
    return SimpleNamespace(criteria=criteria)


class EmptyCriteriaTest(SimpleTestCase):
    def test_empty_dict_matches_every_listing(self):
        profiles = [_profile({})]
        self.assertEqual(match_profiles(_listing(), profiles), profiles)

    def test_all_keys_absent_matches(self):
        # An empty list / empty string on a dimension is "unconstrained".
        profiles = [_profile({"region_ids": [], "states": [], "category_ids": []})]
        self.assertEqual(match_profiles(_listing(region_id=None), profiles), profiles)

    def test_profile_without_a_criteria_attribute_matches(self):
        profiles = [SimpleNamespace()]
        self.assertEqual(match_profiles(_listing(), profiles), profiles)


class SingleDimensionTest(SimpleTestCase):
    def test_region_ids_match(self):
        profiles = [_profile({"region_ids": [7, 96]})]
        self.assertEqual(match_profiles(_listing(region_id=96), profiles), profiles)

    def test_region_ids_miss(self):
        profiles = [_profile({"region_ids": [7, 96]})]
        self.assertEqual(match_profiles(_listing(region_id=1), profiles), [])

    def test_category_ids_match_and_miss(self):
        profiles = [_profile({"category_ids": [1, 2]})]
        self.assertEqual(match_profiles(_listing(category_id=2), profiles), profiles)
        self.assertEqual(match_profiles(_listing(category_id=9), profiles), [])

    def test_states_match_and_miss(self):
        profiles = [_profile({"states": ["apstiprināta"]})]
        self.assertEqual(match_profiles(_listing(), profiles), profiles)
        self.assertEqual(match_profiles(_listing(state="atcelta"), profiles), [])


class MissingListingFieldTest(SimpleTestCase):
    def test_region_id_none_fails_a_non_empty_region_ids_constraint(self):
        profiles = [_profile({"region_ids": [7]})]
        self.assertEqual(match_profiles(_listing(region_id=None), profiles), [])

    def test_state_absent_on_object_fails_a_states_constraint(self):
        listing = SimpleNamespace(region_id=7, category_id=1, start_price="1.00")
        profiles = [_profile({"states": ["apstiprināta"]})]
        self.assertEqual(match_profiles(listing, profiles), [])

    def test_region_id_missing_from_mapping_fails_the_constraint(self):
        listing = {"category_id": 1, "start_price": "1.00", "state": "apstiprināta"}
        profiles = [_profile({"region_ids": [7]})]
        self.assertEqual(match_profiles(listing, profiles), [])


class MultiDimensionAndTest(SimpleTestCase):
    CRITERIA = {"region_ids": [7], "category_ids": [1], "states": ["apstiprināta"]}

    def test_all_dimensions_satisfied_matches(self):
        profiles = [_profile(self.CRITERIA)]
        self.assertEqual(match_profiles(_listing(), profiles), profiles)

    def test_one_failing_key_defeats_the_whole_profile(self):
        profiles = [_profile(self.CRITERIA)]
        self.assertEqual(match_profiles(_listing(category_id=2), profiles), [])


class PriceBoundsTest(SimpleTestCase):
    def test_price_exactly_on_price_min_matches(self):
        profiles = [_profile({"price_min": "25000.00"})]
        self.assertEqual(match_profiles(_listing(start_price="25000.00"), profiles), profiles)

    def test_price_exactly_on_price_max_matches(self):
        profiles = [_profile({"price_max": "25000.00"})]
        self.assertEqual(match_profiles(_listing(start_price="25000.00"), profiles), profiles)

    def test_price_min_only_below_bound_misses(self):
        profiles = [_profile({"price_min": "10000"})]
        self.assertEqual(match_profiles(_listing(start_price="9999.99"), profiles), [])

    def test_price_min_only_above_bound_matches(self):
        profiles = [_profile({"price_min": "10000"})]
        self.assertEqual(match_profiles(_listing(start_price="10000.01"), profiles), profiles)

    def test_price_max_only_above_bound_misses(self):
        profiles = [_profile({"price_max": "10000"})]
        self.assertEqual(match_profiles(_listing(start_price="10000.01"), profiles), [])

    def test_price_max_only_below_bound_matches(self):
        profiles = [_profile({"price_max": "10000"})]
        self.assertEqual(match_profiles(_listing(start_price="9999.99"), profiles), profiles)

    def test_both_bounds_inside_range_matches(self):
        profiles = [_profile({"price_min": "100", "price_max": "50000"})]
        self.assertEqual(match_profiles(_listing(start_price="25000.00"), profiles), profiles)

    def test_start_price_none_fails_any_price_constraint(self):
        for criteria in ({"price_min": "1.00"}, {"price_max": "1.00"}):
            profiles = [_profile(criteria)]
            self.assertEqual(match_profiles(_listing(start_price=None), profiles), [])

    def test_price_bounds_do_not_apply_when_criteria_has_no_price(self):
        profiles = [_profile({"region_ids": [7]})]
        self.assertEqual(match_profiles(_listing(start_price=None), profiles), profiles)


class MultipleProfilesTest(SimpleTestCase):
    def test_returns_the_ordered_matching_subset(self):
        listing = _listing(region_id=7, category_id=1, start_price="25000.00")
        p_all = _profile({})
        p_region_ok = _profile({"region_ids": [7]})
        p_region_bad = _profile({"region_ids": [99]})
        p_price_ok = _profile({"price_min": "1000", "price_max": "30000"})
        p_price_bad = _profile({"price_min": "30000"})
        profiles = [p_all, p_region_bad, p_region_ok, p_price_bad, p_price_ok]

        self.assertEqual(
            match_profiles(listing, profiles), [p_all, p_region_ok, p_price_ok]
        )

    def test_profiles_are_read_by_mapping_access_too(self):
        listing = {"region_id": 7, "category_id": 1, "start_price": "1.00", "state": "x"}
        profiles = [{"criteria": {"region_ids": [7]}}, {"criteria": {"region_ids": [8]}}]
        self.assertEqual(match_profiles(listing, profiles), [profiles[0]])

    def test_no_profiles_yields_empty_list(self):
        self.assertEqual(match_profiles(_listing(), []), [])


class InvalidCriteriaTest(SimpleTestCase):
    def test_unknown_key_raises_value_error(self):
        with self.assertRaises(ValueError):
            match_profiles(_listing(), [_profile({"colour": "blue"})])

    def test_list_field_that_is_not_a_list_raises_value_error(self):
        with self.assertRaises(ValueError):
            match_profiles(_listing(), [_profile({"region_ids": 7})])

    def test_non_decimal_price_min_raises_value_error(self):
        with self.assertRaises(ValueError):
            match_profiles(_listing(), [_profile({"price_min": "abc"})])

    def test_non_decimal_price_max_raises_value_error(self):
        with self.assertRaises(ValueError):
            match_profiles(_listing(), [_profile({"price_max": "not-a-number"})])

    def test_inverted_price_bounds_raise_value_error(self):
        with self.assertRaises(ValueError):
            match_profiles(_listing(), [_profile({"price_min": "50", "price_max": "10"})])
