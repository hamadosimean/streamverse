"""Outbound transactional mail, off the request path.

Activation and password-reset messages used to be handed to the SMTP server
inline, which was harmless against a local catcher and is not against a real
provider: Gmail's TLS handshake plus delivery is comfortably a second or two,
every one of them spent holding the signup request open, and a provider hiccup
turned a successful account creation into a 500.

Here the account is created, the message is queued, and the request ends. If the
provider is briefly unavailable the task retries; if it is misconfigured, the
failure lands in the worker log with the reason attached instead of in the
user's face.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


#: 30s, then 60s, then 120s. Long enough to ride out a restart on the provider's
#: side, short enough that an activation link is still worth clicking. The delay
#: is computed rather than declared: Celery's `retry_backoff` only applies to
#: `autoretry_for`, and an explicit `self.retry()` without a countdown silently
#: falls back to `default_retry_delay` (three minutes, three times over).
_RETRY_BASE_SECONDS = 30


@shared_task(name="accounts.send_email", bind=True, max_retries=3)
def send_email(self, *, subject: str, body: str, to: list[str],
               html_body: str = "", from_email: str | None = None) -> str:
    """Send one already-rendered message.

    Takes rendered text rather than a template name and a context: the context
    holds a User and a signed token, and neither belongs in a broker payload
    that is serialised as JSON and may sit in Redis for a while.
    """
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=to,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")

    try:
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - retried below, then logged
        logger.warning("Could not send %r to %s: %s", subject, to, exc)
        # A wrong password or a refused sender will fail identically on every
        # attempt; the retries cost nothing and the final failure is loud.
        raise self.retry(
            exc=exc, countdown=_RETRY_BASE_SECONDS * 2 ** self.request.retries
        ) from exc

    logger.info("Sent %r to %s", subject, to)
    return "sent"
