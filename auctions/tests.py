from django.test import SimpleTestCase
from django.apps import apps


class SmokeTest(SimpleTestCase):
    def test_auctions_app_is_installed(self):
        self.assertIn('auctions', [app.name for app in apps.get_app_configs()])
