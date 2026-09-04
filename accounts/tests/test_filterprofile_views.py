"""Tests for the FilterProfile list/create views (#12) and edit/delete (#13)."""

import time
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import FilterProfileForm, state_choices
from accounts.models import FilterProfile
from accounts.summaries import summarize_criteria, summarize_preferences
from auctions.models import Category, Listing, Notification, Region

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


# --------------------------------------------------------------------------- #
# Issue #13 — edit and delete views
# --------------------------------------------------------------------------- #


def edit_url(pk):
    return f"/profiles/{pk}/edit/"


def delete_url(pk):
    return f"/profiles/{pk}/delete/"


class EditDeleteMixin(RefDataMixin):
    @classmethod
    def setUpTestData(cls):
        cls.make_ref_data()
        cls.alice = User.objects.create_user("alice", password="pw")
        cls.bob = User.objects.create_user("bob", password="pw")
        cls.profile = FilterProfile.objects.create(
            user=cls.alice,
            name="Rīga flats",
            criteria={
                "region_ids": [7, 96],
                "category_ids": [1],
                "price_min": "10000.00",
                "price_max": "50000.00",
                "states": ["apstiprināta"],
            },
        )
        cls.bob_profile = FilterProfile.objects.create(
            user=cls.bob, name="B-one", criteria={"category_ids": [1]}
        )

    def valid_payload(self, **overrides):
        payload = {
            "name": "Rīga flats",
            "regions": [7],
            "categories": [2],
            "price_min": "20000",
            "price_max": "30000",
            "states": ["apstiprināta"],
        }
        payload.update(overrides)
        return payload


class EditViewAccessTest(EditDeleteMixin, TestCase):
    def test_anonymous_get_is_redirected_to_login(self):
        response = self.client.get(edit_url(self.profile.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))

    def test_anonymous_post_is_redirected_to_login_and_changes_nothing(self):
        response = self.client.post(
            edit_url(self.profile.pk), self.valid_payload()
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.criteria["region_ids"], [7, 96])

    def test_other_users_profile_get_is_404(self):
        self.client.login(username="bob", password="pw")
        response = self.client.get(edit_url(self.profile.pk))
        self.assertEqual(response.status_code, 404)

    def test_other_users_profile_post_is_404_and_changes_nothing(self):
        self.client.login(username="bob", password="pw")
        response = self.client.post(
            edit_url(self.profile.pk), self.valid_payload()
        )
        self.assertEqual(response.status_code, 404)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.criteria["region_ids"], [7, 96])


class EditViewGetTest(EditDeleteMixin, TestCase):
    def setUp(self):
        self.client.login(username="alice", password="pw")

    def test_get_renders_form_prepopulated_from_criteria(self):
        response = self.client.get(edit_url(self.profile.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/filterprofile_form.html")
        form = response.context["form"]
        self.assertIsInstance(form, FilterProfileForm)
        self.assertEqual(form.initial["regions"], [7, 96])
        self.assertEqual(form.initial["categories"], [1])
        self.assertEqual(form.initial["price_min"], "10000.00")
        self.assertEqual(form.initial["price_max"], "50000.00")
        self.assertEqual(form.initial["states"], ["apstiprināta"])

    def test_get_form_posts_back_to_the_edit_url(self):
        response = self.client.get(edit_url(self.profile.pk))
        self.assertContains(response, f'action="{edit_url(self.profile.pk)}"')

    def test_get_prepopulates_only_the_keys_present_in_criteria(self):
        sparse = FilterProfile.objects.create(
            user=self.alice, name="sparse", criteria={"price_min": "5.00"}
        )
        response = self.client.get(edit_url(sparse.pk))
        form = response.context["form"]
        self.assertEqual(form.initial["price_min"], "5.00")
        self.assertEqual(form.initial["regions"], [])
        self.assertEqual(form.initial["categories"], [])
        self.assertIsNone(form.initial["price_max"])
        self.assertEqual(form.initial["states"], [])


class EditViewPostTest(EditDeleteMixin, TestCase):
    def setUp(self):
        self.client.login(username="alice", password="pw")

    def test_valid_post_updates_criteria_bumps_updated_at_and_redirects(self):
        before = FilterProfile.objects.get(pk=self.profile.pk).updated_at
        time.sleep(0.01)
        response = self.client.post(
            edit_url(self.profile.pk), self.valid_payload(), follow=True
        )
        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, "updated")
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.criteria,
            {
                "region_ids": [7],
                "category_ids": [2],
                "price_min": "20000.00",
                "price_max": "30000.00",
                "states": ["apstiprināta"],
            },
        )
        self.assertGreater(self.profile.updated_at, before)

    def test_valid_htmx_post_returns_204_and_hx_redirect(self):
        response = self.client.post(
            edit_url(self.profile.pk),
            self.valid_payload(),
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], LIST_URL)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.criteria["region_ids"], [7])

    def test_invalid_post_no_criteria_is_form_error_and_profile_unchanged(self):
        response = self.client.post(
            edit_url(self.profile.pk),
            {"name": "Rīga flats"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.criteria["region_ids"], [7, 96])

    def test_invalid_htmx_post_rerenders_partial_with_errors(self):
        response = self.client.post(
            edit_url(self.profile.pk),
            {"name": "Rīga flats"},
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/_filterprofile_form.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, "match everything")
        self.assertContains(response, f'hx-post="{edit_url(self.profile.pk)}"')


class DeleteViewTest(EditDeleteMixin, TestCase):
    def make_notification(self, profile, listing, alert_type):
        return Notification.objects.create(
            user=profile.user,
            filter_profile=profile,
            listing=listing,
            alert_type=alert_type,
        )

    def test_anonymous_get_is_redirected_to_login(self):
        response = self.client.get(delete_url(self.profile.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))

    def test_anonymous_post_is_redirected_and_profile_survives(self):
        response = self.client.post(delete_url(self.profile.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))
        self.assertTrue(
            FilterProfile.objects.filter(pk=self.profile.pk).exists()
        )

    def test_get_shows_confirmation_naming_the_profile(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(delete_url(self.profile.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "accounts/filterprofile_confirm_delete.html"
        )
        self.assertContains(response, "Rīga flats")

    def test_post_deletes_profile_keeps_notifications_with_null_link(self):
        self.client.login(username="alice", password="pw")
        listing = make_listing("apstiprināta")
        sent = self.make_notification(
            self.profile, listing, Notification.AlertType.NEW
        )
        pending = self.make_notification(
            self.profile, listing, Notification.AlertType.CHANGED
        )
        other_listing = make_listing("izsludināta")
        untouched = self.make_notification(
            self.bob_profile, other_listing, Notification.AlertType.NEW
        )

        response = self.client.post(delete_url(self.profile.pk), follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertContains(response, "deleted")
        self.assertEqual(response.context["rows"], [])

        self.assertFalse(
            FilterProfile.objects.filter(pk=self.profile.pk).exists()
        )
        for note in (sent, pending):
            note.refresh_from_db()
            self.assertIsNone(note.filter_profile_id)
        untouched.refresh_from_db()
        self.assertEqual(untouched.filter_profile_id, self.bob_profile.pk)
        self.assertEqual(
            Notification.objects.filter(filter_profile__isnull=True).count(), 2
        )

    def test_other_users_profile_get_is_404(self):
        self.client.login(username="bob", password="pw")
        response = self.client.get(delete_url(self.profile.pk))
        self.assertEqual(response.status_code, 404)

    def test_other_users_profile_post_is_404_and_profile_survives(self):
        self.client.login(username="bob", password="pw")
        response = self.client.post(delete_url(self.profile.pk))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            FilterProfile.objects.filter(pk=self.profile.pk).exists()
        )


class ListViewEditDeleteLinksTest(EditDeleteMixin, TestCase):
    def test_rows_carry_edit_and_delete_links(self):
        self.client.login(username="alice", password="pw")
        response = self.client.get(LIST_URL)
        self.assertContains(response, f'href="{edit_url(self.profile.pk)}"')
        self.assertContains(response, f'href="{delete_url(self.profile.pk)}"')
