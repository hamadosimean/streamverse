"""Create MinIO buckets and apply explicit access policies.

Run from the backend entrypoint on every boot — it is idempotent.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core import storage


class Command(BaseCommand):
    help = "Provision MinIO buckets (public-read + private) with explicit policies."

    def handle(self, *args, **options):
        storage.ensure_buckets()
        self.stdout.write(
            self.style.SUCCESS(
                f"MinIO ready: public='{settings.MINIO_PUBLIC_BUCKET}' (anonymous GET), "
                f"private='{settings.MINIO_PRIVATE_BUCKET}' (signed requests only)"
            )
        )
