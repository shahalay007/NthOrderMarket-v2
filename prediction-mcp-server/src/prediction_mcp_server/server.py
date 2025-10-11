"""FastMCP server exposing prediction market data and Gemini analysis tools."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .db_sync_service import ReadTracker

try:
    from .intelligent_gemini_bot import IntelligentGeminiBot
except ImportError:  # pragma: no cover
    IntelligentGeminiBot = None  # type: ignore


def _get_db_path() -> Path:
    """Resolve the SQLite database path from the environment."""
    raw = os.getenv("PREDICTION_DB_PATH") or "polymarket_read.db"
    return Path(raw).expanduser()


def _get_default_limit(limit: Optional[int] = None) -> int:
    """Return the default limit respecting overrides."""
    if limit is not None and limit > 0:
        return limit

    try:
        value = int(os.getenv("PREDICTION_DEFAULT_LIMIT", "25") or 25)
        return value if value > 0 else 25
    except ValueError:
        return 25


def _ensure_database() -> Path:
    path = _get_db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Prediction markets database not found at {path.resolve()}. "
            "Set PREDICTION_DB_PATH to the read replica."
        )
    return path


def _fetch_rows(sql: str, params: Iterable[Any] = (), fetch_one: bool = False) -> Any:
    """Run a read-only SQL query with read tracking."""
    database = _ensure_database()

    with ReadTracker():
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return cursor.fetchone() if fetch_one else cursor.fetchall()


def _format_price_points(outcome_prices: Optional[str]) -> str:
    if not outcome_prices:
        return "No outcome pricing data."

    try:
        parsed = json.loads(outcome_prices)
    except json.JSONDecodeError:
        return "Outcome prices unavailable (malformed JSON)."

    if isinstance(parsed, dict):
        items = parsed.items()
    elif isinstance(parsed, list):
        items = enumerate(parsed, 1)
    else:
        return "Outcome prices unavailable (unexpected structure)."

    lines = []
    for key, entry in items:
        if isinstance(entry, dict):
            name = entry.get("outcome") or entry.get("name") or f"Outcome {key}"
            price = entry.get("price") or entry.get("probability")
            if price is not None:
                try:
                    price_val = float(price)
                except (TypeError, ValueError):
                    price_val = None
            else:
                price_val = None
        else:
            name = f"Outcome {key}"
            try:
                price_val = float(entry)
            except (TypeError, ValueError):
                price_val = None

        cents = f"{price_val * 100:.1f}¢" if price_val is not None else "n/a"
        lines.append(f"- {name}: {cents}")

    return "\n".join(lines) if lines else "No outcome pricing data."


def _format_timestamp(value: Optional[str]) -> str:
    if not value:
        return "n/a"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


LOG_LEVEL = os.getenv("PREDICTION_MCP_LOG_LEVEL", "INFO")
SERVER_ID = os.getenv("PREDICTION_MCP_SERVER_ID", "prediction-markets")
mcp = FastMCP(SERVER_ID, log_level=LOG_LEVEL)

_gemini_bot: Optional[IntelligentGeminiBot] = None


def _get_gemini_bot() -> IntelligentGeminiBot:
    global _gemini_bot
    if _gemini_bot is not None:
        return _gemini_bot

    if IntelligentGeminiBot is None:
        raise RuntimeError(
            "IntelligentGeminiBot could not be imported. Ensure intelligent_gemini_bot.py is available."
        )

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set; intelligent chat tool is unavailable.")

    _gemini_bot = IntelligentGeminiBot(api_key, db_path=str(_ensure_database()))
    return _gemini_bot


def _market_markdown(row: sqlite3.Row) -> str:
    data = dict(row)
    url = f"https://polymarket.com/event/{data.get('slug')}" if data.get("slug") else "n/a"
    volume = data.get("volume") or 0
    liquidity = data.get("liquidity") or 0

    section_parts = [
        data.get("domain") or "",
        data.get("section") or "",
        data.get("subsection") or "",
    ]
    hierarchy = " › ".join(part for part in section_parts if part)

    return dedent(
        f"""
        **{data.get('title')}**
        • ID: `{data.get('id')}`
        • Slug: `{data.get('slug')}`
        • Category: {hierarchy or 'n/a'}
        • Volume: ${volume:,.0f} | Liquidity: ${liquidity:,.0f}
        • Last Trade: {_format_timestamp(data.get('last_trade_date'))}
        • Updated: {_format_timestamp(data.get('updated_at'))}
        • Outcomes:
        {_format_price_points(data.get('outcome_prices'))}
        • Link: {url}
        """
    ).strip()


@mcp.tool()
async def list_top_markets(
    limit: Optional[int] = None,
    domain_filter: Optional[str] = None,
    sort_by: str = "volume",
) -> str:
    """Return top active markets sorted by volume, liquidity, or recency."""
    order_clauses = {
        "volume": "COALESCE(volume, 0) DESC",
        "liquidity": "COALESCE(liquidity, 0) DESC",
        "updated": "datetime(COALESCE(updated_at, last_trade_date)) DESC",
    }
    order = order_clauses.get(sort_by.lower())
    if not order:
        raise ValueError(f"Unsupported sort_by '{sort_by}'. Use volume, liquidity, or updated.")

    params: List[Any] = []
    filters = ["is_active = 1"]

    if domain_filter:
        like = f"%{domain_filter.lower()}%"
        filters.append(
            "(LOWER(domain) LIKE ? OR LOWER(section) LIKE ? OR LOWER(subsection) LIKE ?)"
        )
        params.extend([like, like, like])

    sql = f"""
        SELECT id, slug, title, domain, section, subsection, volume, liquidity,
               outcome_prices, last_trade_date, updated_at
        FROM events
        WHERE {' AND '.join(filters)}
        ORDER BY {order}
        LIMIT ?
    """
    params.append(_get_default_limit(limit))

    rows = _fetch_rows(sql, params)
    if not rows:
        return "No active markets matched the requested filters."

    sections = [f"{idx+1}. {_market_markdown(row)}" for idx, row in enumerate(rows)]
    return "\n\n".join(sections)


@mcp.tool()
async def search_markets(
    query: str,
    limit: Optional[int] = None,
    include_inactive: bool = False,
) -> str:
    """Search markets by title, description, or slug."""
    if not query or len(query.strip()) < 2:
        raise ValueError("Provide a search query with at least two characters.")

    params: List[Any] = []
    filters = ["(LOWER(title) LIKE ? OR LOWER(description) LIKE ? OR LOWER(slug) LIKE ?)"]
    like = f"%{query.lower()}%"
    params.extend([like, like, like])

    if not include_inactive:
        filters.append("is_active = 1")

    sql = f"""
        SELECT id, slug, title, domain, section, subsection, volume, liquidity,
               outcome_prices, last_trade_date, updated_at
        FROM events
        WHERE {' AND '.join(filters)}
        ORDER BY COALESCE(volume, 0) DESC
        LIMIT ?
    """
    params.append(_get_default_limit(limit))

    rows = _fetch_rows(sql, params)
    if not rows:
        return f"No markets found matching '{query}'."

    results = [f"{idx+1}. {_market_markdown(row)}" for idx, row in enumerate(rows)]
    return "\n\n".join(results)


@mcp.tool()
async def market_details(
    slug: Optional[str] = None,
    event_id: Optional[str] = None,
) -> str:
    """Return detailed information for a specific market."""
    if not slug and not event_id:
        raise ValueError("Provide either a slug or an event_id.")

    if slug:
        sql = """
            SELECT *
            FROM events
            WHERE slug = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """
        params = (slug,)
    else:
        sql = """
            SELECT *
            FROM events
            WHERE id = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """
        params = (event_id,)

    row = _fetch_rows(sql, params, fetch_one=True)
    if not row:
        return "Market not found."

    data = dict(row)

    aux_fields = [
        ("Best Bid", data.get("best_bid")),
        ("Best Ask", data.get("best_ask")),
        ("Open Interest", data.get("open_interest")),
        ("Last Trade Price", data.get("last_trade_price")),
    ]

    extra_lines = []
    for label, value in aux_fields:
        if value is not None:
            extra_lines.append(f"• {label}: {value}")

    return (
        f"{_market_markdown(row)}\n\n"
        f"Additional Metrics:\n"
        + ("\n".join(extra_lines) if extra_lines else "• No additional metrics stored.")
    )


@mcp.tool()
async def market_stats() -> str:
    """Return aggregate statistics for the prediction market dataset."""
    totals = _fetch_rows(
        """
        SELECT
            COUNT(*) AS total_events,
            SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_events,
            SUM(volume) AS total_volume,
            AVG(liquidity) AS avg_liquidity
        FROM events
        """,
        (),
        fetch_one=True,
    )

    if not totals:
        return "No market data available."

    total_events = totals["total_events"] or 0
    active_events = totals["active_events"] or 0
    total_volume = float(totals["total_volume"] or 0)
    avg_liquidity = float(totals["avg_liquidity"] or 0)

    by_domain = _fetch_rows(
        """
        SELECT domain, COUNT(*) AS count, SUM(volume) AS volume
        FROM events
        WHERE is_active = 1
        GROUP BY domain
        ORDER BY CASE WHEN volume IS NULL THEN 1 ELSE 0 END, volume DESC
        LIMIT 10
        """
    )

    lines = [
        "**Dataset Overview**",
        f"- Total events: {int(total_events):,}",
        f"- Active events: {int(active_events):,}",
        f"- Total volume: ${total_volume:,.0f}",
        f"- Avg liquidity (active): ${avg_liquidity:,.0f}",
        "",
        "**Top Domains by Volume (active)**",
    ]

    if by_domain:
        for row in by_domain:
            domain = row["domain"] or "Uncategorized"
            volume = float(row["volume"] or 0)
            count = row["count"] or 0
            lines.append(f"- {domain}: ${volume:,.0f} across {count} markets")
    else:
        lines.append("No active domain breakdown available.")

    return "\n".join(lines)


@mcp.tool()
async def intelligent_market_analysis(question: str) -> str:
    """Answer natural language questions using the IntelligentGeminiBot flow."""
    if not question or len(question.strip()) < 4:
        raise ValueError("Provide a question with at least four characters.")

    bot = _get_gemini_bot()
    try:
        return bot.process_query(question.strip())
    except Exception as exc:  # pragma: no cover
        return f"Intelligent analysis failed: {exc}"


class PredictionMCPServer:
    """CLI-friendly wrapper mirroring the Alpaca MCP server entrypoint."""

    def __init__(self, config_file: Optional[Path] = None) -> None:
        env_config = config_file or Path(
            os.getenv("PREDICTION_CONFIG_FILE", ".env")
        ).expanduser()
        self.config_file = env_config

        if env_config.exists():
            load_dotenv(env_config, override=True)
        else:
            load_dotenv(override=False)

    def run(self, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8001) -> None:
        if transport == "stdio":
            mcp.run()
        else:
            mcp.settings.host = host
            mcp.settings.port = port
            transport_name = "streamable-http" if transport == "http" else transport
            mcp.run(transport=transport_name)
