"""Tests for the ``accounts`` admin (#15): User + FilterProfile registrations."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.test import TestCase
from django.urls import reverse

from accounts.models import FilterProfile
from accounts.summaries import summarize_criteria

User = get_user_model()


class RegistrationTest(TestCase):
    def test_only_the_expected_accounts_models_are_registered(self):
        registered = {
            model.__name__
            for model in admin.site._registry
            if model._meta.app_label == "accounts"
        }
        self.assertEqual(registered, {"User", "FilterProfile"})

    def test_user_is_registered_with_djangos_useradmin(self):
        self.assertIsInstance(admin.site._registry[User], UserAdmin)


class AdminSmokeTest(TestCase):
    """Every registered accounts model's changelist/add/change pages load (200)."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            "admin", "admin@example.test", "pw"
        )
        cls.user = User.objects.create_user("alice", password="pw")
        cls.profile = FilterProfile.objects.create(
            user=cls.user, name="p", criteria={"states": ["apstiprināta"]}
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_changelist_add_and_change_pages_return_200(self):
        cases = [("user", self.user.pk), ("filterprofile", self.profile.pk)]
        for model_name, pk in cases:
            with self.subTest(model=model_name, page="changelist"):
                url = reverse(f"admin:accounts_{model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)
            with self.subTest(model=model_name, page="add"):
                url = reverse(f"admin:accounts_{model_name}_add")
                self.assertEqual(self.client.get(url).status_code, 200)
            with self.subTest(model=model_name, page="change"):
                url = reverse(f"admin:accounts_{model_name}_change", args=[pk])
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_filterprofile_change_page_shows_the_criteria_summary(self):
        url = reverse("admin:accounts_filterprofile_change", args=[self.profile.pk])

        response = self.client.get(url)

        self.assertContains(response, summarize_criteria(self.profile.criteria))
