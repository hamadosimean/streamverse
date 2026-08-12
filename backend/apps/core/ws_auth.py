"""JWT authentication middleware for Channels.

Browsers cannot set arbitrary headers on a WebSocket handshake, so the access
token travels as a `?token=` query parameter. It is still a short-lived access
token (15 min by default), and every consumer re-checks ownership/membership
after authentication — the token alone never grants access to a group.
"""
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from channels.sessions import CookieMiddleware, SessionMiddleware
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


@database_sync_to_async
def _user_from_token(raw_token: str):
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.models import User

    try:
        token = AccessToken(raw_token)
        user = User.objects.get(pk=token["user_id"])
    except (InvalidToken, TokenError, KeyError, User.DoesNotExist, ValueError):
        return AnonymousUser()

    if not user.is_active or user.is_suspended:
        return AnonymousUser()
    return user


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]

        scope["user"] = await _user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """Session middleware first (harmless, useful for admin-origin sockets), then JWT."""
    return CookieMiddleware(SessionMiddleware(JWTAuthMiddleware(inner)))
