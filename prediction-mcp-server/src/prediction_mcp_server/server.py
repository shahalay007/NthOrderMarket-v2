"""FastMCP server exposing prediction market data and Gemini/ChatGPT analysis tools."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

from .db_sync_service import ReadTracker

try:
    from .intelligent_gemini_bot import IntelligentGeminiBot
except ImportError:  # pragma: no cover
    IntelligentGeminiBot = None  # type: ignore

# Try to import the multi-platform bot
try:
    import sys
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from intelligent_multi_platform_bot import IntelligentMultiPlatformBot
except ImportError:  # pragma: no cover
    IntelligentMultiPlatformBot = None  # type: ignore


def _get_db_path() -> Path:
    """Resolve the SQLite database path from the environment."""
    raw = os.getenv("PREDICTION_DB_PATH") or "polymarket_read.db"
    return Path(raw).expanduser()


def _get_kalshi_db_path() -> Path:
    """Resolve the Kalshi SQLite database path from the environment."""
    raw = os.getenv("KALSHI_DB_PATH") or "kalshi_read.db"
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
_multi_platform_bot: Optional[Any] = None  # IntelligentMultiPlatformBot type
_openai_client: Optional[OpenAI] = None


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


def _get_multi_platform_bot() -> Any:
    """Get or create the multi-platform bot instance."""
    global _multi_platform_bot
    if _multi_platform_bot is not None:
        return _multi_platform_bot

    if IntelligentMultiPlatformBot is None:
        raise RuntimeError(
            "IntelligentMultiPlatformBot could not be imported. "
            "Ensure intelligent_multi_platform_bot.py is in the project root."
        )

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set; intelligent multi-platform search is unavailable.")

    polymarket_db = str(_ensure_database())
    kalshi_db = str(_ensure_kalshi_database())

    _multi_platform_bot = IntelligentMultiPlatformBot(
        api_key,
        polymarket_db_path=polymarket_db,
        kalshi_db_path=kalshi_db
    )
    return _multi_platform_bot


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


def _get_openai_client() -> OpenAI:
    """Return a cached OpenAI client instance."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set; ChatGPT market analysis is unavailable.")

    _openai_client = OpenAI(api_key=api_key)
    return _openai_client


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "then",
    "there",
    "they",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "markets",
    "market",
    "prediction",
    "show",
    "list",
    "give",
}


def _extract_keywords(text: str, limit: int = 6) -> List[str]:
    """Extract rough keywords from user input for SQL filtering."""
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    keywords: List[str] = []
    for token in tokens:
        normalized = token.strip("'")
        if (
            len(normalized) >= 3
            and normalized not in _STOPWORDS
            and normalized not in keywords
        ):
            keywords.append(normalized)
        if len(keywords) >= limit:
            break
    return keywords


def _fetch_market_context(question: str, limit: int = 15) -> List[sqlite3.Row]:
    """Return a compact set of markets relevant to the user's question."""
    keywords = _extract_keywords(question)

    params: List[Any] = []
    filters = ["is_active = 1"]

    if keywords:
        keyword_clauses = []
        for kw in keywords:
            like = f"%{kw}%"
            keyword_clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(description) LIKE ? OR LOWER(slug) LIKE ? "
                "OR LOWER(domain) LIKE ? OR LOWER(section) LIKE ? OR LOWER(subsection) LIKE ?)"
            )
            params.extend([like, like, like, like, like, like])
        filters.append("(" + " OR ".join(keyword_clauses) + ")")

    sql = f"""
        SELECT id, slug, title, domain, section, subsection, volume, liquidity, updated_at
        FROM events
        WHERE {' AND '.join(filters)}
        ORDER BY COALESCE(volume, 0) DESC, datetime(COALESCE(updated_at, last_trade_date)) DESC
        LIMIT ?
    """
    params.append(limit)

    rows = _fetch_rows(sql, params)
    if rows:
        return rows

    # Fallback: top markets by volume when no keyword hits
    return _fetch_rows(
        """
        SELECT id, slug, title, domain, section, subsection, volume, liquidity, updated_at
        FROM events
        WHERE is_active = 1
        ORDER BY COALESCE(volume, 0) DESC
        LIMIT ?
        """,
        (min(limit, 20),),
    )


def _format_chatgpt_context(rows: Iterable[sqlite3.Row]) -> str:
    """Format market rows into concise bullet points for ChatGPT prompts."""
    lines = []
    for idx, row in enumerate(rows, 1):
        data = dict(row)
        hierarchy = " › ".join(
            part
            for part in (
                data.get("domain"),
                data.get("section"),
                data.get("subsection"),
            )
            if part
        )
        volume = data.get("volume") or 0
        liquidity = data.get("liquidity") or 0
        url = f"https://polymarket.com/event/{data.get('slug')}" if data.get("slug") else "n/a"
        lines.append(
            dedent(
                f"""
                {idx}. {data.get('title')}
                   • Category: {hierarchy or 'n/a'}
                   • Volume: ${volume:,.0f} | Liquidity: ${liquidity:,.0f}
                   • URL: {url}
                """
            ).strip()
        )
    return "\n".join(lines) if lines else "No specific markets matched the query."


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
    """Search markets by title, description, or slug. Falls back to intelligent AI search if no SQL results."""
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
    
    # If no SQL results, fall back to intelligent bot for semantic search
    if not rows:
        try:
            bot = _get_gemini_bot()
            return bot.process_query(query.strip())
        except Exception as exc:
            return f"No exact matches found. Intelligent search also failed: {exc}"

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


@mcp.tool()
async def chatgpt_market_analysis(question: str, limit: Optional[int] = None, model: Optional[str] = None) -> str:
    """Answer market questions with ChatGPT using Polymarket context."""
    if not question or len(question.strip()) < 4:
        raise ValueError("Provide a question with at least four characters.")

    rows = _fetch_market_context(question, limit or 15)
    context = _format_chatgpt_context(rows)
    prompt = dedent(
        f"""
        You are a prediction market analyst. Use only the market context provided below plus the user question.
        Prefer concrete market references, relevant metrics, and clear takeaways. If the context lacks an answer, say so.

        User question:
        {question.strip()}

        Market context:
        {context}
        """
    ).strip()

    client = _get_openai_client()
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    loop = asyncio.get_running_loop()

    def _call_openai() -> str:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert on prediction markets. "
                        "Ground answers in the supplied Polymarket context."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        if not response.choices:
            return "ChatGPT returned no response."
        return response.choices[0].message.content.strip()

    try:
        answer = await loop.run_in_executor(None, _call_openai)
    except Exception as exc:  # pragma: no cover
        return f"ChatGPT analysis failed: {exc}"

    header = "**ChatGPT Analysis**"
    return f"{header}\n\n{answer}"


# === Kalshi-specific tools ===

def _ensure_kalshi_database() -> Path:
    """Ensure Kalshi database exists and return its path."""
    path = _get_kalshi_db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Kalshi database not found at {path.resolve()}. "
            "Set KALSHI_DB_PATH to the Kalshi read replica."
        )
    return path


def _fetch_kalshi_rows(sql: str, params: Iterable[Any] = (), fetch_one: bool = False) -> Any:
    """Run a read-only SQL query on Kalshi database."""
    database = _ensure_kalshi_database()

    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        return cursor.fetchone() if fetch_one else cursor.fetchall()


def _kalshi_market_markdown(row: sqlite3.Row) -> str:
    """Format a Kalshi market row as markdown."""
    data = dict(row)
    ticker = data.get("ticker", "n/a")
    volume = data.get("volume") or 0
    liquidity = data.get("liquidity") or 0
    yes_bid = data.get("yes_bid")
    yes_ask = data.get("yes_ask")

    # Format prices
    price_str = "n/a"
    if yes_bid is not None and yes_ask is not None:
        price_str = f"Yes: {yes_bid}¢ bid / {yes_ask}¢ ask"
    elif yes_bid is not None:
        price_str = f"Yes: {yes_bid}¢ bid"
    elif yes_ask is not None:
        price_str = f"Yes: {yes_ask}¢ ask"

    status = data.get("status", "unknown")
    category = data.get("category") or "Uncategorized"

    return dedent(
        f"""
        **{data.get('title')}**
        • Ticker: `{ticker}`
        • Category: {category}
        • Status: {status}
        • Volume: ${volume:,.0f} | Liquidity: ${liquidity:,.0f}
        • Prices: {price_str}
        • Close: {_format_timestamp(data.get('close_time'))}
        • Link: https://kalshi.com/markets/{ticker}
        """
    ).strip()


@mcp.tool()
async def list_kalshi_markets(
    limit: Optional[int] = None,
    category_filter: Optional[str] = None,
    sort_by: str = "volume",
    group_by_event: bool = True,
) -> str:
    """Return top active Kalshi markets sorted by volume, liquidity, or close time.

    Args:
        limit: Maximum number of results to return
        category_filter: Filter by category name
        sort_by: Sort by 'volume', 'liquidity', or 'close_time'
        group_by_event: If True, groups contracts by event_ticker and sums volumes (default: True)
    """
    order_clauses = {
        "volume": "COALESCE(total_volume, 0) DESC" if group_by_event else "COALESCE(volume, 0) DESC",
        "liquidity": "COALESCE(total_liquidity, 0) DESC" if group_by_event else "COALESCE(liquidity, 0) DESC",
        "close_time": "datetime(close_time) ASC",
    }
    order = order_clauses.get(sort_by.lower())
    if not order:
        raise ValueError(f"Unsupported sort_by '{sort_by}'. Use volume, liquidity, or close_time.")

    params: List[Any] = []
    filters = ["is_active = 1"]

    if category_filter:
        filters.append("LOWER(category) LIKE ?")
        params.append(f"%{category_filter.lower()}%")

    if group_by_event:
        # Group by event_ticker and sum volumes/liquidity
        sql = f"""
            SELECT
                event_ticker,
                MAX(ticker) as ticker,
                MAX(title) as title,
                MAX(category) as category,
                MAX(status) as status,
                SUM(COALESCE(volume, 0)) as total_volume,
                SUM(COALESCE(liquidity, 0)) as total_liquidity,
                SUM(COALESCE(open_interest, 0)) as total_open_interest,
                MAX(yes_bid) as yes_bid,
                MAX(yes_ask) as yes_ask,
                MAX(close_time) as close_time,
                COUNT(*) as contract_count
            FROM kalshi_markets
            WHERE {' AND '.join(filters)}
            GROUP BY event_ticker
            ORDER BY {order}
            LIMIT ?
        """
    else:
        # Original query - individual contracts
        sql = f"""
            SELECT ticker, title, category, status, volume as total_volume, liquidity as total_liquidity,
                   yes_bid, yes_ask, close_time, open_interest as total_open_interest, 1 as contract_count
            FROM kalshi_markets
            WHERE {' AND '.join(filters)}
            ORDER BY {order}
            LIMIT ?
        """

    params.append(_get_default_limit(limit))

    rows = _fetch_kalshi_rows(sql, params)
    if not rows:
        return "No active Kalshi markets matched the requested filters."

    sections = []
    for idx, row in enumerate(rows):
        data = dict(row)
        # Format with grouped data
        ticker = data.get("ticker", "n/a")
        volume = data.get("total_volume") or 0
        liquidity = data.get("total_liquidity") or 0
        contract_count = data.get("contract_count", 1)

        yes_bid = data.get("yes_bid")
        yes_ask = data.get("yes_ask")

        price_str = "n/a"
        if yes_bid is not None and yes_ask is not None:
            price_str = f"Yes: {yes_bid}¢ bid / {yes_ask}¢ ask"
        elif yes_bid is not None:
            price_str = f"Yes: {yes_bid}¢ bid"
        elif yes_ask is not None:
            price_str = f"Yes: {yes_ask}¢ ask"

        status = data.get("status", "unknown")
        category = data.get("category") or "Uncategorized"

        contract_info = f" ({contract_count} contracts)" if group_by_event and contract_count > 1 else ""

        market_str = dedent(
            f"""
            **{data.get('title')}**{contract_info}
            • Ticker: `{ticker}`
            • Category: {category}
            • Status: {status}
            • Volume: ${volume:,.0f} | Liquidity: ${liquidity:,.0f}
            • Prices: {price_str}
            • Close: {_format_timestamp(data.get('close_time'))}
            • Link: https://kalshi.com/markets/{ticker}
            """
        ).strip()

        sections.append(f"{idx+1}. {market_str}")

    return "\n\n".join(sections)


@mcp.tool()
async def search_kalshi_markets(
    query: str,
    limit: Optional[int] = None,
    include_inactive: bool = False,
) -> str:
    """Search Kalshi markets by title or subtitle."""
    if not query or len(query.strip()) < 2:
        raise ValueError("Provide a search query with at least two characters.")

    params: List[Any] = []
    filters = ["(LOWER(title) LIKE ? OR LOWER(subtitle) LIKE ?)"]
    like = f"%{query.lower()}%"
    params.extend([like, like])

    if not include_inactive:
        filters.append("is_active = 1")

    sql = f"""
        SELECT ticker, title, category, status, volume, liquidity,
               yes_bid, yes_ask, close_time, open_interest
        FROM kalshi_markets
        WHERE {' AND '.join(filters)}
        ORDER BY COALESCE(volume, 0) DESC
        LIMIT ?
    """
    params.append(_get_default_limit(limit))

    rows = _fetch_kalshi_rows(sql, params)
    if not rows:
        return f"No Kalshi markets found matching '{query}'."

    results = [f"{idx+1}. {_kalshi_market_markdown(row)}" for idx, row in enumerate(rows)]
    return "\n\n".join(results)


@mcp.tool()
async def kalshi_market_details(ticker: str) -> str:
    """Return detailed information for a specific Kalshi market by ticker."""
    if not ticker:
        raise ValueError("Provide a ticker.")

    sql = """
        SELECT *
        FROM kalshi_markets
        WHERE ticker = ?
        LIMIT 1
    """

    row = _fetch_kalshi_rows(sql, (ticker,), fetch_one=True)
    if not row:
        return f"Kalshi market '{ticker}' not found."

    data = dict(row)

    aux_fields = [
        ("Event Ticker", data.get("event_ticker")),
        ("Market Type", data.get("market_type")),
        ("Subtitle", data.get("subtitle")),
        ("Open Interest", data.get("open_interest")),
        ("No Bid", f"{data.get('no_bid')}¢" if data.get("no_bid") is not None else None),
        ("No Ask", f"{data.get('no_ask')}¢" if data.get("no_ask") is not None else None),
        ("Last Price", f"{data.get('last_price')}¢" if data.get("last_price") is not None else None),
        ("Open Time", _format_timestamp(data.get("open_time"))),
        ("Expiration", _format_timestamp(data.get("expiration_time"))),
        ("Result", data.get("result")),
    ]

    extra_lines = []
    for label, value in aux_fields:
        if value is not None:
            extra_lines.append(f"• {label}: {value}")

    return (
        f"{_kalshi_market_markdown(row)}\n\n"
        f"Additional Details:\n"
        + ("\n".join(extra_lines) if extra_lines else "• No additional details available.")
    )


@mcp.tool()
async def kalshi_market_stats() -> str:
    """Return aggregate statistics for the Kalshi market dataset."""
    totals = _fetch_kalshi_rows(
        """
        SELECT
            COUNT(*) AS total_markets,
            SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_markets,
            SUM(volume) AS total_volume,
            AVG(liquidity) AS avg_liquidity
        FROM kalshi_markets
        """,
        (),
        fetch_one=True,
    )

    if not totals:
        return "No Kalshi market data available."

    total_markets = totals["total_markets"] or 0
    active_markets = totals["active_markets"] or 0
    total_volume = float(totals["total_volume"] or 0)
    avg_liquidity = float(totals["avg_liquidity"] or 0)

    by_category = _fetch_kalshi_rows(
        """
        SELECT category, COUNT(*) AS count, SUM(volume) AS volume
        FROM kalshi_markets
        WHERE is_active = 1
        GROUP BY category
        ORDER BY CASE WHEN volume IS NULL THEN 1 ELSE 0 END, volume DESC
        LIMIT 10
        """
    )

    lines = [
        "**Kalshi Dataset Overview**",
        f"- Total markets: {int(total_markets):,}",
        f"- Active markets: {int(active_markets):,}",
        f"- Total volume: ${total_volume:,.0f}",
        f"- Avg liquidity (active): ${avg_liquidity:,.0f}",
        "",
        "**Top Categories by Volume (active)**",
    ]

    if by_category:
        for row in by_category:
            category = row["category"] or "Uncategorized"
            volume = float(row["volume"] or 0)
            count = row["count"] or 0
            lines.append(f"- {category}: ${volume:,.0f} across {count} markets")
    else:
        lines.append("No active category breakdown available.")

    return "\n".join(lines)


@mcp.tool()
async def intelligent_search_multi_platform(
    question: str,
    platform: str = "both"
) -> str:
    """
    Use AI semantic search across Polymarket and/or Kalshi with relevance scoring.

    This is a SLOW operation (15-30 seconds) that uses Gemini AI to:
    - Understand semantic relationships
    - Score markets by relevance (0-100)
    - Provide reasoning for each match
    - Search across both platforms or target a specific one

    Args:
        question: Natural language query (e.g., "markets affected by Fed rate increases")
        platform: Which platform(s) to search - "polymarket", "kalshi", or "both" (default)

    Returns:
        Markets from both platforms ranked by AI relevance score with explanations.
        Format: 🔵 = Polymarket, 🟢 = Kalshi

    Note: This tool makes multiple Gemini API calls and may take 15-30 seconds.
          For simple keyword searches, use search_markets or search_kalshi_markets instead.
    """
    if not question or len(question.strip()) < 4:
        raise ValueError("Provide a question with at least four characters.")

    # Validate platform parameter
    platform = platform.lower().strip()
    if platform not in ["polymarket", "kalshi", "both"]:
        raise ValueError("Platform must be 'polymarket', 'kalshi', or 'both'")

    bot = _get_multi_platform_bot()
    try:
        # Inject platform preference into query if specified
        if platform != "both":
            modified_question = f"{platform} {question}"
        else:
            modified_question = question.strip()

        return bot.process_query(modified_question)
    except Exception as exc:  # pragma: no cover
        return f"Multi-platform intelligent search failed: {exc}"


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
