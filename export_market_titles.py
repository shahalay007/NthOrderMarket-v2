"""Utility script to export all market titles for prompt engineering workflows."""

import argparse
import csv
from pathlib import Path
import sqlite3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export market titles from polymarket.db for taxonomy design"
    )
    parser.add_argument(
        "--db",
        default="polymarket.db",
        help="Path to the Polymarket SQLite database (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default="market_titles.csv",
        help="Output CSV file to write titles into (default: %(default)s)",
    )
    return parser.parse_args()


def export_titles(db_path: str, output_path: Path) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, COALESCE(title, '') AS title FROM events ORDER BY title COLLATE NOCASE;"
    )
    rows = cur.fetchall()
    conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["id", "title"])
        writer.writerows(rows)

    return len(rows)


def main() -> None:
    args = parse_args()
    output_path = Path(args.out)
    count = export_titles(args.db, output_path)
    print(f"Exported {count} titles to {output_path}")


if __name__ == "__main__":
    main()
