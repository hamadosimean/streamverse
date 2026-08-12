"""Djoser transactional emails, pointed at the React frontend routes."""
from django.conf import settings
from djoser import email


class _FrontendContextMixin:
    def get_context_data(self):
        context = super().get_context_data()
        context["domain"] = settings.FRONTEND_URL.split("://", 1)[-1]
        context["protocol"] = settings.FRONTEND_URL.split("://", 1)[0]
        context["site_name"] = "StreamVerse"
        return context


class ActivationEmail(_FrontendContextMixin, email.ActivationEmail):
    template_name = "email/activation.html"


class PasswordResetEmail(_FrontendContextMixin, email.PasswordResetEmail):
    template_name = "email/password_reset.html"
