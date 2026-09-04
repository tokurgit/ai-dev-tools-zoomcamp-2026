from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from accounts.models import FilterProfile, User


class AccountsAppTest(SimpleTestCase):
    def test_accounts_app_is_installed(self):
        self.assertIn("accounts", [app.name for app in apps.get_app_configs()])

    def test_auth_user_model_is_the_custom_user(self):
        self.assertIs(get_user_model(), User)


class FilterProfilePersistenceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")

    POPULATED_CRITERIA = {
        "region_ids": [7, 96],
        "category_ids": [1, 2, 18],
        "price_min": "10000.00",
        "price_max": "50000.00",
        "states": ["apstiprināta"],
    }

    def test_create_save_and_retrieve_with_populated_criteria(self):
        profile = FilterProfile.objects.create(
            user=self.user, name="Rīga flats", criteria=self.POPULATED_CRITERIA
        )

        fetched = FilterProfile.objects.get(pk=profile.pk)
        self.assertEqual(fetched.criteria, self.POPULATED_CRITERIA)
        self.assertEqual(fetched.name, "Rīga flats")
        self.assertEqual(fetched.user, self.user)
        self.assertIsNotNone(fetched.created_at)
        self.assertIsNotNone(fetched.updated_at)

    def test_related_name_is_filter_profiles(self):
        FilterProfile.objects.create(user=self.user, name="A")
        FilterProfile.objects.create(user=self.user, name="B")
        self.assertEqual(self.user.filter_profiles.count(), 2)

    def test_deleting_the_user_cascades_to_profiles(self):
        FilterProfile.objects.create(user=self.user, name="A")
        self.user.delete()
        self.assertEqual(FilterProfile.objects.count(), 0)

    def test_str_is_user_endash_name(self):
        profile = FilterProfile(user=self.user, name="Rīga flats")
        self.assertEqual(str(profile), f"{self.user} – Rīga flats")

    def test_duplicate_name_for_same_user_raises_integrity_error(self):
        FilterProfile.objects.create(user=self.user, name="dupe")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FilterProfile.objects.create(user=self.user, name="dupe")

    def test_same_name_for_different_users_is_allowed(self):
        bob = User.objects.create_user("bob", password="pw")
        FilterProfile.objects.create(user=self.user, name="shared")
        FilterProfile.objects.create(user=bob, name="shared")
        self.assertEqual(FilterProfile.objects.filter(name="shared").count(), 2)

    def test_new_profiles_carry_the_documented_preference_defaults(self):
        profile = FilterProfile.objects.create(user=self.user, name="defaults")
        profile.refresh_from_db()
        self.assertIs(profile.notify_new, True)
        self.assertIs(profile.notify_change, False)
        self.assertIs(profile.notify_deadline, False)
        self.assertEqual(profile.deadline_days, 3)
        self.assertEqual(profile.delivery, "digest")
        self.assertEqual(profile.criteria, {})


class FilterProfileCleanTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("carol", password="pw")

    def _profile(self, criteria):
        return FilterProfile(user=self.user, name="p", criteria=criteria)

    def test_full_criteria_passes_validation(self):
        self._profile(
            {
                "region_ids": [7],
                "category_ids": [1],
                "price_min": "100.00",
                "price_max": "200.00",
                "states": ["apstiprināta"],
            }
        ).full_clean()

    def test_empty_criteria_passes_validation(self):
        self._profile({}).full_clean()

    def test_price_min_without_price_max_passes(self):
        self._profile({"price_min": "100.00"}).full_clean()

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._profile({"colour": "blue"}).full_clean()
        self.assertIn("criteria", ctx.exception.message_dict)

    def test_non_list_list_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._profile({"region_ids": 7}).full_clean()

    def test_inverted_price_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._profile(
                {"price_min": "50000.00", "price_max": "10000.00"}
            ).full_clean()

    def test_non_decimal_price_string_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._profile({"price_min": "abc", "price_max": "5.00"}).full_clean()


class UserModelTest(TestCase):
    def test_user_has_no_extra_fields_beyond_abstract_user(self):
        own_fields = {
            f.name for f in User._meta.get_fields() if f.name != "filter_profiles"
        }
        abstract_fields = {
            "id", "password", "last_login", "is_superuser", "username",
            "first_name", "last_name", "email", "is_staff", "is_active",
            "date_joined", "groups", "user_permissions", "logentry",
        }
        self.assertEqual(own_fields, abstract_fields)
