"""Static files storage.

Why this exists rather than using WhiteNoise's class directly:

Jazzmin's `admin/base.html` contains

    data-theme-base="{% static 'vendor/bootswatch' %}"

— a `{% static %}` call on a **directory**, not a file. It hands the directory
prefix to the client so the theme switcher can build stylesheet URLs in the
browser. Directories never appear in the staticfiles manifest, so a strict
`ManifestStaticFilesStorage` raises

    ValueError: Missing staticfiles manifest entry for 'vendor/bootswatch'

which renders as a **500 on every admin page** — the failure this class fixes.

`manifest_strict = False` is Django's documented escape hatch: a name that is not
in the manifest is returned unchanged instead of raising. Everything that *is* in
the manifest still gets its content hash, so cache-busting is unaffected for
every real asset.

The trade-off is that a genuinely missing static file now 404s at request time
instead of failing loudly at render time. That is the right trade here: the
alternative is an admin nobody can open, and the SPA's own assets are hashed by
Vite and never pass through this storage at all.
"""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class AdminFriendlyManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False
