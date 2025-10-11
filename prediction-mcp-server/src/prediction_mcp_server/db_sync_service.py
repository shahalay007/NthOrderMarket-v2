"""Utility to sync write database to read-only replica for fast queries."""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .database import _resolve_db_path

DEFAULT_READ_DB = "polymarket_read.db"

_read_lock = threading.Lock()
_active_reads = 0


class ReadTracker:
    """Context manager used by services to pause sync during reads."""

    def __enter__(self) -> "ReadTracker":
        global _active_reads
        with _read_lock:
            _active_reads += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        global _active_reads
        with _read_lock:
            _active_reads -= 1


def get_active_reads() -> int:
    with _read_lock:
        return _active_reads


def _get_paths(
    write_db: Optional[str] = None,
    read_db: Optional[str] = None,
) -> tuple[Path, Path]:
    write_path = Path(_resolve_db_path(write_db))
    read_path = Path(
        read_db or
        os.getenv("PREDICTION_DB_PATH") or
        os.getenv("PREDICTION_READ_DB_PATH") or
        DEFAULT_READ_DB
    ).expanduser().resolve()
    return write_path, read_path


def sync_databases(
    write_db: Optional[str] = None,
    read_db: Optional[str] = None,
    wait_for_reads: bool = True,
    max_wait: float = 10.0,
) -> bool:
    """Copy the write database to the read replica once."""
    write_path, read_path = _get_paths(write_db, read_db)

    if not write_path.exists():
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.touch()

    if wait_for_reads:
        waited = 0.0
        while get_active_reads() > 0 and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        if get_active_reads() > 0:
            print(
                f"[{datetime.now():%H:%M:%S}] Skipping sync ({get_active_reads()} active reads)"
            )
            return False

    try:
        backup_path = read_path.with_suffix(read_path.suffix + ".backup")
        if read_path.exists():
            shutil.copy2(read_path, backup_path)

        read_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(write_path, read_path)

        with sqlite3.connect(read_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM events WHERE is_active=1")
            count = cur.fetchone()[0]

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] ✓ Synced {count} active events to read DB")

        if backup_path.exists():
            backup_path.unlink()
        return True
    except Exception as exc:
        print(f"[{datetime.now():%H:%M:%S}] ✗ Sync failed: {exc}")
        return False


def run_sync_service(
    *,
    interval: float = 5.0,
    write_db: Optional[str] = None,
    read_db: Optional[str] = None,
) -> None:
    """Start a background loop copying the write DB into the read replica."""
    write_path, read_path = _get_paths(write_db, read_db)
    print("=" * 50)
    print("🔄 Prediction DB Sync Service")
    print("=" * 50)
    print(f"Write DB : {write_path}")
    print(f"Read DB  : {read_path}")
    print(f"Interval : {interval} seconds")
    print("=" * 50)

    sync_databases(write_db, read_db)
    print("Sync service running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(interval)
            sync_databases(write_db, read_db)
    except KeyboardInterrupt:
        print("\nStopping sync service.")
