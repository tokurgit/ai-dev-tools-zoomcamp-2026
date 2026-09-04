"""Tests for :mod:`auctions.email` — the backend interface, backends, factory (#9).

No test performs real network I/O: :class:`ResendBackend` is exercised through
``httpx.MockTransport`` (the pattern from ``test_ingest.py``).
"""

import io
import json
from unittest import mock

import httpx
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from auctions.email import (
    ConsoleBackend,
    NotificationBackend,
    NotificationDeliveryError,
    ResendBackend,
    get_backend,
)


class NotificationBackendInterfaceTest(SimpleTestCase):
    def test_cannot_instantiate_the_abstract_base(self):
        with self.assertRaises(TypeError):
            NotificationBackend()

    def test_base_send_is_a_noop_returning_none(self):
        class Concrete(NotificationBackend):
            def send(self, to, subject, body):
                return super().send(to, subject, body)

        self.assertIsNone(Concrete().send("a@b.test", "s", "b"))


class ConsoleBackendTest(SimpleTestCase):
    def test_writes_recipient_subject_and_body_to_the_given_stream(self):
        stream = io.StringIO()
        ConsoleBackend(stream=stream).send("dst@b.test", "Subject line", "Body text")

        written = stream.getvalue()
        self.assertIn("To: dst@b.test", written)
        self.assertIn("Subject: Subject line", written)
        self.assertIn("Body text", written)

    def test_defaults_to_stdout(self):
        backend = ConsoleBackend()
        with mock.patch("sys.stdout", new=io.StringIO()) as fake_stdout:
            backend.send("dst@b.test", "Hi", "There")
        self.assertIn("Hi", fake_stdout.getvalue())

    def test_never_raises(self):
        # Contract: the console backend always "succeeds".
        self.assertIsNone(ConsoleBackend(stream=io.StringIO()).send("x", "y", "z"))


class ResendBackendTest(SimpleTestCase):
    def _backend(self, handler, **kwargs):
        kwargs.setdefault("api_key", "re_test_key")
        kwargs.setdefault("from_address", "alerts@example.test")
        return ResendBackend(transport=httpx.MockTransport(handler), **kwargs)

    def test_posts_to_resend_with_auth_header_and_json_payload(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["auth"] = request.headers.get("Authorization")
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "abc-123"})

        self._backend(handler).send("user@b.test", "Your alerts", "line 1\nline 2")

        self.assertEqual(seen["url"], "https://api.resend.com/emails")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["auth"], "Bearer re_test_key")
        self.assertEqual(
            seen["payload"],
            {
                "from": "alerts@example.test",
                "to": ["user@b.test"],
                "subject": "Your alerts",
                "text": "line 1\nline 2",
            },
        )

    def test_non_2xx_raises_delivery_error_with_status_and_body(self):
        def handler(request):
            return httpx.Response(422, text="Invalid from address")

        with self.assertRaises(NotificationDeliveryError) as ctx:
            self._backend(handler).send("user@b.test", "s", "b")
        self.assertIn("HTTP 422", str(ctx.exception))
        self.assertIn("Invalid from address", str(ctx.exception))

    @override_settings(
        RESEND_API_KEY="re_from_settings", RESEND_FROM="settings@example.test"
    )
    def test_falls_back_to_settings_for_credentials(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200)

        ResendBackend(transport=httpx.MockTransport(handler)).send(
            "user@b.test", "s", "b"
        )

        self.assertEqual(seen["auth"], "Bearer re_from_settings")
        self.assertEqual(seen["payload"]["from"], "settings@example.test")

    @override_settings(RESEND_API_KEY="", RESEND_FROM="from@example.test")
    def test_missing_api_key_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            ResendBackend()
        self.assertIn("RESEND_API_KEY", str(ctx.exception))

    @override_settings(RESEND_API_KEY="re_key", RESEND_FROM="")
    def test_missing_from_address_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            ResendBackend()
        self.assertIn("RESEND_FROM", str(ctx.exception))


class GetBackendTest(SimpleTestCase):
    @override_settings(NOTIFICATION_BACKEND="auctions.email.ConsoleBackend")
    def test_resolves_the_class_named_by_the_setting(self):
        self.assertIsInstance(get_backend(), ConsoleBackend)

    def test_explicit_path_wins_over_the_setting(self):
        backend = get_backend("auctions.tests.support.RecordingBackend")
        self.assertEqual(type(backend).__name__, "RecordingBackend")

    def test_unknown_path_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            get_backend("auctions.email.NoSuchBackend")
        self.assertIn("NoSuchBackend", str(ctx.exception))
