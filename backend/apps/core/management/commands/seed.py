"""Seed demo data.

Video approach (documented in the README, as the spec asks): the ~15 demo videos
are **really generated and really transcoded**. The command synthesises short
clips with FFmpeg's `lavfi` sources at a deliberate spread of resolutions —
including a portrait clip and one below 240p — and pushes each through the exact
same Celery pipeline a user upload takes. Nothing about the seeded playback path
is faked, and the ladder logic (no upscaling, portrait handling) is exercised on
first boot.

The clips are queued, not transcoded inline, so `docker compose up` returns
promptly. They appear as `ready` over the following minute or two; pass `--wait`
to block until the queue drains.
"""
from __future__ import annotations

import random
import subprocess
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.catalog.models import Category, Tag
from apps.videos.models import Video, VideoStatus, Visibility
from apps.videos.services import pipeline
from apps.videos.tasks import start_transcoding_pipeline

# Deterministic output across runs.
RNG = random.Random(20260811)

CATEGORIES = [
    # (slug, canonical name, lucide icon, accent)
    ("music", "Musique", "music", "#8b5cf6"),
    ("gaming", "Jeux video", "gamepad-2", "#22c55e"),
    ("education", "Education", "graduation-cap", "#3b82f6"),
    ("news", "Actualites", "newspaper", "#ef4444"),
    ("sport", "Sport", "trophy", "#f59e0b"),
    ("tech", "Technologie", "cpu", "#06b6d4"),
    ("cooking", "Cuisine", "chef-hat", "#f97316"),
    ("travel", "Voyage", "plane", "#14b8a6"),
]

TAGS = [
    "tutoriel", "live", "afrique", "burkina", "ouagadougou", "code", "python",
    "django", "react", "musique", "concert", "football", "recette", "vlog",
    "documentaire", "interview", "demo", "test",
]

# (title, category slug, width, height, duration, lavfi video source)
# The resolution spread is the point: it proves the ladder never upscales.
DEMO_VIDEOS = [
    ("Concert live a Ouagadougou", "music", 1920, 1080, 12, "testsrc2"),
    ("Studio session - basse et batterie", "music", 1280, 720, 10, "smptehdbars"),
    ("Speedrun retro - niveau 1", "gaming", 1280, 720, 11, "rgbtestsrc"),
    ("Analyse tactique de la finale", "sport", 1920, 1080, 10, "smptebars"),
    ("Match amateur - resume", "sport", 854, 480, 9, "testsrc"),
    ("Introduction a Django en 10 minutes", "education", 1280, 720, 12, "testsrc2"),
    ("Les bases de l'algebre lineaire", "education", 1280, 720, 10, "gradients"),
    ("Journal du soir - edition speciale", "news", 1920, 1080, 10, "smptehdbars"),
    ("Reportage: marche central", "news", 854, 480, 8, "testsrc"),
    ("Comparatif de cartes graphiques", "tech", 1280, 720, 11, "rgbtestsrc"),
    ("Monter son premier serveur Linux", "tech", 640, 360, 9, "testsrc2"),
    ("Recette du riz gras", "cooking", 1280, 720, 10, "gradients"),
    # Portrait sources: the ladder must scale the short side, not letterbox —
    # and these double as the Shorts feed (vertical + under the duration cap).
    ("Street food en vertical", "cooking", 720, 1280, 8, "testsrc2"),
    ("Une minute a Ouagadougou", "travel", 1080, 1920, 15, "gradients"),
    ("Astuce Django en 20 secondes", "tech", 720, 1280, 20, "rgbtestsrc"),
    ("But de la semaine", "sport", 1080, 1920, 12, "smptehdbars"),
    ("Recette express: le the", "cooking", 720, 1280, 18, "testsrc"),
    ("Beat maison", "music", 1080, 1920, 10, "testsrc2"),
    ("Route du Sahel - carnet de voyage", "travel", 1920, 1080, 12, "mandelbrot"),
    # Below the bottom rung: must produce exactly one native-size rendition.
    ("Archive 1998 - qualite d'epoque", "travel", 320, 180, 8, "testsrc"),
]

COMMENT_TEXTS = [
    "Super video, merci pour le partage !",
    "La qualite d'image est vraiment nette en 1080p.",
    "Quelqu'un sait quel materiel a ete utilise pour filmer ?",
    "J'ai appris beaucoup de choses, continuez comme ca.",
    "Le passage vers la moitie de la video est excellent.",
    "Tres bon rythme, ni trop long ni trop court.",
    "Est-ce qu'il y aura une deuxieme partie ?",
    "Je regarde depuis Ouagadougou, ca marche parfaitement.",
    "Le son pourrait etre un peu plus fort, sinon parfait.",
    "Enfin une explication claire sur ce sujet.",
]

REPLY_TEXTS = [
    "Tout a fait d'accord avec toi.",
    "Merci, c'est note !",
    "Je me posais exactement la meme question.",
    "Oui, une suite est prevue.",
    "Bien vu, je n'avais pas remarque.",
]

DEMO_USERS = [
    # (username, email, display name, role)
    ("admin", "admin@streamverse.local", "Administrateur", Role.ADMIN),
    ("moderateur", "moderator@streamverse.local", "Awa Moderation", Role.MODERATOR),
    ("fatou", "fatou@streamverse.local", "Fatou Diallo", Role.USER),
    ("ibrahim", "ibrahim@streamverse.local", "Ibrahim Sawadogo", Role.USER),
    ("nadia", "nadia@streamverse.local", "Nadia Kabore", Role.USER),
    ("koffi", "koffi@streamverse.local", "Koffi Mensah", Role.USER),
]

DEMO_PASSWORD = "StreamVerse2026!"

# Fixed so the README can document it and an OBS test works immediately.
# A real channel gets a random key from `generate_stream_key()`; this one is a
# demo credential on a throwaway stack and is documented as such.
DEMO_STREAM_KEY = "sv-demo-stream-key-do-not-use-in-production"
DEMO_LIVE_SLUG = "fatou"


class Command(BaseCommand):
    help = "Create demo accounts, categories, tags and ~15 really-transcoded videos."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing demo videos before seeding.")
        parser.add_argument("--wait", action="store_true",
                            help="Block until every seeded video reaches ready/failed.")
        parser.add_argument("--no-videos", action="store_true",
                            help="Seed accounts and catalogue only.")
        parser.add_argument("--wait-timeout", type=int, default=1800)

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        users = self._seed_users()
        categories = self._seed_categories()
        self._seed_tags()

        if options["no_videos"]:
            self._print_credentials()
            return

        if Video.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Des videos existent deja — seeding video ignore. "
                "Utilisez --reset pour repartir de zero."
            ))
            # Still attempt engagement: it is idempotent, and an existing catalogue
            # seeded before Phase 3 has videos but no views/likes/comments.
            self._seed_engagement(users)
            self._seed_live_channel(users, categories)
            self._seed_monetization(users, categories)
            self._seed_library(users)
            self._print_credentials()
            return

        queued = self._seed_videos(users, categories)
        self._seed_engagement(users)
        self._seed_live_channel(users, categories)
        self._seed_monetization(users, categories)
        self._seed_library(users)

        if options["wait"]:
            self._wait_for(queued, options["wait_timeout"])

        self._print_credentials()
        self.stdout.write(self.style.SUCCESS(
            f"\n{len(queued)} videos mises en file de transcodage. "
            "Elles apparaissent comme 'prete' au fur et a mesure "
            "(suivi en direct sur Flower: http://localhost:5574)."
        ))

    # ------------------------------------------------------------------
    def _reset(self):
        self.stdout.write("Suppression des videos existantes...")
        from apps.engagement.models import Report
        from apps.videos.tasks import delete_video_assets

        for video in Video.objects.all():
            delete_video_assets(str(video.pk), video.asset_prefix)

        # Views/likes/comments cascade with the video; reports use a generic FK
        # and would otherwise be left dangling at a target that no longer exists.
        Report.objects.all().delete()
        Video.objects.all().delete()

    def _seed_users(self) -> dict[str, User]:
        users: dict[str, User] = {}
        for username, email, display_name, role in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "display_name": display_name,
                    "role": role,
                    "is_active": True,          # demo accounts skip email activation
                    "is_staff": role == Role.ADMIN,
                    "is_superuser": role == Role.ADMIN,
                    "bio": f"Compte de demonstration StreamVerse ({role}).",
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                self.stdout.write(f"  + utilisateur {username} ({role})")
            users[username] = user
        return users

    def _seed_categories(self) -> dict[str, Category]:
        categories: dict[str, Category] = {}
        for order, (slug, name, icon, accent) in enumerate(CATEGORIES):
            category, created = Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "icon": icon, "accent_color": accent,
                          "display_order": order},
            )
            if created:
                self.stdout.write(f"  + categorie {slug}")
            categories[slug] = category
        return categories

    def _seed_tags(self) -> list[Tag]:
        tags = Tag.resolve(TAGS)
        self.stdout.write(f"  + {len(tags)} tags")
        return tags

    # ------------------------------------------------------------------
    def _generate_clip(self, path: Path, width: int, height: int,
                       duration: int, source: str) -> None:
        """Synthesise a real, decodable MP4 with FFmpeg's test-pattern sources.

        No text overlay on purpose: `drawtext` needs a font file that the slim
        base image does not ship, and a seed that fails on a missing font would
        be worse than one without captions.
        """
        # Length comes from `-t`, never from a `duration=` filter option: several
        # lavfi sources (mandelbrot, life, ...) do not accept one and error out.
        video_input = f"{source}=size={width}x{height}:rate=25"

        frequency = RNG.choice([220, 330, 440, 550, 660])
        cmd = [
            settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", video_input,
            "-f", "lavfi", "-i", f"sine=frequency={frequency}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-t", str(duration),
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not path.exists():
            raise RuntimeError(f"FFmpeg n'a pas pu generer le clip: {result.stderr[-500:]}")

    def _seed_videos(self, users: dict[str, User],
                     categories: dict[str, Category]) -> list[str]:
        uploaders = [users[name] for name in ("fatou", "ibrahim", "nadia", "koffi")]
        all_tags = list(Tag.objects.all())
        queued: list[str] = []

        self.stdout.write("Generation des clips de demonstration (FFmpeg lavfi)...")

        for index, (title, cat_slug, width, height, duration, source) in enumerate(
            DEMO_VIDEOS
        ):
            uploader = uploaders[index % len(uploaders)]

            with transaction.atomic():
                video = Video.objects.create(
                    uploader=uploader,
                    title=title,
                    description=(
                        f"Video de demonstration StreamVerse.\n\n"
                        f"Source synthetique {width}x{height}, {duration} s, "
                        f"generee par FFmpeg puis transcodee par le pipeline reel "
                        f"(ffprobe -> rendus HLS multiples -> miniatures)."
                    ),
                    status=VideoStatus.PROCESSING,
                    visibility=Visibility.PUBLIC,
                    category=categories[cat_slug],
                    original_filename=f"demo-{index:02d}.mp4",
                    original_mime_type="video/mp4",
                    uploaded_at=timezone.now() - timedelta(
                        days=RNG.randint(0, 45), hours=RNG.randint(0, 23)
                    ),
                )
                video.tags.set(RNG.sample(all_tags, k=RNG.randint(2, 4)))

            # One unusable clip must not abort the whole seed: mark that video
            # failed (which is a state the UI already renders correctly) and keep
            # going with the rest.
            try:
                destination = pipeline.local_source_path(video)
                self._generate_clip(destination, width, height, duration, source)
            except Exception as exc:
                video.mark_failed(f"Generation du clip de demonstration echouee: {exc}")
                self.stdout.write(self.style.ERROR(
                    f"  ! [{index + 1:2d}/{len(DEMO_VIDEOS)}] {title}: {exc}"
                ))
                continue

            Video.objects.filter(pk=video.pk).update(
                original_size_bytes=destination.stat().st_size
            )

            start_transcoding_pipeline.delay(str(video.pk))
            queued.append(str(video.pk))
            self.stdout.write(
                f"  + [{index + 1:2d}/{len(DEMO_VIDEOS)}] {title} "
                f"({width}x{height}, {duration}s) -> file de transcodage"
            )

        return queued

    def _seed_engagement(self, users: dict[str, User]) -> None:
        """Create real View / Like / Comment / Report rows.

        Real rows, not fabricated counters: the counters on `Video` are then
        derived from them by the same reconciliation task that runs in
        production, so the demo numbers and the production maths agree.
        """
        from apps.engagement.models import (
            Comment,
            Like,
            Report,
            ReportReason,
            View,
        )
        from django.contrib.contenttypes.models import ContentType

        if View.objects.exists():
            self.stdout.write("  (engagement deja seede)")
            return

        audience = [users[name] for name in
                    ("fatou", "ibrahim", "nadia", "koffi", "moderateur")]
        videos = list(Video.objects.all())

        views, likes, comments = [], [], []

        for video in videos:
            # Views: a plausible spread, all past the qualifying threshold.
            for n in range(RNG.randint(15, 220)):
                viewer = RNG.choice(audience) if RNG.random() < 0.35 else None
                identity = f"u{viewer.pk}" if viewer else f"seed{video.pk}-{n}"
                views.append(
                    View(
                        video=video,
                        viewer=viewer,
                        session_key="" if viewer else f"seed-{n}",
                        ip_hash=View.hash_ip(f"10.0.{n % 255}.{RNG.randint(1, 254)}"),
                        watched_seconds=RNG.randint(30, 600),
                        counted=True,
                        dedup_key=View.build_dedup_key(video.pk, identity, n),
                        created_at=timezone.now() - timedelta(
                            days=RNG.randint(0, 29), hours=RNG.randint(0, 23)
                        ),
                    )
                )

            # Likes: one row per (video, user), heavily positive as is typical.
            for user in RNG.sample(audience, k=RNG.randint(1, len(audience))):
                likes.append(Like(video=video, user=user,
                                  is_like=RNG.random() < 0.85))

            # Comments: top-level plus the occasional reply.
            for _ in range(RNG.randint(0, 4)):
                author = RNG.choice(audience)
                comments.append(
                    Comment(video=video, author=author,
                            content=RNG.choice(COMMENT_TEXTS))
                )

        created_views = View.objects.bulk_create(views, batch_size=1000)
        Like.objects.bulk_create(likes, batch_size=500, ignore_conflicts=True)
        Comment.objects.bulk_create(comments, batch_size=500)

        # `auto_now_add` overrides any created_at passed to bulk_create, so the
        # 30-day spread has to be re-applied with an explicit UPDATE — otherwise
        # every seeded view lands today and the dashboard chart is one spike.
        for view in created_views:
            view.created_at = timezone.now() - timedelta(
                days=RNG.randint(0, 29), hours=RNG.randint(0, 23),
                minutes=RNG.randint(0, 59),
            )
        View.objects.bulk_update(created_views, ["created_at"], batch_size=1000)

        # Replies on a subset of the top-level comments.
        replies = []
        for parent in Comment.objects.filter(parent_comment__isnull=True)[:20]:
            if RNG.random() < 0.5:
                replies.append(
                    Comment(
                        video_id=parent.video_id,
                        author=RNG.choice(audience),
                        parent_comment=parent,
                        content=RNG.choice(REPLY_TEXTS),
                    )
                )
        Comment.objects.bulk_create(replies, batch_size=200)

        reply_counts: dict[int, int] = {}
        for reply in replies:
            reply_counts[reply.parent_comment_id] = (
                reply_counts.get(reply.parent_comment_id, 0) + 1
            )
        for parent_id, count in reply_counts.items():
            Comment.objects.filter(pk=parent_id).update(reply_count=count)

        # A couple of pending items so the Phase 6 moderation queue is not empty.
        video_ct = ContentType.objects.get_for_model(Video)
        comment_ct = ContentType.objects.get_for_model(Comment)
        reported_video = RNG.choice(videos)
        reported_comment = Comment.objects.filter(parent_comment__isnull=True).first()

        Report.objects.get_or_create(
            reporter=users["nadia"], content_type=video_ct,
            object_id=str(reported_video.pk), status="pending",
            defaults={"reason": ReportReason.COPYRIGHT,
                      "details": "La bande son semble etre une oeuvre protegee."},
        )
        if reported_comment:
            Report.objects.get_or_create(
                reporter=users["koffi"], content_type=comment_ct,
                object_id=str(reported_comment.pk), status="pending",
                defaults={"reason": ReportReason.SPAM,
                          "details": "Commentaire promotionnel repete."},
            )

        # Derive the denormalised counters from the rows just created, using the
        # same task that keeps them honest in production.
        from apps.engagement.tasks import reconcile_counters

        result = reconcile_counters()

        self.stdout.write(
            f"  + engagement: {len(views)} vues, {len(likes)} appreciations, "
            f"{len(comments) + len(replies)} commentaires, "
            f"{Report.objects.count()} signalement(s) — "
            f"{result['corrected']} compteur(s) recalcule(s)"
        )

    def _seed_live_channel(self, users: dict[str, User],
                           categories: dict[str, Category]) -> None:
        """One demo live channel with a documented stream key.

        A live stream cannot be seeded meaningfully — it needs an actual RTMP
        push. What the seed *can* do is provision the channel and its key so the
        README's OBS/ffmpeg walkthrough works with no setup.
        """
        from apps.live.models import LiveChannel

        channel, created = LiveChannel.objects.get_or_create(
            user=users["fatou"],
            defaults={
                "slug": DEMO_LIVE_SLUG,
                "title": "Le direct de Fatou",
                "description": "Chaine de demonstration pour tester "
                               "l'ingestion RTMP et le chat en direct.",
                "category": categories.get("tech"),
                "stream_key": DEMO_STREAM_KEY,
            },
        )
        if not created and channel.stream_key != DEMO_STREAM_KEY:
            # Keep the documented key working after a re-seed.
            channel.stream_key = DEMO_STREAM_KEY
            channel.save(update_fields=["stream_key", "updated_at"])

        self.stdout.write(f"  + chaine en direct '{channel.slug}' "
                          f"(cle de flux de demonstration)")

    def _seed_monetization(self, users: dict[str, User],
                           categories: dict[str, Category]) -> None:
        """Plans, two ad campaigns, and active subscriptions bought through the
        mock provider.

        The subscriptions are created by running the **real** payment path —
        checkout, then a signed webhook — rather than by inserting an `active`
        row. A seed that fabricates state proves nothing about the code that
        will run in production.
        """
        from apps.monetization.models import (
            AdCampaign,
            CampaignStatus,
            SubscriptionPlan,
            Transaction,
            TransactionStatus,
            UserSubscription,
        )
        from apps.monetization.services import payments as payment_service

        # ---- plans
        plans = [
            {
                "slug": "sans-pub-mensuel", "name": "Sans publicite - Mensuel",
                "price": 2000, "billing_period": "monthly", "display_order": 1,
                "description": "Regardez tout le catalogue sans aucune publicite.",
                "benefits": ["Aucune publicite", "Lecture en qualite maximale",
                             "Resiliable a tout moment"],
            },
            {
                "slug": "sans-pub-annuel", "name": "Sans publicite - Annuel",
                "price": 20000, "billing_period": "yearly", "display_order": 2,
                "description": "Deux mois offerts par rapport au mensuel.",
                "benefits": ["Aucune publicite", "Lecture en qualite maximale",
                             "2 mois offerts", "Resiliable a tout moment"],
            },
        ]
        for spec in plans:
            SubscriptionPlan.objects.get_or_create(slug=spec["slug"], defaults=spec)
        self.stdout.write(f"  + {len(plans)} formules d'abonnement")

        # ---- ad campaigns
        now = timezone.now()
        campaigns = [
            {
                "advertiser_name": "Faso Telecom", "title": "Forfait internet illimite",
                "placement": "pre_roll", "duration_seconds": 12,
                "skippable_after_seconds": 5, "weight": 2,
                "click_url": "https://example.com/faso-telecom",
            },
            {
                "advertiser_name": "Cafe du Marche", "title": "Le gout de Ouagadougou",
                "placement": "mid_roll", "duration_seconds": 10,
                "skippable_after_seconds": 5, "weight": 1,
                "mid_roll_position": 0.5,
                "click_url": "https://example.com/cafe-du-marche",
            },
        ]
        created_campaigns = 0
        for spec in campaigns:
            campaign, created = AdCampaign.objects.get_or_create(
                advertiser_name=spec["advertiser_name"], title=spec["title"],
                defaults={
                    **spec,
                    "start_date": now - timedelta(days=1),
                    "end_date": now + timedelta(days=60),
                    "impression_cap": 10000,
                    # Active without a creative file would fail validation in the
                    # admin UI; the seed generates one below.
                    "status": CampaignStatus.ACTIVE,
                    "created_by": users["admin"],
                },
            )
            if created:
                self._attach_ad_creative(campaign)
                created_campaigns += 1
        self.stdout.write(f"  + {created_campaigns or len(campaigns)} campagnes publicitaires")

        # ---- subscriptions, bought through the real payment path
        plan = SubscriptionPlan.objects.get(slug="sans-pub-mensuel")
        subscribed = 0
        for username, provider in (("nadia", "orange_money"), ("ibrahim", "wave")):
            user = users[username]
            if UserSubscription.objects.filter(
                user=user, status__in=["pending", "active"]
            ).exists():
                continue
            try:
                payment = payment_service.start_subscription_checkout(
                    user=user, plan=plan, provider_code=provider,
                    payer_identifier="+22670000000",
                )
            except payment_service.CheckoutError:
                continue

            # Settle it synchronously here rather than waiting on the Celery
            # round-trip, but through the same state machine the webhook uses.
            self._settle_seed_payment(payment)
            subscribed += 1

        self.stdout.write(f"  + {subscribed} abonnement(s) actif(s) via le "
                          f"fournisseur simule")

    def _attach_ad_creative(self, campaign) -> None:
        """Generate a real creative image with FFmpeg, like the video seeds."""
        from django.core.files import File

        target = Path(settings.TRANSCODE_WORK_DIR) / f"ad-{campaign.pk}.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"gradients=size=1280x720:rate=1",
            "-frames:v", "1", "-q:v", "4", str(target),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            with target.open("rb") as handle:
                campaign.creative.save(f"ad-{campaign.pk}.jpg", File(handle), save=True)
            target.unlink(missing_ok=True)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f"    ! creative non generee pour {campaign.title}: {exc}"
            ))

    def _settle_seed_payment(self, payment) -> None:
        """Complete a seeded payment through the same code the webhook runs."""
        import json

        from apps.monetization.models import WebhookEvent
        from apps.monetization.services import payments as payment_service

        event = WebhookEvent.objects.create(
            provider=payment.provider,
            event_id=f"seed_{payment.pk}",
            event_type="payment.completed",
            transaction=payment,
            payload={"status": "completed", "amount": payment.amount,
                     "reference": payment.provider_reference},
            signature_valid=True,
        )
        payment_service.apply_webhook_outcome(event)
        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["processed", "processed_at"])

    def _seed_library(self, users: dict[str, User]) -> None:
        """Follows, bookmarks and watch history, so the library pages have
        something in them on first boot."""
        from apps.library.models import Bookmark, Follow, WatchHistoryEntry

        if Follow.objects.exists():
            self.stdout.write("  (bibliotheque deja seedee)")
            return

        people = [users[n] for n in ("fatou", "ibrahim", "nadia", "koffi")]
        follows = 0
        for follower in people:
            for channel in people:
                if follower.pk != channel.pk and RNG.random() < 0.6:
                    Follow.objects.get_or_create(follower=follower, channel=channel)
                    follows += 1

        # Counters are derived from the rows, same as the toggle does.
        for person in people:
            User.objects.filter(pk=person.pk).update(
                follower_count=Follow.objects.filter(channel=person).count(),
                following_count=Follow.objects.filter(follower=person).count(),
            )

        videos = list(Video.objects.all())
        bookmarks, history = 0, 0
        for person in people:
            for video in RNG.sample(videos, k=min(len(videos), RNG.randint(2, 5))):
                Bookmark.objects.get_or_create(user=person, video=video)
                bookmarks += 1
            for video in RNG.sample(videos, k=min(len(videos), RNG.randint(4, 9))):
                progress = RNG.randint(1, max(1, video.duration_seconds))
                WatchHistoryEntry.objects.get_or_create(
                    user=person, video=video,
                    defaults={"progress_seconds": progress,
                              "completed": progress >= video.duration_seconds * 0.95,
                              "last_watched_at": timezone.now() - timedelta(
                                  days=RNG.randint(0, 20), hours=RNG.randint(0, 23))},
                )
                history += 1

        self.stdout.write(f"  + bibliotheque: {follows} abonnements, "
                          f"{bookmarks} favoris, {history} entrees d'historique")

    def _wait_for(self, video_ids: list[str], timeout: int) -> None:
        self.stdout.write("Attente de la fin du transcodage...")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = Video.objects.filter(
                pk__in=video_ids, status=VideoStatus.PROCESSING
            ).count()
            if pending == 0:
                break
            self.stdout.write(f"  {pending} video(s) encore en traitement...")
            time.sleep(5)

        ready = Video.objects.filter(pk__in=video_ids, status=VideoStatus.READY).count()
        failed = Video.objects.filter(pk__in=video_ids, status=VideoStatus.FAILED)
        self.stdout.write(self.style.SUCCESS(f"  {ready} prete(s)."))
        for video in failed:
            self.stdout.write(self.style.ERROR(
                f"  ECHEC {video.title}: {video.failure_reason[:200]}"
            ))

    # ------------------------------------------------------------------
    def _print_credentials(self):
        rtmp = settings.LIVE_RTMP_PUBLIC_URL
        app = settings.LIVE_RTMP_APP

        self.stdout.write("\n" + "=" * 66)
        self.stdout.write(" COMPTES DE DEMONSTRATION / DEMO CREDENTIALS")
        self.stdout.write("=" * 66)
        self.stdout.write(f" Mot de passe commun / shared password : {DEMO_PASSWORD}")
        self.stdout.write("-" * 66)
        for username, email, display_name, role in DEMO_USERS:
            self.stdout.write(f" {role:<10} {email:<34} ({display_name})")
        self.stdout.write("-" * 66)
        self.stdout.write(" DIRECT / LIVE STREAMING — see the README for the full walkthrough")
        self.stdout.write(f"   OBS Server     : {rtmp}/{app}")
        self.stdout.write(f"   OBS Stream Key : {DEMO_LIVE_SLUG}?key={DEMO_STREAM_KEY}")
        self.stdout.write(f"   Watch page     : http://localhost:8110/live/{DEMO_LIVE_SLUG}")
        self.stdout.write("=" * 66)
