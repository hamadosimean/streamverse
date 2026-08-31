"""Turning a verified external identity into a StreamVerse user."""
from __future__ import annotations

import logging
import re
import secrets

from django.db import IntegrityError, transaction

from apps.accounts.models import Role, SocialAccount, SocialProvider, User
from apps.accounts.oauth import GoogleAuthError, GoogleIdentity

logger = logging.getLogger(__name__)

#: Leaves room under the model's 30-character ceiling for a disambiguating
#: suffix, so a taken handle never has to be truncated twice.
_USERNAME_SEED_MAX = 24


def _seed_username(identity: GoogleIdentity) -> str:
    """A first guess at a handle, derived from the e-mail's local part.

    It has to satisfy USERNAME_VALIDATOR (`^[a-z0-9][a-z0-9_-]{2,29}$`), and it
    is public — it becomes the channel URL — so dots and plus-addressing are
    stripped rather than mapped to something surprising.
    """
    local = identity.email.split("@", 1)[0].lower()
    seed = re.sub(r"[^a-z0-9_-]+", "", local)
    seed = re.sub(r"^[^a-z0-9]+", "", seed)[:_USERNAME_SEED_MAX]
    # "j.p+news@" reduces to "jp", and anything shorter than three characters
    # cannot be a handle at all.
    return seed if len(seed) >= 3 else "creator"


def _available_username(seed: str) -> str:
    if not User.objects.filter(username=seed).exists():
        return seed
    # Random rather than sequential: `alice-2` advertises that `alice` is taken,
    # and a counter turns signup into a probe for which handles exist.
    for _ in range(8):
        candidate = f"{seed}-{secrets.token_hex(2)}"
        if not User.objects.filter(username=candidate).exists():
            return candidate
    return f"{seed[:16]}-{secrets.token_hex(6)}"


def _preferred_language(identity: GoogleIdentity) -> str:
    """Match Google's locale to a language we actually ship, else the default."""
    return "en" if identity.locale.startswith("en") else "fr"


def _create_from_identity(identity: GoogleIdentity) -> User:
    user = User(
        email=identity.email,
        username=_available_username(_seed_username(identity)),
        display_name=identity.name,
        role=Role.USER,
        preferred_language=_preferred_language(identity),
        # No activation e-mail: Google has already proven the address, and
        # sending one would strand the user on a screen they cannot act on.
        is_active=True,
    )
    # There is no password to check against — sign-in goes through Google. The
    # user can still claim one later via the password-reset flow, which is what
    # `has_usable_password` on the profile is there to advertise.
    user.set_unusable_password()
    try:
        user.save()
    except IntegrityError:
        # Two concurrent first-time sign-ins picked the same handle. One retry
        # against a freshly sampled name is enough; a second collision would
        # mean something else is wrong.
        user.username = _available_username(_seed_username(identity))
        user.save()
    return user


@transaction.atomic
def resolve_google_user(identity: GoogleIdentity) -> tuple[User, bool]:
    """Find, link or create the user behind a verified Google identity.

    Returns `(user, created)`. Three cases, in the order they are tried:

    1. We have seen this Google `sub` before — that link is the answer.
    2. The verified address matches an existing account, including one created
       with a password. Google vouching for the address is exactly the proof the
       activation e-mail would have asked for, so we link rather than refuse:
       otherwise "Sign in with Google" would be a dead end for every user who
       signed up the normal way.
    3. Nobody owns the address. Create the account.
    """
    link = (
        SocialAccount.objects.select_related("user")
        .filter(provider=SocialProvider.GOOGLE, subject=identity.subject)
        .first()
    )

    if link is not None:
        user = _guard(link.user)
        if link.email != identity.email:
            link.email = identity.email
        link.touch()
        return user, False

    user = User.objects.filter(email__iexact=identity.email).first()
    created = user is None
    if created:
        user = _create_from_identity(identity)
    else:
        _guard(user)
        if not user.is_active:
            # Signed up, never clicked the activation link, then came back
            # through Google. The address is proven; let them in.
            user.is_active = True
            user.save(update_fields=["is_active", "updated_at"])

    existing = SocialAccount.objects.filter(
        provider=SocialProvider.GOOGLE, user=user
    ).first()
    if existing is not None:
        # Same address, different `sub`: the Google account behind it was
        # deleted and recreated. Rebinding is exactly as safe as the original
        # link was — both rest on the same verified address — but it is unusual
        # enough to be worth a line in the log.
        logger.info("Rebinding Google identity for user %s: %s -> %s",
                    user.pk, existing.subject, identity.subject)
        existing.subject = identity.subject
        existing.email = identity.email
        existing.save(update_fields=["subject", "email", "updated_at"])
        existing.touch()
        return user, created

    SocialAccount.objects.create(
        user=user,
        provider=SocialProvider.GOOGLE,
        subject=identity.subject,
        email=identity.email,
    )
    return user, created


def _guard(user: User) -> User:
    """Refuse a sign-in the rest of the app would refuse on the next request.

    Issuing a token to a suspended account only to have
    SuspensionAwareJWTAuthentication reject it would look like a broken login
    rather than a moderation decision.
    """
    if user.is_suspended:
        raise GoogleAuthError("account_suspended", "Ce compte est suspendu.")
    return user
