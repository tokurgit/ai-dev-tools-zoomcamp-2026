from django.test import SimpleTestCase
from django.urls import reverse


class UrlConfTest(SimpleTestCase):
    def test_admin_url_is_wired(self):
        # Resolving a name forces config/urls.py to import and build urlpatterns.
        self.assertEqual(reverse("admin:index"), "/admin/")
