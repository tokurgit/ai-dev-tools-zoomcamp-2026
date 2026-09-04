"""Test-only helpers. Never imported by production code.

:class:`RecordingBackend` is the stub :class:`~auctions.email.NotificationBackend`
the #9 tests use — it records every message and never touches the network. It
lives here (under ``tests/``, excluded from coverage) rather than in
``auctions.email`` so it can never be named by ``NOTIFICATION_BACKEND`` in a
real deployment by accident.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class SentMessage:
    to: str
    subject: str
    body: str


class RecordingBackend:
    """Records messages instead of sending them.

    Pass ``fail_for`` a set of recipient addresses to make :meth:`send` raise
    for those batches (simulating a provider error for one email only).
    """

    def __init__(self, *, fail_for=None):
        self.messages = []
        self.fail_for = set(fail_for or ())

    def send(self, to, subject, body):
        if to in self.fail_for:
            raise RuntimeError(f"provider rejected {to}")
        self.messages.append(SentMessage(to=to, subject=subject, body=body))
