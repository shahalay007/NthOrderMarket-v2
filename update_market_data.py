"""
Fast market data updater - updates all enrichment fields for all active events every 5 seconds
Uses parallel processing for efficiency
"""
import requests
import time
import schedule
from datetime import datetime
from database import Database
from concurrent.futures import ThreadPoolExecutor, as_completed

GAMMA = "https://gamma-api.polymarket.com"

BOOTSTRAP_LIMIT = 500


def bootstrap_active_events(db):
    """Ensure the database contains up-to-date active events from Polymarket."""
    all_events = []
    offset = 0

    while True:
        try:
            response = requests.get(
                f"{GAMMA}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": BOOTSTRAP_LIMIT,
                    "offset": offset
                },
                timeout=15
            )
            if not response.ok:
                print(f"  Error bootstrapping events (offset {offset}): {response.status_code}")
                break

            batch = response.json()
        except Exception as e:
            print(f"  Error fetching active events (offset {offset}): {e}")
            break

        if not batch:
            break

        all_events.extend(batch)

        if len(batch) < BOOTSTRAP_LIMIT:
            break

        offset += len(batch)

    if not all_events:
        return []

    active_ids = []
    seen_ids = set()

    def to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    for event in all_events:
        event_id = str(event.get("id"))
        if not event_id:
            continue
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)

        slug = event.get("slug") or event.get("ticker") or event_id
        title = event.get("title") or event.get("question") or slug
        description = event.get("description")
        domain = event.get("category")

        series = event.get("series") or []
        section = series[0].get("title") if series else event.get("seriesSlug")

        tags = event.get("tags") or []
        subsection = tags[0].get("label") if tags else None
        subsection_tag_id = to_int(tags[0].get("id")) if tags else None

        volume = to_float(event.get("volume"))
        liquidity = to_float(event.get("liquidity"))
        liquidity_clob = to_float(event.get("liquidityClob"))
        open_interest = to_float(event.get("openInterest"))
        last_trade_date = event.get("endDate") or event.get("endDateIso")

        markets = event.get("markets") or []
        outcome_prices = None
        last_trade_price = None
        best_bid = None
        best_ask = None
        liquidity_num = None

        if markets:
            market = markets[0]
            outcome_prices = str(market.get("outcomePrices", "[]"))
            last_trade_price = to_float(market.get("lastTradePrice"))
            best_bid = to_float(market.get("bestBid"))
            best_ask = to_float(market.get("bestAsk"))
            liquidity_num = to_float(market.get("liquidityNum"))

        db.add_or_update_event(
            event_id=event_id,
            slug=slug,
            title=title,
            domain=domain,
            section=section,
            subsection=subsection,
            section_tag_id=None,
            subsection_tag_id=subsection_tag_id,
            volume=volume,
            last_trade_date=last_trade_date,
            outcome_prices=outcome_prices,
            last_trade_price=last_trade_price,
            best_bid=best_bid,
            best_ask=best_ask,
            liquidity=liquidity,
            liquidity_num=liquidity_num,
            liquidity_clob=liquidity_clob,
            open_interest=open_interest,
            description=description
        )

        active_ids.append(event_id)

    if active_ids:
        db.mark_inactive_events(active_ids)
        print(f"  Refreshed metadata for {len(active_ids)} active events")

    return active_ids


def fetch_event_market_data(event_id):
    """Fetch complete market data for a single event."""
    try:
        response = requests.get(f"{GAMMA}/events/{event_id}", timeout=10)
        if not response.ok:
            return None

        data = response.json()
        event_data = data[0] if isinstance(data, list) and data else data

        # Extract event-level fields
        volume = int(float(event_data.get("volume", 0)))
        last_trade_date = event_data.get("endDateIso") or event_data.get("endDate")
        description = event_data.get("description", "")  # Extract description
        liquidity = float(event_data.get("liquidity", 0)) if event_data.get("liquidity") else None
        liquidity_clob = float(event_data.get("liquidityClob", 0)) if event_data.get("liquidityClob") else None
        open_interest = float(event_data.get("openInterest", 0)) if event_data.get("openInterest") else None

        # Extract market-level fields from first active market
        markets = event_data.get("markets", [])
        outcome_prices = "[]"
        last_trade_price = None
        best_bid = None
        best_ask = None
        liquidity_num = None

        if markets:
            # Use first market for pricing data
            market = markets[0]
            outcome_prices = str(market.get("outcomePrices", "[]"))
            last_trade_price = float(market.get("lastTradePrice", 0)) if market.get("lastTradePrice") else None
            best_bid = float(market.get("bestBid", 0)) if market.get("bestBid") else None
            best_ask = float(market.get("bestAsk", 0)) if market.get("bestAsk") else None
            liquidity_num = float(market.get("liquidityNum", 0)) if market.get("liquidityNum") else None

        return {
            'volume': volume,
            'last_trade_date': last_trade_date,
            'description': description,
            'outcome_prices': outcome_prices,
            'last_trade_price': last_trade_price,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'liquidity': liquidity,
            'liquidity_num': liquidity_num,
            'liquidity_clob': liquidity_clob,
            'open_interest': open_interest
        }

    except Exception as e:
        print(f"  Error fetching market data for {slug}: {e}")
        return None

def fetch_and_update_event(event):
    """Fetch and update a single event (for parallel execution). Each thread gets its own DB connection."""
    db = Database()  # Create new DB session for this thread
    try:
        market_data = fetch_event_market_data(event.id)

        if market_data is not None:
            db.add_or_update_event(
                event_id=event.id,
                slug=event.slug,
                title=event.title,
                domain=event.domain,
                section=event.section,
                subsection=event.subsection,
                volume=market_data['volume'],
                last_trade_date=market_data['last_trade_date'],
                description=market_data['description'],
                outcome_prices=market_data['outcome_prices'],
                last_trade_price=market_data['last_trade_price'],
                best_bid=market_data['best_bid'],
                best_ask=market_data['best_ask'],
                liquidity=market_data['liquidity'],
                liquidity_num=market_data['liquidity_num'],
                liquidity_clob=market_data['liquidity_clob'],
                open_interest=market_data['open_interest']
            )
            return True
        return False
    except Exception as e:
        print(f"  Error updating event {event.slug}: {e}")
        return False
    finally:
        db.close()

def update_all_market_data():
    """Update all enrichment fields for all active events in parallel."""
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Starting market data update...")

    db = Database()

    try:
        # Ensure we have the latest set of active events
        active_ids = bootstrap_active_events(db)
        if not active_ids:
            print("  Warning: No active events fetched from Polymarket.")

        # Get all active events
        active_events = db.get_all_active_events()
        print(f"  Found {len(active_events)} active events")

        updated_count = 0
        
        # Use ThreadPoolExecutor for parallel requests (50 workers for faster processing)
        with ThreadPoolExecutor(max_workers=50) as executor:
            # Submit all tasks (each will create its own DB connection)
            futures = {executor.submit(fetch_and_update_event, event): event for event in active_events}
            
            # Process completed tasks
            for future in as_completed(futures):
                if future.result():
                    updated_count += 1
                    
                    if updated_count % 100 == 0:
                        print(f"  Updated {updated_count}/{len(active_events)} events...")

        print(f"  Successfully updated market data for {updated_count} events")
        print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Market data update completed\n")

    except Exception as e:
        print(f"  ERROR during market data update: {e}")
    finally:
        db.close()

def run_scheduler():
    """Run the market data update every 20 seconds."""
    print("Starting Polymarket market data updater...")
    print("Running initial update...")
    update_all_market_data()

    schedule.every(20).seconds.do(update_all_market_data)

    print("Scheduler started. Updating market data every 20 seconds. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    run_scheduler()
