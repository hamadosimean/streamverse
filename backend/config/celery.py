"""Celery application for StreamVerse.

Two queues:
  * `transcode` — long-running, CPU-bound FFmpeg work. Kept separate so a burst
    of uploads never starves the cheap bookkeeping tasks.
  * `default`   — everything else (cleanup, aggregation, mail).
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("streamverse")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_routes = {
    "videos.transcode.*": {"queue": "transcode"},
    # Recording conversion is FFmpeg work; it belongs with the other CPU-bound
    # jobs, not in front of the cheap bookkeeping tasks.
    "live.convert_recording_to_vod": {"queue": "transcode"},
}

app.conf.beat_schedule = {
    # Sweep tus sessions that were started and never finished, plus their
    # half-written scratch files (Section 10: orphaned-upload cleanup).
    "cleanup-abandoned-uploads": {
        "task": "videos.maintenance.cleanup_abandoned_uploads",
        "schedule": crontab(minute="*/30"),
    },
    # Remove transcode work directories left behind by crashed workers.
    "cleanup-transcode-workdirs": {
        "task": "videos.maintenance.cleanup_stale_workdirs",
        "schedule": crontab(minute=15, hour="*/6"),
    },
    # The denormalised engagement counters are a cache; re-derive them from the
    # source rows so a crash mid-write cannot leave them permanently wrong.
    "reconcile-engagement-counters": {
        "task": "engagement.reconcile_counters",
        "schedule": crontab(minute=20),
    },
    # Pre-aggregate the homepage rails — identical for every visitor, so
    # recomputing them per request is pure waste.
    "refresh-trending-cache": {
        "task": "engagement.refresh_trending_cache",
        "schedule": crontab(minute="*/10"),
    },
    # Safety net for search vectors that changed through a path which did not
    # update them inline (admin edits, data migrations).
    "rebuild-search-index": {
        "task": "engagement.rebuild_search_index",
        "schedule": crontab(minute=45, hour="*/4"),
    },
    # Raw view rows are for dedup and analytics; both lose value quickly and the
    # table would otherwise dwarf everything else.
    "prune-view-rows": {
        "task": "engagement.prune_view_rows",
        "schedule": crontab(minute=0, hour=4),
    },
    # `runOnNotReady` is best-effort: if MediaMTX is killed it never fires and a
    # channel would advertise a stream nobody can watch. MediaMTX's own API is
    # the source of truth.
    "reconcile-live-state": {
        "task": "live.reconcile_live_state",
        "schedule": crontab(minute="*/2"),
    },
    # Raw recordings are redundant once converted; the Video holds the durable
    # copy in object storage.
    "cleanup-old-recordings": {
        "task": "live.cleanup_old_recordings",
        "schedule": crontab(minute=30, hour=4),
    },
    # A mobile-money push the payer ignores produces no callback at all; without
    # this the subscription sits pending forever and the user cannot retry.
    "sweep-stale-payments": {
        "task": "monetization.sweep_stale_payments",
        "schedule": crontab(minute="*/10"),
    },
    # Renewals create a NEW pending payment and wait for confirmation, exactly
    # like a first purchase.
    "process-renewals": {
        "task": "monetization.process_renewals",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "expire-subscriptions": {
        "task": "monetization.expire_subscriptions",
        "schedule": crontab(minute=5, hour="*"),
    },
    "expire-campaigns": {
        "task": "monetization.expire_campaigns",
        "schedule": crontab(minute=25),
    },
    # Campaign counters are a cache on a hot path; re-derive them from the
    # impression rows.
    "aggregate-ad-stats": {
        "task": "monetization.aggregate_ad_stats",
        "schedule": crontab(minute=40),
    },
    "revenue-snapshot": {
        "task": "monetization.revenue_snapshot",
        "schedule": crontab(minute=50, hour="*"),
    },
}


@app.task(bind=True, name="core.debug_ping")
def debug_ping(self):
    """Trivial liveness task, handy from Flower."""
    return {"task_id": self.request.id, "status": "pong"}
