"""Google sign-in, using the OAuth 2.0 authorization-code flow with PKCE.

WHY THE REDIRECT FLOW AND NOT GOOGLE IDENTITY SERVICES
------------------------------------------------------
The obvious alternative is Google's `gsi/client` script, which renders the
button and hands the browser an ID token. It would cost us a third-party script
tag and an iframe, which means widening the CSP with
`script-src https://accounts.google.com` and `frame-src https://accounts.google.com`.
That policy is the one thing standing between an injected script and the JWTs in
localStorage (see nginx/templates/default.conf.template), so we pay a redirect
instead of relaxing it. Nothing here requires a single byte of Google JavaScript.

THE SHAPE OF THE FLOW
---------------------
1. The SPA asks for an authorization URL. We mint `state` + a PKCE verifier and
   park them in the cache; only the URL goes to the browser.
2. The browser leaves for Google and comes back to the SPA's callback route with
   `code` + `state`.
3. The SPA posts both here. We redeem the state (single use), exchange the code
   for an ID token over a direct server-to-server call, verify that token, and
   hand back our own JWT pair.

The client secret never leaves the backend, and the code is useless to anyone
who intercepts the redirect: without the PKCE verifier, which only we hold, the
exchange fails.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils.http import url_has_allowed_host_and_scheme
from google.auth.transport import requests as google_transport
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: `openid` gets us the `sub`; the other two get us an e-mail to match on and a
#: name to prefill the profile with. We ask for nothing else — no Drive, no
#: contacts, no offline access — so the consent screen stays a one-liner.
SCOPES = ("openid", "email", "profile")

_STATE_PREFIX = "oauth:google:state:"

#: Reused across requests so the underlying HTTPS session (and its connection
#: pool) survives. Google's signing certificates are still fetched on each
#: verification; that is one extra call to a host we are already talking to in
#: the same request, and it is the price of never holding a stale key.
_transport = google_transport.Request()


class GoogleAuthError(Exception):
    """Anything that makes us refuse the sign-in.

    `code` is a stable string the SPA can branch on; `message` is shown to the
    user as-is.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class GoogleIdentity:
    """The claims we keep out of a verified ID token."""

    subject: str
    email: str
    email_verified: bool
    name: str
    locale: str


def is_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def safe_next(value: str | None) -> str:
    """Reduce a caller-supplied `next` to a same-origin path, or to `/`.

    This value survives a round trip through Google and is fed to the SPA's
    router afterwards, so an unchecked one is an open redirect with an extra
    step. Absolute URLs, protocol-relative `//evil.example` and backslash tricks
    all collapse to the home page.
    """
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if not url_has_allowed_host_and_scheme(value, allowed_hosts=None):
        return "/"
    return value


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_authorization_url(*, next_path: str = "/") -> str:
    """Mint a state + PKCE pair, stash them, and return where to send the user."""
    if not is_configured():
        raise GoogleAuthError("not_configured",
                              "La connexion Google n'est pas configuree.")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)

    cache.set(
        f"{_STATE_PREFIX}{state}",
        {"verifier": verifier, "next": safe_next(next_path)},
        settings.GOOGLE_OAUTH_STATE_TTL_SECONDS,
    )

    query = urlencode({
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        # We never call a Google API on the user's behalf, so there is nothing to
        # refresh: an access token we immediately drop is all we want.
        "access_type": "online",
        # Without this, a user already signed in to exactly one Google account is
        # bounced straight through, which makes "wrong account" unrecoverable.
        "prompt": "select_account",
    })
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


def _redeem_state(state: str) -> dict:
    """Consume a state exactly once and return what was stored with it."""
    key = f"{_STATE_PREFIX}{state}" if state else ""
    stored = cache.get(key) if key else None

    # Read-then-delete is not atomic, but `delete` reporting False means someone
    # else got there first — that replay loses, which is the property we need.
    if not stored or not cache.delete(key):
        raise GoogleAuthError(
            "invalid_state",
            "Cette tentative de connexion a expire. Reessayez.",
        )
    return stored


def _exchange_code(code: str, verifier: str) -> str:
    """Trade the authorization code for an ID token. Returns the raw JWT."""
    try:
        response = requests.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=settings.GOOGLE_OAUTH_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("Google token exchange failed to complete: %s", exc)
        raise GoogleAuthError("provider_unreachable",
                              "Google est injoignable. Reessayez dans un instant.") from exc

    if response.status_code != 200:
        # Google's body names the reason (bad code, reused code, redirect_uri
        # mismatch, bad client credentials). It is operator information, not
        # user information, so it goes to the log rather than to the response.
        logger.warning("Google token exchange rejected (%s): %s",
                       response.status_code, response.text[:500])
        try:
            reason = response.json().get("error") or ""
        except ValueError:
            reason = ""

        # `invalid_client` is a deployment fault, not a transient one: the
        # client id and secret do not match. Reporting it as "try again" would
        # invite a user to retry something that cannot succeed until someone
        # edits the environment, so it is separated out and answered like the
        # unconfigured case. The single most common cause is a second copy of
        # the client id pasted into GOOGLE_OAUTH_CLIENT_SECRET, which must
        # start with `GOCSPX-`.
        if reason == "invalid_client":
            raise GoogleAuthError(
                "client_misconfigured",
                "La connexion Google est mal configuree cote serveur. "
                "Utilisez un autre moyen de connexion en attendant.",
            )

        raise GoogleAuthError("exchange_failed",
                              "Google a refuse cette connexion. Reessayez.")

    id_token = response.json().get("id_token")
    if not id_token:
        raise GoogleAuthError("exchange_failed",
                              "Google n'a pas renvoye d'identite. Reessayez.")
    return id_token


def _verify(raw_id_token: str) -> GoogleIdentity:
    """Check the ID token's signature, issuer, audience and expiry.

    Strictly speaking this is belt and braces: the token arrived over a direct
    TLS call to Google's token endpoint, which OIDC lets a client trust without
    revalidating. It stays because the cost is one request and the failure it
    guards against — us ever accepting a token from somewhere else — is total.
    """
    try:
        claims = google_id_token.verify_oauth2_token(
            raw_id_token,
            _transport,
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:
        logger.warning("Google ID token rejected: %s", exc)
        raise GoogleAuthError("invalid_token",
                              "L'identite renvoyee par Google est invalide.") from exc

    subject = claims.get("sub")
    email = (claims.get("email") or "").lower()
    if not subject or not email:
        raise GoogleAuthError("invalid_token",
                              "Google n'a pas fourni d'adresse e-mail.")

    return GoogleIdentity(
        subject=subject,
        email=email,
        # Google sometimes sends this as the string "true".
        email_verified=str(claims.get("email_verified", "")).lower() == "true",
        name=(claims.get("name") or "").strip()[:80],
        locale=(claims.get("locale") or "").lower(),
    )


def complete(*, code: str, state: str) -> tuple[GoogleIdentity, str]:
    """Run the whole callback half. Returns the identity and where to land."""
    if not is_configured():
        raise GoogleAuthError("not_configured",
                              "La connexion Google n'est pas configuree.")

    stored = _redeem_state(state)
    identity = _verify(_exchange_code(code, stored["verifier"]))

    # An unverified address is not evidence of anything: anyone can attach one to
    # a Google account. Accepting it would let a stranger claim the StreamVerse
    # account that already owns that address.
    if not identity.email_verified:
        raise GoogleAuthError(
            "email_unverified",
            "Cette adresse Google n'est pas verifiee. Verifiez-la puis reessayez.",
        )

    return identity, safe_next(stored.get("next"))
