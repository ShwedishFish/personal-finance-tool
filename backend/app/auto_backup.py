"""Daily JSON backups beside the database, restorable with the app's Restore button.

They hold the same data as the database (minus Plaid tokens), so they get the same owner-only
permissions. Nothing is written while the app is empty, so a fresh install doesn't fill the folder.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal, engine
from .models import Account, Plan

KEEP = 14
EVERY = timedelta(days=1)
CHECK_SECONDS = 3600
PATTERN = "finance-backup-*.json"

log = logging.getLogger(__name__)


def backup_dir(bind=None) -> Path | None:
    url = (bind or engine).url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).parent / "backups"


def existing(folder: Path) -> list[Path]:
    return sorted(folder.glob(PATTERN), key=lambda p: p.stat().st_mtime)


def last_backup(folder: Path | None) -> datetime | None:
    files = existing(folder) if folder and folder.exists() else []
    return datetime.fromtimestamp(files[-1].stat().st_mtime) if files else None


def run_if_due(folder: Path | None, session_factory=SessionLocal, now: datetime | None = None) -> Path | None:
    """Write a backup if the newest one is a day old (or missing), then keep only the latest KEEP."""
    from .routers.data import backup_contents

    if folder is None:
        return None
    now = now or datetime.now()
    newest = last_backup(folder)
    if newest and now - newest < EVERY:
        return None
    with session_factory() as session:
        if not any(session.scalars(select(model).limit(1)).first() for model in (Account, Plan)):
            return None
        body = backup_contents(session)

    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    path = folder / f"finance-backup-{now:%Y-%m-%d-%H%M%S}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(body, f, indent=2)
    os.utime(path, (now.timestamp(), now.timestamp()))
    for old in existing(folder)[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


async def keep_backing_up() -> None:
    """Check hourly, so an app left running for days still gets its daily backup."""
    while True:
        try:
            await asyncio.to_thread(run_if_due, backup_dir())
        except Exception:
            log.exception("Automatic backup failed")
        await asyncio.sleep(CHECK_SECONDS)
