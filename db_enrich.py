"""
Batch enrichment utility for Polymarket events.

Copies `polymarket_read.db` into `polymarket_read_enriched.db`,
then assigns a domain/category label for every market title.
The script mirrors the batching style used by `intelligent_gemini_bot.py`
but falls back to lightweight keyword heuristics when Gemini API access
is not configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import google.generativeai as genai  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    genai = None


DEFAULT_INPUT_DB = "polymarket_read.db"
DEFAULT_OUTPUT_DB = "polymarket_read_enriched.db"
DEFAULT_PROMPT_PATH = "market_categorization_prompt.md"

# Defensive lower-case keyword buckets for heuristic fallback.
KEYWORD_MAP: Dict[int, Sequence[str]] = {
    1: (
        " fc ",
        " vs. ",
        " vs ",
        "premier league",
        "uefa",
        "bundesliga",
        "serie a",
        "laliga",
        "fifa",
        "champions league",
        "mls",
    ),
    2: (
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "super bowl",
        "world series",
        "stanley cup",
        "nba finals",
        "yankees",
        "lakers",
        "cowboys",
    ),
    3: (
        "ufc",
        "mma",
        "boxing",
        "golf",
        "masters",
        "grand slam",
        "tennis",
        "pga",
        "nascar",
        "formula",
        "counter-strike",
        "valorant",
        "league of legends",
        " dota ",
        "cricket",
        "icc",
        "fide",
    ),
    4: (
        " up or down ",
        " price on ",
        "price on ",
        "price above",
        "price below",
        "intraday",
    ),
    5: (
        "token",
        "airdrop",
        "etf",
        "crypto reserve",
        "market cap",
        "fdv",
        "op_cat",
        "op_ctv",
    ),
    6: (
        "senate",
        "governor",
        "president",
        "supreme court",
        "congress",
        "trump",
        "biden",
        "house ",
        "district",
        "mayoral",
        "attorney general",
    ),
    7: (
        " ceasefire",
        "election",
        "presidential election",
        "prime minister",
        "coup",
        "strike on",
        "war",
        "army",
        "nato",
        "eu ",
        "russia",
        "israel",
        "china",
        "ukraine",
    ),
    8: (
        "openai",
        "anthropic",
        "tesla",
        "iphone",
        "ai ",
        "artificial intelligence",
        "product",
        "ipo",
        "launch",
        "robot",
        "meta ",
        "apple",
        "microsoft",
        "google",
    ),
    9: (
        "oscars",
        "grammy",
        "box office",
        "album",
        "movie",
        "season",
        "rotten tomatoes",
        "metacritic",
        "video",
        "youtube",
        "views",
        "celebrity",
        "taylor swift",
        "billboard",
    ),
    10: (
        "inflation",
        "gdp",
        "earnings",
        "revenue",
        "unemployment",
        "cpi",
        "interest rate",
        "fed ",
        "treasury",
        "yield",
    ),
}

CATEGORY_LABELS = {
    1: "Sports: Soccer (Football)",
    2: "Sports: North American Leagues (NHL, MLB, NFL, NBA)",
    3: "Sports: Combat & eSports (Gaming, Fighting, Cricket)",
    4: "Cryptocurrency: Price (Immediate/Daily)",
    5: "Cryptocurrency: Products & Futures (Tokens, ETFs, Price Targets)",
    6: "Politics: U.S. Domestic & Legal",
    7: "Politics: Global & Military Conflict",
    8: "Technology & Business (Product Releases, AI, IPOs)",
    9: "Media & Entertainment (Awards, Celebs, Content Views)",
    10: "Finance & Economics (Earnings, Macro Indicators)",
    11: "Miscellaneous",
}


def _batched(iterable: Sequence[Tuple[str, str]], size: int) -> Iterable[Sequence[Tuple[str, str]]]:
    for start in range(0, len(iterable), size):
        yield iterable[start : start + size]


def _normalize_title(title: str) -> str:
    return " ".join(title.split()).strip()


def _keyword_domain(title: str) -> int:
    lowered = f" {title.lower()} "
    for category, keywords in KEYWORD_MAP.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    if "bitcoin" in lowered or "ethereum" in lowered or "solana" in lowered or "xrp" in lowered:
        return 4
    if "crypto" in lowered or "polymarket" in lowered:
        return 5
    if "weather" in lowered or "temperature" in lowered or "cases" in lowered or "pandemic" in lowered:
        return 11
    return 11


def _extract_json_block(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("JSON array not found in model response")
    return text[start : end + 1]


@dataclass
class ClassificationResult:
    id: str
    category_id: int


class BatchDomainClassifier:
    def __init__(
        self,
        prompt: str,
        model_name: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        temperature: float = 0.2,
    ) -> None:
        self.prompt = prompt.strip()
        self.temperature = temperature
        self.model_name = model_name
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self._model = None
        if self.api_key and genai:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(model_name)

    @property
    def uses_gemini(self) -> bool:
        return self._model is not None

    def classify(self, batch: Sequence[Tuple[str, str]]) -> List[ClassificationResult]:
        if self._model is None:
            return [
                ClassificationResult(event_id, _keyword_domain(title))
                for event_id, title in batch
            ]
        try:
            batch_payload = [
                {"id": event_id, "title": _normalize_title(title)}
                for event_id, title in batch
            ]
            instruction = textwrap.dedent(
                f"""
                {self.prompt}

                Respond with a JSON array of objects in this format:
                [{{"id": "123", "category": 4}}]

                Markets:
                {json.dumps(batch_payload, indent=2)}
                """
            ).strip()
            response = self._model.generate_content(
                instruction,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature,
                ),
            )
            text = response.text or ""
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = json.loads(_extract_json_block(text))
            results = []
            for record in parsed:
                category = int(record.get("category"))
                results.append(ClassificationResult(record["id"], category))
            return results
        except Exception:
            return [
                ClassificationResult(event_id, _keyword_domain(title))
                for event_id, title in batch
            ]


def ensure_output_db(source_db: Path, target_db: Path) -> sqlite3.Connection:
    if target_db.exists():
        target_db.unlink()
    with sqlite3.connect(source_db) as src, sqlite3.connect(target_db) as dst:
        src.backup(dst)
    conn = sqlite3.connect(target_db)
    cursor = conn.execute("PRAGMA table_info(events)")
    columns = [row[1] for row in cursor.fetchall()]
    if "domain" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN domain TEXT")
        conn.commit()
    return conn


def fetch_events(conn: sqlite3.Connection, limit: Optional[int] = None) -> List[Tuple[str, str, Optional[str]]]:
    query = "SELECT id, title, domain FROM events ORDER BY ROWID"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    cursor = conn.execute(query)
    return [(str(event_id), title, domain) for event_id, title, domain in cursor.fetchall()]


def update_domains(
    conn: sqlite3.Connection,
    classifications: Iterable[ClassificationResult],
) -> None:
    cursor = conn.cursor()
    for result in classifications:
        label = CATEGORY_LABELS.get(result.category_id, CATEGORY_LABELS[11])
        cursor.execute(
            "UPDATE events SET domain = ? WHERE id = ?",
            (label, result.id),
        )
    conn.commit()


def process_database(
    input_db: Path,
    output_db: Path,
    prompt_path: Path,
    batch_size: int,
    max_rows: Optional[int],
    skip_existing: bool,
    sleep_seconds: float,
    model_name: str,
    temperature: float,
) -> None:
    prompt = prompt_path.read_text(encoding="utf-8")
    classifier = BatchDomainClassifier(prompt, model_name=model_name, temperature=temperature)
    with sqlite3.connect(input_db) as src_conn:
        events = fetch_events(src_conn, max_rows)
    enriched_conn = ensure_output_db(input_db, output_db)
    to_process = []
    if skip_existing:
        cursor = enriched_conn.execute(
            "SELECT id FROM events WHERE domain IS NOT NULL AND domain <> ''"
        )
        completed_ids = {row[0] for row in cursor.fetchall()}
        to_process = [
            (event_id, title)
            for event_id, title, domain in events
            if event_id not in completed_ids
        ]
    else:
        to_process = [(event_id, title) for event_id, title, domain in events]
    total = len(to_process)
    if not total:
        print("No events require enrichment.")
        return
    print(f"Classifying {total} markets in batches of {batch_size} (Gemini enabled: {classifier.uses_gemini})")
    processed = 0
    for batch_events in _batched(to_process, batch_size):
        classifications = classifier.classify(batch_events)
        update_domains(enriched_conn, classifications)
        processed += len(batch_events)
        percent = (processed / total) * 100
        print(f"Processed {processed}/{total} markets ({percent:.1f}%)")
        if sleep_seconds:
            time.sleep(sleep_seconds)
    enriched_conn.close()
    print(f"Domain enrichment complete. Output saved to {output_db}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch domain enrichment for Polymarket DB.")
    parser.add_argument("--input-db", type=Path, default=Path(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", type=Path, default=Path(DEFAULT_OUTPUT_DB))
    parser.add_argument("--prompt-path", type=Path, default=Path(DEFAULT_PROMPT_PATH))
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-rows", type=int, default=None, help="Optional cap for number of markets processed")
    parser.add_argument("--skip-existing", action="store_true", help="Skip markets that already have a domain value")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional delay between batches")
    parser.add_argument("--model-name", type=str, default="gemini-2.5-flash")
    parser.add_argument("--temperature", type=float, default=0.2)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if not args.prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {args.prompt_path}")
    process_database(
        input_db=args.input_db,
        output_db=args.output_db,
        prompt_path=args.prompt_path,
        batch_size=args.batch_size,
        max_rows=args.max_rows,
        skip_existing=args.skip_existing,
        sleep_seconds=args.sleep,
        model_name=args.model_name,
        temperature=args.temperature,
    )


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
