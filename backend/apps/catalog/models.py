"""Categories and tags.

Translation lives entirely in the frontend i18n bundles — the database stores one
canonical label per row, never parallel `*_fr` / `*_en` columns. The frontend
looks a category up by its stable `slug` (`catalog.category.<slug>`) and falls
back to the stored `name` when a locale has no entry for it, so an admin can add
a category without a code deploy and it still renders sensibly in both languages.
"""
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    name = models.CharField(
        _("nom"), max_length=80,
        help_text=_("Libelle canonique. La traduction affichee vient du frontend, "
                    "cle 'catalog.category.<slug>'."),
    )
    slug = models.SlugField(
        max_length=90, unique=True, db_index=True,
        help_text=_("Cle de traduction cote frontend. Ne pas modifier apres creation."),
    )
    description = models.TextField(_("description"), blank=True)
    # Lucide icon name, rendered by the frontend category chips.
    icon = models.CharField(max_length=40, blank=True, default="clapperboard")
    accent_color = models.CharField(
        max_length=7, blank=True, default="#6366f1",
        help_text=_("Couleur hexadecimale utilisee sur les pastilles de categorie."),
    )
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = _("categorie")
        verbose_name_plural = _("categories")
        ordering = ("display_order", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:90]
        super().save(*args, **kwargs)


class Tag(models.Model):
    name = models.CharField(_("nom"), max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True, db_index=True)
    usage_count = models.PositiveIntegerField(
        default=0, db_index=True,
        help_text=_("Denormalise pour trier les tags populaires sans agregation."),
    )

    class Meta:
        verbose_name = _("tag")
        verbose_name_plural = _("tags")
        ordering = ("-usage_count", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip().lower()
        if not self.slug:
            self.slug = slugify(self.name)[:60]
        super().save(*args, **kwargs)

    @classmethod
    def resolve(cls, names) -> list["Tag"]:
        """Get-or-create a list of tags from free-text names.

        Normalises case/whitespace so `Musique`, `musique ` and `MUSIQUE` are one
        tag rather than three.
        """
        tags = []
        for raw in names:
            cleaned = (raw or "").strip().lower()[:50]
            if not cleaned:
                continue
            tag, _created = cls.objects.get_or_create(
                slug=slugify(cleaned)[:60], defaults={"name": cleaned}
            )
            tags.append(tag)
        return tags
