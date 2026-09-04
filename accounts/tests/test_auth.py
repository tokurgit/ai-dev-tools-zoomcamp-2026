from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

LOGIN_URL = "/accounts/login/"


class HomeViewAccessTest(TestCase):
    def test_anonymous_get_home_redirects_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN_URL))

    def test_authenticated_get_home_renders_placeholder(self):
        User.objects.create_user("alice", password="s3cret-pw!")
        self.client.login(username="alice", password="s3cret-pw!")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertContains(response, "alice")


class LoginViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bob", password="s3cret-pw!")

    def test_login_page_reachable_anonymously(self):
        response = self.client.get(LOGIN_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")

    def test_bad_credentials_rerender_form_with_error_and_stay_anonymous(self):
        response = self.client.post(
            LOGIN_URL, {"username": "bob", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_good_credentials_redirect_to_login_redirect_url_and_authenticate(self):
        response = self.client.post(
            LOGIN_URL, {"username": "bob", "password": "s3cret-pw!"}
        )
        self.assertRedirects(
            response, reverse(settings.LOGIN_REDIRECT_URL), fetch_redirect_response=False
        )
        self.assertEqual(
            int(self.client.session["_auth_user_id"]), self.user.pk
        )


class LogoutViewTest(TestCase):
    def test_logout_clears_session_and_regates_home(self):
        User.objects.create_user("carol", password="s3cret-pw!")
        self.client.login(username="carol", password="s3cret-pw!")

        response = self.client.post("/accounts/logout/")
        self.assertRedirects(
            response,
            reverse(settings.LOGOUT_REDIRECT_URL),
            fetch_redirect_response=False,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

        regated = self.client.get("/")
        self.assertEqual(regated.status_code, 302)
        self.assertTrue(regated.url.startswith(LOGIN_URL))


class PasswordChangeViewTest(TestCase):
    OLD = "old-s3cret-pw!"
    NEW = "new-s3cret-pw!"

    def setUp(self):
        self.user = User.objects.create_user("dave", password=self.OLD)
        self.client.login(username="dave", password=self.OLD)

    def test_password_change_succeeds_and_swaps_the_valid_password(self):
        response = self.client.post(
            "/accounts/password_change/",
            {
                "old_password": self.OLD,
                "new_password1": self.NEW,
                "new_password2": self.NEW,
            },
        )
        self.assertRedirects(response, "/accounts/password_change/done/")

        done = self.client.get("/accounts/password_change/done/")
        self.assertEqual(done.status_code, 200)
        self.assertTemplateUsed(done, "registration/password_change_done.html")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))
        self.assertFalse(self.user.check_password(self.OLD))


class SystemChecksTest(TestCase):
    def test_manage_py_check_is_clean(self):
        call_command("check")

    def test_auth_user_model_points_at_accounts_user(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")


class NoRegistrationRouteTest(TestCase):
    def test_no_signup_or_password_reset_routes(self):
        for path in (
            "/accounts/signup/",
            "/accounts/register/",
            "/accounts/password_reset/",
        ):
            self.assertEqual(self.client.get(path).status_code, 404, path)
