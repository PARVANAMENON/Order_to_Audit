"""Back up the configured database to a timestamped file."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Create a timestamped database backup (pg_dump custom format for PostgreSQL, "
        "file copy for SQLite) and prune old backups."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default=str(settings.PROJECT_ROOT / "backups"),
            help="Directory for backup files (default: <project>/backups).",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=14,
            help="Number of most recent backups to keep; 0 disables pruning.",
        )

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"]).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        db = settings.DATABASES["default"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        engine = db["ENGINE"]

        if "postgresql" in engine:
            target = output_dir / f"backup-{stamp}.dump"
            self._pg_dump(db, target)
        elif "sqlite3" in engine:
            name = str(db["NAME"])
            if name == ":memory:" or name.startswith("file:"):
                # In-memory databases (tests, ad-hoc shells) have no file to copy.
                target = output_dir / f"backup-{stamp}.json"
                with target.open("w", encoding="utf-8") as handle:
                    call_command("dumpdata", "--natural-foreign", stdout=handle)
            else:
                source = Path(name)
                if not source.exists():
                    raise CommandError(f"SQLite database not found at {source}")
                target = output_dir / f"backup-{stamp}.sqlite3"
                shutil.copy2(source, target)
        else:
            raise CommandError(f"Unsupported database engine: {engine}")

        self.stdout.write(self.style.SUCCESS(f"Backup written to {target}"))

        keep = options["keep"]
        if keep > 0:
            self._prune(output_dir, keep)

    def _pg_dump(self, db: dict, target: Path) -> None:
        command = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(target),
            "--host",
            str(db.get("HOST") or "localhost"),
            "--port",
            str(db.get("PORT") or "5432"),
            "--username",
            str(db.get("USER") or ""),
            str(db.get("NAME") or ""),
        ]
        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = str(db["PASSWORD"])
        try:
            subprocess.run(command, check=True, env=env, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise CommandError(
                "pg_dump was not found; install the PostgreSQL client tools."
            ) from exc
        except subprocess.CalledProcessError as exc:
            target.unlink(missing_ok=True)
            raise CommandError(f"pg_dump failed: {exc.stderr.strip()}") from exc

        if not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise CommandError("pg_dump produced an empty backup file.")

    def _prune(self, output_dir: Path, keep: int) -> None:
        backups = sorted(
            (
                path
                for path in output_dir.glob("backup-*")
                if path.suffix in {".dump", ".sqlite3", ".json"}
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[keep:]:
            stale.unlink()
            self.stdout.write(f"Pruned old backup {stale.name}")
