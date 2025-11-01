#!/usr/bin/env python3
"""
Kalshi Market Data Updater
Fetches market data from Kalshi API and stores it in SQLite database
"""

import requests
import time
import json
from datetime import datetime
from kalshi_database import KalshiDatabase
from concurrent.futures import ThreadPoolExecutor, as_completed

# Kalshi API Configuration
KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
FETCH_INTERVAL = 20  # seconds
MAX_WORKERS = 10  # parallel requests

class KalshiDataFetcher:
    def __init__(self, db_path='kalshi.db'):
        self.db = KalshiDatabase(db_path)
        self.base_url = KALSHI_API_BASE
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'KalshiMCPServer/1.0'
        })

    def fetch_markets(self, limit=1000, cursor=None, status='open'):
        """Fetch markets from Kalshi API with pagination."""
        url = f"{self.base_url}/markets"
        params = {'limit': limit}

        if cursor:
            params['cursor'] = cursor
        if status:
            params['status'] = status

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching markets: {e}")
            return None

    def fetch_all_markets(self, status='open'):
        """Fetch all markets using pagination."""
        all_markets = []
        cursor = None
        page = 1

        while True:
            print(f"Fetching markets page {page}... ", end='', flush=True)
            data = self.fetch_markets(limit=1000, cursor=cursor, status=status)

            if not data or 'markets' not in data:
                print("No data returned")
                break

            markets = data.get('markets', [])
            all_markets.extend(markets)
            print(f"Got {len(markets)} markets (total: {len(all_markets)})")

            # Check for next page
            cursor = data.get('cursor')
            if not cursor:  # Empty cursor means no more pages
                break

            page += 1

        return all_markets

    def parse_datetime(self, dt_string):
        """Parse ISO datetime string to datetime object."""
        if not dt_string:
            return None
        try:
            # Handle both formats: with and without 'Z'
            if dt_string.endswith('Z'):
                dt_string = dt_string[:-1] + '+00:00'
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

    def categorize_market(self, market):
        """Determine category from market data."""
        # Kalshi uses 'category' field directly
        category = market.get('category', 'Miscellaneous')

        # Map common categories
        category_map = {
            'politics': 'Politics',
            'economics': 'Economics',
            'finance': 'Finance',
            'sports': 'Sports',
            'entertainment': 'Entertainment',
            'technology': 'Technology',
            'climate': 'Climate',
            'science': 'Science'
        }

        return category_map.get(category.lower(), category.title())

    def store_market(self, market):
        """Store a single market in the database."""
        try:
            ticker = market.get('ticker')
            event_ticker = market.get('event_ticker')

            if not ticker or not event_ticker:
                return False

            # Parse datetimes
            open_time = self.parse_datetime(market.get('open_time'))
            close_time = self.parse_datetime(market.get('close_time'))
            expiration_time = self.parse_datetime(market.get('expiration_time'))
            settlement_time = self.parse_datetime(market.get('settlement_time'))

            # Determine category
            category = self.categorize_market(market)

            # Determine if market is active
            status = market.get('status')
            is_active = status in ['open', 'active']

            # Store in database
            self.db.add_or_update_market(
                ticker=ticker,
                event_ticker=event_ticker,
                title=market.get('title', ''),
                subtitle=market.get('subtitle'),
                market_type=market.get('market_type', 'binary'),
                category=category,
                status=status,
                open_time=open_time,
                close_time=close_time,
                expiration_time=expiration_time,
                settlement_time=settlement_time,
                volume=market.get('volume', 0),
                liquidity=market.get('liquidity', 0),
                open_interest=market.get('open_interest', 0),
                yes_bid=market.get('yes_bid'),
                yes_ask=market.get('yes_ask'),
                no_bid=market.get('no_bid'),
                no_ask=market.get('no_ask'),
                last_price=market.get('last_price'),
                result=market.get('result')
            )

            return True
        except Exception as e:
            print(f"Error storing market {market.get('ticker', 'unknown')}: {e}")
            return False

    def update_all_markets(self):
        """Fetch and update all markets from Kalshi."""
        print("\n" + "="*60)
        print(f"🔄 Kalshi Market Data Update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)

        # Fetch all open markets
        markets = self.fetch_all_markets(status='open')

        if not markets:
            print("⚠️  No markets fetched")
            return

        print(f"\n📊 Processing {len(markets)} markets...")

        # Store markets
        stored_count = 0
        active_tickers = []

        for market in markets:
            if self.store_market(market):
                stored_count += 1
                active_tickers.append(market.get('ticker'))

        # Mark inactive markets
        inactive_count = self.db.mark_inactive_markets(active_tickers)

        print(f"\n✅ Update complete:")
        print(f"   - Stored/Updated: {stored_count} markets")
        print(f"   - Marked inactive: {inactive_count} markets")
        print(f"   - Total active: {len(active_tickers)} markets")
        print("="*60)

    def close(self):
        """Close database connection."""
        self.db.close()


def main():
    """Main function to run continuous updates."""
    print("🚀 Starting Kalshi Market Data Fetcher")
    print(f"📡 API: {KALSHI_API_BASE}")
    print(f"⏱️  Update interval: {FETCH_INTERVAL} seconds")
    print("-" * 60)

    fetcher = KalshiDataFetcher()

    try:
        # Initial fetch
        fetcher.update_all_markets()

        # Continuous updates
        print(f"\n🔁 Starting continuous updates every {FETCH_INTERVAL} seconds...")
        print("Press Ctrl+C to stop\n")

        while True:
            time.sleep(FETCH_INTERVAL)
            fetcher.update_all_markets()

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping market data fetcher...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        fetcher.close()
        print("👋 Shutdown complete")


if __name__ == "__main__":
    main()
