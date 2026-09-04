"""Tests for the FilterProfile list and create views (issue #12)."""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import FilterProfileForm, state_choices
from accounts.models import FilterProfile
from accounts.summaries import summarize_criteria, summarize_preferences
from auctions.models import Category, Listing, Region

User = get_user_model()

LIST_URL = "/profiles/"
CREATE_URL = "/profiles/new/"
LOGIN_URL = "/accounts/login/"


def make_listing(state, **kwargs):
    defaults = dict(
        source_id=uuid.uuid4(),
        title="x",
        initiated_by="ZTI",
        start_time=timezone.now(),
        end_time=timezone.now(),
        state=state,
        raw_hash="a" * 64,
    )
    defaults.update(kwargs)
    return Listing.objects.create(**defaults)


class RefDataMixin:
    @classmethod
    def make_ref_data(cls):
        cls.riga = Region.objects.create(id=7, name="Rīga")
        cls.kurzeme = Region.objects.create(id=96, name="Kurzeme")
        cls.flats = Category.objects.create(id=1, name="Dzīvokļi")
        cls.houses = Category.objects.create(id=2, name="Mājas")


class ListViewTest(RefDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_ref_data()
        cls.alice = User.objects.create_user("alice", password="pw")
        cls.bob = User.objects.create_user("bob", password="pw")
        cls.a1 = FilterProfile.objects.create(
            user=cls.alice, name="A-one", criteria={"region_ids": [7]}
        )
        cls.a2 = FilterProfile.objects.create(
            user=cls.alice, name="A-two", criteria={"price_min": "100.00"}
        )
        cls.b1 = FilterProfile.objects.create(
            user=cls.bob, name="B-one", criteria={"category_ids": [1]}
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))

    def test_lists_only_the_current_users_profiles(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/filterprofile_list.html")
        self.assertContains(response, "A-one")
        self.assertContains(response, "A-two")
        self.assertNotContains(response, "B-one")

    def test_queryset_is_scoped_and_row_count_matches(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(LIST_URL)
        self.assertEqual(len(response.context["rows"]), 2)

    def test_rows_carry_resolved_criteria_and_preference_summaries(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(LIST_URL)
        self.assertContains(response, "Regions: Rīga")
        self.assertContains(response, "Notify on new listings")

    def test_new_profile_link_is_shown(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(LIST_URL)
        self.assertContains(response, f'href="{CREATE_URL}"')

    def test_empty_state_for_a_user_with_no_profiles(self):
        User.objects.create_user("carol", password="pw")
        self.client.login(username="carol", password="pw")
        response = self.client.get(LIST_URL)
        self.assertEqual(response.context["rows"], [])
        self.assertContains(response, "no filter profiles yet")
        self.assertContains(response, f'href="{CREATE_URL}"')


class CreateViewAccessTest(TestCase):
    def test_anonymous_get_is_redirected_to_login(self):
        response = self.client.get(CREATE_URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))

    def test_anonymous_post_is_redirected_to_login(self):
        response = self.client.post(CREATE_URL, {"name": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))
        self.assertEqual(FilterProfile.objects.count(), 0)


class CreateViewGetTest(RefDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_ref_data()
        cls.alice = User.objects.create_user("alice", password="pw")

    def test_get_renders_the_modelform_and_vendored_htmx(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(CREATE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/filterprofile_form.html")
        self.assertIsInstance(response.context["form"], FilterProfileForm)
        self.assertContains(response, "/static/accounts/htmx.min.js")
        self.assertNotContains(response, "unpkg.com")
        self.assertNotContains(response, "cdn")


class CreateViewPostTest(RefDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_ref_data()
        cls.alice = User.objects.create_user("alice", password="pw")
        cls.bob = User.objects.create_user("bob", password="pw")

    def setUp(self):
        self.client.login(username="alice", password="pw")

    def full_payload(self, **overrides):
        payload = {
            "name": "Rīga flats",
            "regions": [7, 96],
            "categories": [1],
            "price_min": "10000",
            "price_max": "50000",
            "states": ["apstiprināta"],
        }
        payload.update(overrides)
        return payload

    def test_valid_post_creates_profile_and_redirects_with_message(self):
        response = self.client.post(CREATE_URL, self.full_payload(), follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, "created")
        profile = FilterProfile.objects.get()
        self.assertEqual(profile.user, self.alice)
        self.assertEqual(
            profile.criteria,
            {
                "region_ids": [7, 96],
                "category_ids": [1],
                "price_min": "10000.00",
                "price_max": "50000.00",
                "states": ["apstiprināta"],
            },
        )

    def test_user_field_in_post_data_is_ignored(self):
        self.client.post(CREATE_URL, self.full_payload(user=self.bob.pk))
        profile = FilterProfile.objects.get()
        self.assertEqual(profile.user, self.alice)

    def test_new_profile_carries_preference_defaults(self):
        self.client.post(CREATE_URL, self.full_payload())
        profile = FilterProfile.objects.get()
        self.assertIs(profile.notify_new, True)
        self.assertIs(profile.notify_change, False)
        self.assertIs(profile.notify_deadline, False)
        self.assertEqual(profile.deadline_days, 3)
        self.assertEqual(profile.delivery, "digest")

    def test_criteria_serialisation_omits_empty_keys(self):
        self.client.post(
            CREATE_URL, {"name": "only price", "price_min": "500"}
        )
        profile = FilterProfile.objects.get()
        self.assertEqual(profile.criteria, {"price_min": "500.00"})

    def test_post_with_no_criteria_is_a_form_error_and_saves_nothing(self):
        response = self.client.post(CREATE_URL, {"name": "empty"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertFalse(FilterProfile.objects.exists())

    def test_post_with_inverted_price_range_is_a_form_error(self):
        response = self.client.post(
            CREATE_URL,
            {"name": "bad", "price_min": "500", "price_max": "100"},
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertFalse(form.is_valid())
        self.assertIn(
            "price_min must not be greater than price_max.",
            form.non_field_errors()[0],
        )
        self.assertFalse(FilterProfile.objects.exists())


class CreateViewHtmxTest(RefDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_ref_data()
        cls.alice = User.objects.create_user("alice", password="pw")

    def setUp(self):
        self.client.login(username="alice", password="pw")

    def test_invalid_htmx_post_rerenders_partial_with_errors_no_full_page(self):
        response = self.client.post(
            CREATE_URL, {"name": "empty"}, headers={"hx-request": "true"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/_filterprofile_form.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, "match everything")

    def test_valid_htmx_post_returns_hx_redirect_header(self):
        response = self.client.post(
            CREATE_URL,
            {"name": "hx", "price_min": "10"},
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], LIST_URL)
        self.assertEqual(FilterProfile.objects.count(), 1)


class StateChoicesTest(TestCase):
    def test_distinct_db_states_plus_apstiprinata_sorted_blanks_dropped(self):
        make_listing("izsludināta")
        make_listing("izsludināta")
        make_listing("noslēgusies")
        make_listing("")
        self.assertEqual(
            state_choices(),
            [
                ("apstiprināta", "apstiprināta"),
                ("izsludināta", "izsludināta"),
                ("noslēgusies", "noslēgusies"),
            ],
        )

    def test_form_offers_apstiprinata_even_with_no_listings(self):
        form = FilterProfileForm()
        self.assertEqual(
            form.fields["states"].choices,
            [("apstiprināta", "apstiprināta")],
        )

    def test_form_rejects_a_state_not_in_choices(self):
        form = FilterProfileForm(
            {"name": "x", "states": ["not-a-real-state"]}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("states", form.errors)


class SummarizeCriteriaTest(RefDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_ref_data()

    def test_resolves_region_and_category_names(self):
        self.assertEqual(
            summarize_criteria({"region_ids": [7, 96], "category_ids": [1]}),
            "Regions: Rīga, Kurzeme; Categories: Dzīvokļi",
        )

    def test_unknown_reference_ids_drop_out(self):
        self.assertEqual(
            summarize_criteria({"region_ids": [7, 999]}), "Regions: Rīga"
        )

    def test_price_range_both_bounds(self):
        self.assertEqual(
            summarize_criteria({"price_min": "100.00", "price_max": "200.00"}),
            "Price 100.00–200.00",
        )

    def test_price_min_only(self):
        self.assertEqual(
            summarize_criteria({"price_min": "100.00"}), "Price from 100.00"
        )

    def test_price_max_only(self):
        self.assertEqual(
            summarize_criteria({"price_max": "200.00"}), "Price up to 200.00"
        )

    def test_states_only(self):
        self.assertEqual(
            summarize_criteria({"states": ["apstiprināta", "izsludināta"]}),
            "States: apstiprināta, izsludināta",
        )

    def test_empty_criteria_falls_back_to_matches_everything(self):
        self.assertEqual(summarize_criteria({}), "Matches every listing")
        self.assertEqual(summarize_criteria(None), "Matches every listing")


class SummarizePreferencesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")

    def test_default_preferences(self):
        profile = FilterProfile(user=self.user, name="p")
        self.assertEqual(
            summarize_preferences(profile),
            "Notify on new listings; digest delivery",
        )

    def test_all_events_enabled(self):
        profile = FilterProfile(
            user=self.user,
            name="p",
            notify_new=True,
            notify_change=True,
            notify_deadline=True,
            deadline_days=5,
            delivery=FilterProfile.Delivery.IMMEDIATE,
        )
        self.assertEqual(
            summarize_preferences(profile),
            "Notify on new listings, changes, deadline in 5d; immediate delivery",
        )

    def test_no_events_enabled(self):
        profile = FilterProfile(
            user=self.user,
            name="p",
            notify_new=False,
            notify_change=False,
            notify_deadline=False,
        )
        self.assertEqual(
            summarize_preferences(profile),
            "Notify on nothing; digest delivery",
        )
