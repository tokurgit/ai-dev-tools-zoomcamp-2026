"""The ``criteria`` schema constants have exactly one source (issue #26)."""

from django.test import SimpleTestCase

from accounts.models import FilterProfile
from auctions import criteria, matching


class CriteriaSchemaSourceTests(SimpleTestCase):
    def test_model_and_matcher_share_the_allowed_keys_object(self):
        self.assertIs(FilterProfile.ALLOWED_CRITERIA_KEYS, criteria.ALLOWED_KEYS)
        self.assertIs(matching.ALLOWED_CRITERIA_KEYS, criteria.ALLOWED_KEYS)

    def test_model_and_matcher_share_the_list_key_set(self):
        self.assertIs(FilterProfile.LIST_CRITERIA_KEYS, criteria.LIST_KEYS)
        self.assertEqual(tuple(matching._LIST_DIMENSIONS), criteria.LIST_KEYS)

    def test_criteria_module_is_model_free(self):
        import inspect

        self.assertNotIn("django", inspect.getsource(criteria))
