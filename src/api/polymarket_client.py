"""
Polymarket API Client
"""

import requests
import json
from typing import Dict, List, Optional
from datetime import datetime

class PolymarketClient:
    """Client for interacting with Polymarket APIs."""

    def __init__(self):
        self.gamma_api_base = "https://gamma-api.polymarket.com"
        self.clob_api_base = "https://clob.polymarket.com"

    def get_markets(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get list of markets from Polymarket."""
        try:
            url = f"{self.gamma_api_base}/markets"
            params = {
                "limit": limit,
                "offset": offset,
                "closed": "false"
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching markets: {e}")
            return []

    def search_markets(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for markets by query."""
        try:
            markets = self.get_markets(limit=100)
            filtered_markets = []

            for market in markets:
                if query.lower() in market.get("question", "").lower():
                    filtered_markets.append(market)
                    if len(filtered_markets) >= limit:
                        break

            return filtered_markets
        except Exception as e:
            print(f"Error searching markets: {e}")
            return []

    def get_market_prices(self, token_id: str) -> Optional[Dict]:
        """Get current prices for a market token."""
        try:
            url = f"{self.clob_api_base}/prices"
            params = {"market": token_id}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching prices for {token_id}: {e}")
            return None

    def get_price_history(self, token_id: str, fidelity: int = 60) -> List[Dict]:
        """Get price history for a token."""
        try:
            url = f"{self.clob_api_base}/prices-history"
            params = {
                "market": token_id,
                "interval": "max",
                "fidelity": fidelity
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("history", [])
        except Exception as e:
            print(f"Error fetching price history for {token_id}: {e}")
            return []

    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Get market details by slug."""
        try:
            url = f"{self.gamma_api_base}/markets"
            params = {"slug": slug}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None
        except Exception as e:
            print(f"Error fetching market by slug {slug}: {e}")
            return None