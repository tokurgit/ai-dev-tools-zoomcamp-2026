"""Tests for the environment-driven settings added in issue #22.

``config/settings.py`` reads every environment-specific value once, at import
time, so exercising different environments means reloading the module itself
(with ``os.environ`` patched first) and inspecting its own attributes —
*not* ``django.conf.settings``, which is configured once per process and
never re-reads the module afterwards. Each test restores the module to
reflect the real process environment in ``tearDown`` so later tests (and any
stray direct read of ``config.settings.X``) aren't left looking at a
reloaded-for-a-test state.
"""

import importlib
import os
import subprocess
import sys
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import BASE_DIR


def _reload_with_env(env):
    """Re-import ``config.settings`` fresh with ``os.environ`` set to *env*.

    A plain ``importlib.reload`` re-executes the module's code in its
    *existing* namespace, so an attribute only set conditionally (like
    ``SECURE_SSL_REDIRECT``, only assigned when ``PRODUCTION``) would leak
    from one test into the next once set. Dropping the module from
    ``sys.modules`` first and re-importing gives every call a genuinely
    fresh namespace.
    """
    with mock.patch.dict(os.environ, env, clear=True):
        sys.modules.pop('config.settings', None)
        return importlib.import_module('config.settings')


class SettingsEnvTest(SimpleTestCase):
    def setUp(self):
        self._real_env = dict(os.environ)

    def tearDown(self):
        # Put the module back to what the real environment produces, so
        # nothing outside this file is left looking at a test-only import.
        _reload_with_env(self._real_env)

    # -- the AC's three named test cases -----------------------------------

    def test_no_env_set_uses_dev_defaults_and_does_not_raise(self):
        mod = _reload_with_env({})

        self.assertFalse(mod.DEBUG)
        self.assertFalse(mod.PRODUCTION)
        self.assertTrue(mod.SECRET_KEY)  # the dev fallback, not raised
        self.assertEqual(mod.ALLOWED_HOSTS, [])
        self.assertEqual(mod.CSRF_TRUSTED_ORIGINS, [])
        self.assertEqual(
            mod.DATABASES['default']['NAME'], str(BASE_DIR / 'db.sqlite3')
        )
        self.assertFalse(hasattr(mod, 'SECURE_SSL_REDIRECT'))

    def test_django_allowed_hosts_parses_comma_separated_and_trims(self):
        mod = _reload_with_env({'DJANGO_ALLOWED_HOSTS': 'a.com, b.com'})
        self.assertEqual(mod.ALLOWED_HOSTS, ['a.com', 'b.com'])

    def test_debug_false_with_no_secret_key_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            _reload_with_env({'DJANGO_DEBUG': 'false'})

    # -- DEBUG / DJANGO_DEBUG truthy parsing ---------------------------------

    def test_debug_true_variants_are_case_insensitive(self):
        for value in ('1', 'true', 'True', 'YES', 'yes'):
            mod = _reload_with_env({'DJANGO_DEBUG': value})
            self.assertTrue(mod.DEBUG, value)
            self.assertFalse(mod.PRODUCTION, value)  # DEBUG=True, not prod

    def test_debug_falsy_values_resolve_to_false(self):
        for value in ('0', 'false', 'no', 'anything-else'):
            # A key is required here: DJANGO_DEBUG present + resolving False
            # is PRODUCTION, which the separate no-key-raises test already
            # covers on its own — this test is only about the bool parsing.
            mod = _reload_with_env(
                {'DJANGO_DEBUG': value, 'DJANGO_SECRET_KEY': 'x'}
            )
            self.assertFalse(mod.DEBUG, value)

    # -- ALLOWED_HOSTS dev-mode default --------------------------------------

    def test_debug_true_with_unset_hosts_defaults_to_localhost(self):
        mod = _reload_with_env({'DJANGO_DEBUG': 'true'})
        self.assertEqual(mod.ALLOWED_HOSTS, ['localhost', '127.0.0.1'])

    def test_empty_allowed_hosts_value_is_an_empty_list(self):
        mod = _reload_with_env({'DJANGO_ALLOWED_HOSTS': ''})
        self.assertEqual(mod.ALLOWED_HOSTS, [])

    # -- CSRF_TRUSTED_ORIGINS -------------------------------------------------

    def test_csrf_trusted_origins_derived_from_allowed_hosts(self):
        mod = _reload_with_env({'DJANGO_ALLOWED_HOSTS': 'example.com,two.example.com'})
        self.assertEqual(
            mod.CSRF_TRUSTED_ORIGINS,
            ['https://example.com', 'https://two.example.com'],
        )

    def test_csrf_trusted_origins_explicit_env_var_wins(self):
        mod = _reload_with_env({
            'DJANGO_ALLOWED_HOSTS': 'example.com',
            'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://custom.example.com',
        })
        self.assertEqual(mod.CSRF_TRUSTED_ORIGINS, ['https://custom.example.com'])

    # -- production posture (DJANGO_DEBUG=false + a real key) ---------------

    def test_production_with_secret_key_enables_secure_settings(self):
        mod = _reload_with_env({
            'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': 'a-real-production-secret-key',
            'DJANGO_ALLOWED_HOSTS': 'example.com',
        })
        self.assertTrue(mod.PRODUCTION)
        self.assertEqual(mod.SECRET_KEY, 'a-real-production-secret-key')
        self.assertEqual(
            mod.SECURE_PROXY_SSL_HEADER, ('HTTP_X_FORWARDED_PROTO', 'https')
        )
        self.assertTrue(mod.SECURE_SSL_REDIRECT)
        self.assertTrue(mod.SESSION_COOKIE_SECURE)
        self.assertTrue(mod.CSRF_COOKIE_SECURE)

    # -- DJANGO_DB_PATH -------------------------------------------------------

    def test_django_db_path_overrides_the_default_sqlite_file(self):
        mod = _reload_with_env({'DJANGO_DB_PATH': '/tmp/custom.sqlite3'})
        self.assertEqual(mod.DATABASES['default']['NAME'], '/tmp/custom.sqlite3')

    # -- app settings untouched by #22 (still env-driven, still working) ----

    def test_app_settings_keep_their_own_defaults(self):
        mod = _reload_with_env({})
        self.assertEqual(mod.NOTIFICATION_BACKEND, 'auctions.email.ConsoleBackend')
        self.assertEqual(
            mod.IZSOLES_CSV_PATH, str(BASE_DIR / 'data' / 'izsoles.csv')
        )


class DeployCheckTest(SimpleTestCase):
    """``manage.py check --deploy`` with production env vars set (issue #22)."""

    def test_check_deploy_reports_no_critical_issues_with_production_env(self):
        env = dict(os.environ)
        env.update({
            'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': 'a-sufficiently-long-production-secret-key',
            'DJANGO_ALLOWED_HOSTS': 'example.com',
        })
        result = subprocess.run(
            [sys.executable, 'manage.py', 'check', '--deploy'],
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode, 0, result.stdout + result.stderr
        )
