"""Block until the schema is migrated.

The Celery worker and beat containers start in parallel with the ASGI container
that owns `migrate`. Without this they crash-loop on missing tables.
"""
import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Wait until there are no unapplied migrations."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=300)
        parser.add_argument("--interval", type=int, default=3)

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        while time.monotonic() < deadline:
            try:
                executor = MigrationExecutor(connection)
                targets = executor.loader.graph.leaf_nodes()
                if not executor.migration_plan(targets):
                    self.stdout.write(self.style.SUCCESS("Schema is up to date."))
                    return
                self.stdout.write("Migrations pending; waiting...")
            except Exception as exc:
                self.stdout.write(f"Database not ready yet ({exc}); waiting...")
            time.sleep(options["interval"])

        raise SystemExit("Timed out waiting for migrations to be applied.")
