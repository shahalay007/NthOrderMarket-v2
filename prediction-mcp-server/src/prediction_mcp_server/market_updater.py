"""Fetch and refresh prediction market data from Polymarket APIs."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional
import random
import threading

import requests
import schedule
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .database import Database, Event

GAMMA_API = "https://gamma-api.polymarket.com"
MAX_ATTEMPTS = int(os.getenv("PREDICTION_UPDATE_MAX_RETRIES", "5"))
BACKOFF_FACTOR = float(os.getenv("PREDICTION_UPDATE_BACKOFF", "1.5"))
MAX_BACKOFF_SECONDS = float(os.getenv("PREDICTION_UPDATE_MAX_BACKOFF", "30"))
REQUEST_THROTTLE = float(os.getenv("PREDICTION_UPDATE_THROTTLE", "0.15"))
MAX_CONCURRENT_REQUESTS = max(1, int(os.getenv("PREDICTION_UPDATE_CONCURRENCY", "4")))

retry_strategy = Retry(
    total=MAX_ATTEMPTS,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    backoff_factor=BACKOFF_FACTOR,
    raise_on_status=False,
    respect_retry_after_header=True,
)

SESSION = requests.Session()
adapter = HTTPAdapter(max_retries=retry_strategy)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)
REQUEST_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_REQUESTS)


def _safe_float(value: Optional[object]) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def bootstrap_active_events(db: Database, limit: int = 500) -> List[str]:
    """Fetch metadata for all active events and ensure they exist in the DB."""
    offset = 0
    all_events: List[Dict[str, object]] = []

    while True:
        try:
            response = _request_json(
                "/events",
                params={"active": "true", "closed": "false", "limit": limit, "offset": offset},
            )
        except Exception as exc:
            print(f"  Error bootstrapping events (offset {offset}): {exc}")
            break

        batch = response
        if not batch:
            break

        all_events.extend(batch)
        if len(batch) < limit:
            break
        offset += len(batch)

    if not all_events:
        return []

    active_ids: List[str] = []
    seen: set[str] = set()

    for record in all_events:
        event_id = str(record.get("id"))
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)

        slug = (
            record.get("slug")
            or record.get("ticker")
            or record.get("question")
            or event_id
        )
        title = record.get("title") or record.get("question") or str(slug)
        description = record.get("description")
        domain = record.get("category")

        series = record.get("series") or []
        section = None
        if isinstance(series, list) and series:
            entry = series[0]
            section = entry.get("title") if isinstance(entry, dict) else None
        section = section or record.get("seriesSlug")

        tags = record.get("tags") or []
        subsection = None
        subsection_tag_id = None
        if isinstance(tags, list) and tags:
            tag_entry = tags[0]
            if isinstance(tag_entry, dict):
                subsection = tag_entry.get("label")
                try:
                    subsection_tag_id = int(tag_entry.get("id"))
                except (TypeError, ValueError):
                    subsection_tag_id = None

        markets = record.get("markets") or []
        outcome_prices = None
        last_trade_price = None
        best_bid = None
        best_ask = None
        liquidity_num = None

        if isinstance(markets, list) and markets:
            market = markets[0]
            if isinstance(market, dict):
                raw_prices = market.get("outcomePrices", "[]")
                outcome_prices = json.dumps(raw_prices) if not isinstance(raw_prices, str) else raw_prices
                last_trade_price = _safe_float(market.get("lastTradePrice"))
                best_bid = _safe_float(market.get("bestBid"))
                best_ask = _safe_float(market.get("bestAsk"))
                liquidity_num = _safe_float(market.get("liquidityNum"))

        db.add_or_update_event(
            event_id=event_id,
            slug=str(slug),
            title=str(title),
            description=description if isinstance(description, str) else None,
            domain=str(domain) if domain else None,
            section=str(section) if section else None,
            subsection=str(subsection) if subsection else None,
            section_tag_id=None,
            subsection_tag_id=subsection_tag_id,
            volume=_safe_float(record.get("volume")),
            liquidity=_safe_float(record.get("liquidity")),
            liquidity_clob=_safe_float(record.get("liquidityClob")),
            open_interest=_safe_float(record.get("openInterest")),
            last_trade_date=record.get("endDateIso") or record.get("endDate"),
            outcome_prices=outcome_prices,
            last_trade_price=last_trade_price,
            best_bid=best_bid,
            best_ask=best_ask,
            liquidity_num=liquidity_num,
        )
        active_ids.append(event_id)

    if active_ids:
        db.mark_inactive_events(active_ids)
        print(f"  Refreshed metadata for {len(active_ids)} active events")

    return active_ids


def fetch_event_market_data(event_id: str) -> Optional[Dict[str, object]]:
    """Fetch granular market data for a single event."""
    try:
        data = _request_json(f"/events/{event_id}", timeout=10)
    except Exception as exc:
        print(f"  Error fetching market data for {event_id}: {exc}")
        return None

    event_data: Dict[str, object]
    if isinstance(data, list) and data:
        event_data = data[0]
    else:
        event_data = data if isinstance(data, dict) else {}

    markets = event_data.get("markets") or []
    outcome_prices = "[]"
    last_trade_price = None
    best_bid = None
    best_ask = None
    liquidity_num = None

    if isinstance(markets, list) and markets:
        market = markets[0]
        if isinstance(market, dict):
            raw_prices = market.get("outcomePrices", "[]")
            outcome_prices = json.dumps(raw_prices) if not isinstance(raw_prices, str) else raw_prices
            last_trade_price = _safe_float(market.get("lastTradePrice"))
            best_bid = _safe_float(market.get("bestBid"))
            best_ask = _safe_float(market.get("bestAsk"))
            liquidity_num = _safe_float(market.get("liquidityNum"))

    return {
        "volume": _safe_float(event_data.get("volume")),
        "last_trade_date": event_data.get("endDateIso") or event_data.get("endDate"),
        "description": event_data.get("description"),
        "outcome_prices": outcome_prices,
        "last_trade_price": last_trade_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "liquidity": _safe_float(event_data.get("liquidity")),
        "liquidity_num": liquidity_num,
        "liquidity_clob": _safe_float(event_data.get("liquidityClob")),
        "open_interest": _safe_float(event_data.get("openInterest")),
    }


def _update_single_event(event: Event) -> bool:
    db = Database()
    try:
        market_data = fetch_event_market_data(event.id)
        if not market_data:
            return False

        db.add_or_update_event(
            event_id=event.id,
            slug=event.slug,
            title=event.title,
            domain=event.domain,
            section=event.section,
            subsection=event.subsection,
            volume=market_data["volume"],
            last_trade_date=market_data["last_trade_date"],
            description=market_data["description"] if isinstance(market_data["description"], str) else None,
            outcome_prices=market_data["outcome_prices"],
            last_trade_price=market_data["last_trade_price"],
            best_bid=market_data["best_bid"],
            best_ask=market_data["best_ask"],
            liquidity=market_data["liquidity"],
            liquidity_num=market_data["liquidity_num"],
            liquidity_clob=market_data["liquidity_clob"],
            open_interest=market_data["open_interest"],
        )
        return True
    except Exception as exc:
        print(f"  Error updating event {event.slug}: {exc}")
        return False
    finally:
        db.close()


def update_all_market_data(max_workers: Optional[int] = None) -> None:
    """Refresh all active event records with a thread pool."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Starting market data update...")
    worker_default = int(os.getenv("PREDICTION_UPDATE_WORKERS", str(MAX_CONCURRENT_REQUESTS)))
    workers = max_workers or worker_default
    workers = max(1, workers)
    db = Database()
    try:
        bootstrap_active_events(db)
        active_events = db.get_all_active_events()
        print(f"  Processing {len(active_events)} active events using {workers} workers")

        updated = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_update_single_event, event): event for event in active_events}
            for idx, future in enumerate(as_completed(futures), 1):
                if future.result():
                    updated += 1
                if idx % 100 == 0:
                    print(f"  Progress: processed {idx}/{len(active_events)} events")

        print(f"  Updated market data for {updated} events")
        print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S}] Market data update complete\n")
    finally:
        db.close()


def run_scheduler(interval_seconds: int = 20, max_workers: Optional[int] = None) -> None:
    """Continuously refresh market data every interval seconds."""
    print("Starting Polymarket market data updater...")
    update_all_market_data(max_workers=max_workers)
    schedule.every(interval_seconds).seconds.do(update_all_market_data, max_workers=max_workers)

    print(f"Scheduler running. Updating every {interval_seconds} seconds. Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping market updater.")


def _request_json(path: str, params: Optional[Dict[str, object]] = None, timeout: int = 15) -> Any:
    """Perform a GET request with retry and throttling for rate limits."""
    url = f"{GAMMA_API}{path}"
    attempts = MAX_ATTEMPTS

    for attempt in range(attempts):
        try:
            with REQUEST_SEMAPHORE:
                if REQUEST_THROTTLE > 0:
                    time.sleep(REQUEST_THROTTLE + random.uniform(0, REQUEST_THROTTLE))
                response = SESSION.get(url, params=params, timeout=timeout)

            if response.status_code == 429:
                if attempt == attempts - 1:
                    response.raise_for_status()
                retry_after_header = response.headers.get("Retry-After")
                if retry_after_header:
                    try:
                        delay = float(retry_after_header)
                    except ValueError:
                        delay = BACKOFF_FACTOR ** attempt
                else:
                    delay = BACKOFF_FACTOR ** attempt
                delay = min(delay, MAX_BACKOFF_SECONDS)
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            if attempt == attempts - 1:
                raise
            delay = min((BACKOFF_FACTOR ** attempt), MAX_BACKOFF_SECONDS)
            time.sleep(delay)

    raise RuntimeError("Exceeded maximum retry attempts")
