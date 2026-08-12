"""PostgreSQL full-text search over the video catalogue.

No external search service. `Video.search_vector` is a `tsvector` column with a
GIN index, built from three weighted fields:

    A  title        — a match here should beat a match anywhere else
    B  tags         — curated, high-signal
    C  description  — long and noisy, so it ranks lowest

Why the vector is stored rather than computed per query: computing
`to_tsvector(title || description)` at query time forces a sequential scan over
the whole table because no index can cover it. A stored column with a GIN index
turns the same search into an index lookup.

**Scope note:** this is stemming-based matching, not typo tolerance. "Djngo"
finds nothing. A trigram-similarity fallback (below) catches near-misses, but if
you need real fuzzy search, Meilisearch or Elasticsearch is the upgrade path —
that is a genuinely different capability, not a tuning knob.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramWordSimilarity,
)
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.db.models.functions import Greatest

from apps.videos.models import Video

logger = logging.getLogger(__name__)

# Below this rank a full-text hit is noise rather than a result.
MIN_RANK = 0.01
# Below this trigram similarity, a "did you mean" guess is worse than nothing.
MIN_SIMILARITY = 0.2


def search_config() -> str:
    return settings.SEARCH_LANGUAGE_CONFIG


def build_vector(video: Video):
    """Weighted tsvector for one video.

    Tags are joined into a single string and fed through `Value` rather than a
    column reference, because they live in a many-to-many table that
    `SearchVector` cannot traverse.
    """
    config = search_config()
    tag_text = " ".join(video.tags.values_list("name", flat=True))

    return (
        SearchVector(Value(video.title or ""), weight="A", config=config)
        + SearchVector(Value(tag_text), weight="B", config=config)
        + SearchVector(Value(video.description or ""), weight="C", config=config)
    )


def update_search_vector(video: Video) -> None:
    """Recompute and store one video's vector.

    Called whenever title/description/tags change, and by the
    `engagement.rebuild_search_index` beat task as a safety net.
    """
    Video.objects.filter(pk=video.pk).update(search_vector=build_vector(video))


def search_videos(query: str, queryset=None):
    """Rank public, ready videos against a query string.

    Two passes, deliberately:

    1. Full-text with `websearch` parsing, so a user can type `"exact phrase"`
       and `-excluded` and have it mean what it means everywhere else.
    2. If that returns nothing, trigram similarity on the title — which rescues
       a misspelling or a partial word that stemming missed.

    The second pass only runs when the first is empty, so the common case never
    pays for it.
    """
    query = (query or "").strip()
    base = queryset if queryset is not None else Video.objects.publicly_listed()

    if not query:
        return base.none(), "empty"

    config = search_config()
    search_query = SearchQuery(query, config=config, search_type="websearch")

    results = (
        base.annotate(rank=SearchRank(F("search_vector"), search_query))
        .filter(search_vector=search_query, rank__gte=MIN_RANK)
        .order_by("-rank", "-view_count")
    )

    if results.exists():
        return results, "fulltext"

    # Fallback: fuzzy match. Word-level similarity, not whole-string: comparing
    # "concrt" against the entire title "Concert live a Ouagadougou" scores near
    # zero because most of the string is unmatched, whereas word similarity
    # compares against the closest word in it and scores the near-miss properly.
    fuzzy = (
        base.annotate(
            similarity=Greatest(
                TrigramWordSimilarity(query, "title"),
                TrigramWordSimilarity(query, "description"),
            )
        )
        .filter(similarity__gte=MIN_SIMILARITY)
        .order_by("-similarity", "-view_count")
    )

    if fuzzy.exists():
        return fuzzy, "fuzzy"

    return base.none(), "none"


def related_videos(video: Video, limit: int = 12):
    """Content-based related videos: shared tags first, then same category.

    **This is not a recommendation engine.** There is no collaborative filtering,
    no watch-history modelling and no personalisation — two different viewers get
    the same list for the same video. Stated plainly here and in the README
    rather than dressed up as something it is not.
    """
    tag_ids = list(video.tags.values_list("id", flat=True))

    candidates = (
        Video.objects.publicly_listed()
        .exclude(pk=video.pk)
        .with_related()
    )

    if not tag_ids and video.category_id is None:
        # Nothing to relate on — fall back to recent popular videos rather than
        # showing an empty rail.
        return candidates.order_by("-view_count", "-published_at")[:limit]

    return (
        candidates.filter(Q(tags__in=tag_ids) | Q(category_id=video.category_id))
        .annotate(
            shared_tags=Count("tags", filter=Q(tags__in=tag_ids), distinct=True),
            same_category=Case(
                When(category_id=video.category_id, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        # Shared tags dominate: a video tagged the same way is a closer match
        # than one that merely shares a broad category like "Music".
        .order_by("-shared_tags", "-same_category", "-view_count", "-published_at")
        .distinct()[:limit]
    )
