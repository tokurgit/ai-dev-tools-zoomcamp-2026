"""Provider-agnostic notification email delivery.

:class:`NotificationBackend` is the seam: one method, ``send(to, subject,
body)``, that raises on failure. Two implementations ship here —
:class:`ConsoleBackend` (prints to a stream, the local-dev default) and
:class:`ResendBackend` (POSTs to the Resend HTTP API over ``httpx``, no SDK).
The stub used by the test suite lives in the tests, never here, so it can never
be selected in a real deployment.

:func:`get_backend` resolves the active backend from
``settings.NOTIFICATION_BACKEND`` (a dotted path). An unknown or un-importable
path raises :class:`~django.core.exceptions.ImproperlyConfigured` there and
then — before any notification row is touched — not part-way through a run.
"""

from __future__ import annotations

import abc
import sys

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


class NotificationDeliveryError(RuntimeError):
    """A backend could not deliver a message (network failure or non-2xx)."""


class NotificationBackend(abc.ABC):
    """Interface every email backend implements."""

    @abc.abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Deliver one plain-text message. Raise on any failure to deliver."""


class ConsoleBackend(NotificationBackend):
    """Write the message to a stream (``sys.stdout`` by default).

    For local development and the default when ``NOTIFICATION_BACKEND`` is
    unset. Never raises, so batches always land as ``sent``.
    """

    def __init__(self, *, stream=None):
        self.stream = stream

    def send(self, to: str, subject: str, body: str) -> None:
        stream = self.stream if self.stream is not None else sys.stdout
        stream.write(
            "=" * 40 + "\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            "\n"
            f"{body}\n"
            + "=" * 40 + "\n"
        )


class ResendBackend(NotificationBackend):
    """Deliver through the Resend API (https://resend.com/docs/api-reference).

    API key and from-address come from ``settings.RESEND_API_KEY`` /
    ``settings.RESEND_FROM`` (populated from the environment) unless passed
    explicitly. Both are required — a missing one raises
    :class:`~django.core.exceptions.ImproperlyConfigured` at construction, so
    the failure surfaces when the backend is resolved, not mid-send. A non-2xx
    response raises :class:`NotificationDeliveryError`.

    ``transport`` is a test injection seam (an ``httpx`` transport); production
    leaves it ``None`` for the real network transport — the same pattern as
    :func:`auctions.ingest.fetch.fetch_csv`.
    """

    api_url = "https://api.resend.com/emails"

    def __init__(
        self, *, api_key=None, from_address=None, timeout=10.0, transport=None
    ):
        self.api_key = api_key if api_key is not None else settings.RESEND_API_KEY
        self.from_address = (
            from_address if from_address is not None else settings.RESEND_FROM
        )
        self.timeout = timeout
        self.transport = transport
        if not self.api_key:
            raise ImproperlyConfigured(
                "RESEND_API_KEY is not set; ResendBackend cannot send email"
            )
        if not self.from_address:
            raise ImproperlyConfigured(
                "RESEND_FROM is not set; ResendBackend cannot send email"
            )

    def send(self, to: str, subject: str, body: str) -> None:
        payload = {
            "from": self.from_address,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(
            timeout=self.timeout, transport=self.transport
        ) as client:
            response = client.post(self.api_url, json=payload, headers=headers)
        if response.status_code // 100 != 2:
            raise NotificationDeliveryError(
                f"Resend API returned HTTP {response.status_code}: {response.text}"
            )


def get_backend(path=None):
    """Instantiate the notification backend named by *path*.

    *path* defaults to ``settings.NOTIFICATION_BACKEND``. Raises
    :class:`~django.core.exceptions.ImproperlyConfigured` if the dotted path
    cannot be imported.
    """
    path = path if path is not None else settings.NOTIFICATION_BACKEND
    try:
        backend_class = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"NOTIFICATION_BACKEND={path!r} could not be imported: {exc}"
        ) from exc
    return backend_class()
