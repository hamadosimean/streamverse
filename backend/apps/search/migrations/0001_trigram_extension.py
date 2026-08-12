"""Enable pg_trgm.

Needed by the trigram-similarity fallback in `apps.search.services.search_videos`,
which catches near-miss queries that stemming-based full-text search returns
nothing for. Extensions are database-wide, so this lives in the search app even
though the app itself has no models.
"""
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),
    ]
