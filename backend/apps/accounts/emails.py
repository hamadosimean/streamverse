"""Djoser transactional emails: pointed at the React routes, sent off-request.

Two things happen here that Djoser does not do on its own.

`domain` and `protocol` are overridden so links land on the SPA rather than on
the Django host — the activation and reset URLs are React routes, and nothing
serves them on the API origin.

`send()` is diverted through Celery. Djoser calls it inside the signup and
password-reset requests, and a real provider's TLS handshake and delivery is
seconds of that request; a provider hiccup used to turn a created account into a
500 with no way to resend. Queuing makes the response immediate and the failure
retryable. Set EMAIL_ASYNC=0 to go back to sending inline, which is easier to
follow when debugging a new SMTP configuration.
"""
import logging

from django.conf import settings
from djoser import email

from apps.accounts.tasks import send_email

logger = logging.getLogger(__name__)


class _FrontendEmailMixin:
    def get_context_data(self):
        context = super().get_context_data()
        context["domain"] = settings.FRONTEND_URL.split("://", 1)[-1]
        context["protocol"] = settings.FRONTEND_URL.split("://", 1)[0]
        context["site_name"] = settings.SITE_NAME
        return context

    def _rendered_parts(self) -> tuple[str, str]:
        """The text and HTML halves of the message, after `render()`.

        templated_mail puts the `text_body` block in `self.body` and attaches
        `html_body` as an alternative — unless the template has no text block at
        all, in which case it moves the HTML into the body and flips
        `content_subtype`. Both shapes are handled so a template that later
        drops its text half degrades to an HTML-only mail rather than to a mail
        whose body is raw markup.
        """
        if self.content_subtype == "html":
            return "", self.body
        for content, mimetype in self.alternatives:
            if mimetype == "text/html":
                return self.body, content
        return self.body, ""

    def send(self, to, *args, **kwargs):
        if not settings.EMAIL_ASYNC:
            return super().send(to, *args, **kwargs)

        # Rendering stays here: the context holds a User object and a signed
        # token, neither of which belongs in a JSON broker payload sitting in
        # Redis. Only the finished text crosses that boundary.
        self.render()
        body, html_body = self._rendered_parts()
        recipients = list(to)
        from_email = kwargs.get("from_email") or settings.DEFAULT_FROM_EMAIL

        try:
            send_email.delay(
                subject=self.subject,
                body=body,
                html_body=html_body,
                to=recipients,
                from_email=from_email,
            )
        except Exception:  # noqa: BLE001 - broker down; see below
            # The queue is the optimisation, not the requirement. If the broker
            # cannot be reached, sending inline is slower but still delivers,
            # and that is strictly better than losing an activation link.
            logger.warning("Could not queue %r for %s; sending inline.",
                           self.subject, recipients, exc_info=True)
            return super().send(to, *args, **kwargs)
        return None


class ActivationEmail(_FrontendEmailMixin, email.ActivationEmail):
    template_name = "email/activation.html"


class PasswordResetEmail(_FrontendEmailMixin, email.PasswordResetEmail):
    template_name = "email/password_reset.html"
