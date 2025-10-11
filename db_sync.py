#!/usr/bin/env python3
"""
Database Synchronization Service
Maintains a read-only replica of the main database for query operations.
Updates replica only when there are no active read operations.
"""

import sqlite3
import time
import shutil
import threading
from datetime import datetime
from pathlib import Path

from database import Database

# Database paths
WRITE_DB = "polymarket.db"  # Updated by sync_events.py and update_market_data.py
READ_DB = "polymarket_read.db"  # Read-only replica for queries

# Track active read operations
read_lock = threading.Lock()
active_reads = 0

class ReadTracker:
    """Context manager to track active read operations."""

    def __enter__(self):
        global active_reads
        with read_lock:
            active_reads += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global active_reads
        with read_lock:
            active_reads -= 1

def get_active_reads():
    """Get count of active read operations."""
    with read_lock:
        return active_reads

def sync_databases():
    """Sync write DB to read DB when no active reads."""
    write_db_path = Path(WRITE_DB)
    read_db_path = Path(READ_DB)

    if not write_db_path.exists():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Write DB not found. Initializing {WRITE_DB}...")
        try:
            db = Database(db_path=WRITE_DB)
            db.close()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Created empty write DB with required schema")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Failed to initialize write DB: {e}")
            return False

    # Wait for all active reads to complete
    max_wait = 10  # seconds
    wait_time = 0
    while get_active_reads() > 0 and wait_time < max_wait:
        time.sleep(0.1)
        wait_time += 0.1

    if get_active_reads() > 0:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping sync - {get_active_reads()} active reads")
        return False

    try:
        # Create backup of read DB if it exists
        if read_db_path.exists():
            backup_path = f"{READ_DB}.backup"
            shutil.copy2(READ_DB, backup_path)

        # Copy write DB to read DB
        shutil.copy2(WRITE_DB, READ_DB)

        # Verify the copy
        conn = sqlite3.connect(READ_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events WHERE is_active=1")
        count = cursor.fetchone()[0]
        conn.close()

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Synced {count} active events to read DB")

        # Remove backup on success
        backup_path = Path(f"{READ_DB}.backup")
        if backup_path.exists():
            backup_path.unlink()

        return True

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Sync failed: {e}")

        # Restore from backup if available
        backup_path = Path(f"{READ_DB}.backup")
        if backup_path.exists():
            shutil.copy2(f"{READ_DB}.backup", READ_DB)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Restored read DB from backup")

        return False

def run_sync_service(interval=5):
    """Run continuous sync service."""
    print("=" * 60)
    print("🔄 DATABASE SYNC SERVICE")
    print("=" * 60)
    print(f"Write DB: {WRITE_DB} (updated by scripts)")
    print(f"Read DB:  {READ_DB} (used for queries)")
    print(f"Sync interval: {interval} seconds")
    print("=" * 60)

    # Initial sync
    print("\nPerforming initial sync...")
    if sync_databases():
        print("✓ Initial sync completed\n")
    else:
        print("✗ Initial sync failed\n")

    print(f"Sync service running. Syncing every {interval} seconds when idle...\n")

    while True:
        time.sleep(interval)
        sync_databases()

if __name__ == "__main__":
    run_sync_service(interval=5)
