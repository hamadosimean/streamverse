"""User model and roles.

Email is the login field. `username` is kept because it doubles as the public
channel handle (`/c/<username>`), so it must be unique, URL-safe and stable.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.files.storage import storages
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

USERNAME_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9][a-z0-9_-]{2,29}$",
    message=_(
        "3 a 30 caracteres: minuscules, chiffres, tiret ou underscore, "
        "commencant par une lettre ou un chiffre."
    ),
)


def public_profile_storage():
    """Avatars and banners belong in the PUBLIC bucket.

    A callable rather than `storages["public"]` directly so the storage is
    resolved at runtime and the migration stays serialisable.
    """
    return storages["public"]


class Role(models.TextChoices):
    USER = "user", _("Utilisateur")
    MODERATOR = "moderator", _("Moderateur")
    ADMIN = "admin", _("Administrateur")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, username, password, **extra):
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        if not username:
            raise ValueError("Le nom d'utilisateur est obligatoire.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=username.lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, username, password=None, **extra):
        extra.setdefault("role", Role.USER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, username, password, **extra)

    def create_superuser(self, email, username, password=None, **extra):
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Un superuser doit avoir is_staff et is_superuser a True.")
        return self._create_user(email, username, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    email = models.EmailField(_("adresse e-mail"), unique=True, db_index=True)
    username = models.CharField(
        _("nom d'utilisateur"),
        max_length=30,
        unique=True,
        validators=[USERNAME_VALIDATOR],
        help_text=_("Sert d'identifiant public de la chaine (/c/<username>)."),
    )
    display_name = models.CharField(_("nom affiche"), max_length=80, blank=True)
    bio = models.TextField(_("biographie"), max_length=1000, blank=True)

    # Both images go in the PUBLIC bucket: they are rendered for every visitor of
    # a channel page, so the default (private) storage was wrong twice over — it
    # would sign each URL with an expiry, against the internal `minio:9000` host
    # no browser can resolve. See apps.monetization.models.public_creative_storage
    # for the same reasoning applied to ad creatives.
    avatar = models.ImageField(
        _("avatar"), upload_to="avatars/%Y/%m/", storage=public_profile_storage,
        blank=True, null=True,
    )
    banner = models.ImageField(
        _("banniere"), upload_to="banners/%Y/%m/", storage=public_profile_storage,
        blank=True, null=True,
        help_text=_("Image large affichee en tete de la chaine (16:5 conseille)."),
    )

    location = models.CharField(_("localisation"), max_length=80, blank=True)
    website_url = models.URLField(_("site web"), max_length=200, blank=True)

    role = models.CharField(
        _("role"), max_length=16, choices=Role.choices, default=Role.USER, db_index=True
    )

    # Django plumbing
    is_active = models.BooleanField(
        _("actif"),
        default=False,
        help_text=_("Passe a True apres activation par e-mail."),
    )
    is_staff = models.BooleanField(_("acces admin Django"), default=False)

    # Moderation (Phase 6 acts on these; the gate is enforced from Phase 1).
    is_suspended = models.BooleanField(_("suspendu"), default=False, db_index=True)
    suspension_reason = models.TextField(_("motif de suspension"), blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)

    # Denormalised follow counters, recomputed from the rows on every toggle
    # (see apps.library.services.toggle_follow) rather than incremented, so they
    # cannot drift.
    follower_count = models.PositiveIntegerField(default=0, db_index=True)
    following_count = models.PositiveIntegerField(default=0)

    preferred_language = models.CharField(
        _("langue"), max_length=5, choices=[("fr", "Francais"), ("en", "English")],
        default="fr",
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.display_name or self.username} <{self.email}>"

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        self.username = self.username.lower()
        if not self.display_name:
            self.display_name = self.username
        super().save(*args, **kwargs)

    # -- Role helpers ------------------------------------------------------
    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN or self.is_superuser

    @property
    def is_moderator(self) -> bool:
        return self.role == Role.MODERATOR

    @property
    def is_staff_member(self) -> bool:
        """Moderator or admin — anyone with platform-wide privileges."""
        return self.is_admin or self.is_moderator

    def suspend(self, reason: str) -> None:
        self.is_suspended = True
        self.suspension_reason = reason
        self.suspended_at = timezone.now()
        self.save(update_fields=["is_suspended", "suspension_reason",
                                 "suspended_at", "updated_at"])

    def lift_suspension(self) -> None:
        self.is_suspended = False
        self.suspension_reason = ""
        self.suspended_at = None
        self.save(update_fields=["is_suspended", "suspension_reason",
                                 "suspended_at", "updated_at"])
