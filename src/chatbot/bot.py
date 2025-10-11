"""
Polymarket Chatbot Implementation
"""

import re
from typing import Dict, List, Optional
from src.api.polymarket_client import PolymarketClient

class PolymarketChatbot:
    """Chatbot for interacting with Polymarket data."""

    def __init__(self, polymarket_client: PolymarketClient):
        self.client = polymarket_client
        self.conversation_history = []

    def process_message(self, message: str) -> str:
        """Process user message and return bot response."""
        message = message.strip().lower()
        self.conversation_history.append(("user", message))

        try:
            # Detect intent and respond accordingly
            if any(word in message for word in ["price", "cost", "value"]):
                response = self._handle_price_query(message)
            elif any(word in message for word in ["search", "find", "look for"]):
                response = self._handle_search_query(message)
            elif any(word in message for word in ["market", "markets"]):
                response = self._handle_market_query(message)
            elif any(word in message for word in ["help", "commands", "what can you do"]):
                response = self._handle_help_query()
            else:
                response = self._handle_general_query(message)

            self.conversation_history.append(("bot", response))
            return response

        except Exception as e:
            error_response = f"Sorry, I encountered an error: {str(e)}"
            self.conversation_history.append(("bot", error_response))
            return error_response

    def _handle_price_query(self, message: str) -> str:
        """Handle price-related queries."""
        # Extract market name from message
        market_keywords = self._extract_market_keywords(message)

        if not market_keywords:
            return "Please specify which market you'd like to know the price for."

        # Search for markets
        markets = self.client.search_markets(" ".join(market_keywords), limit=3)

        if not markets:
            return f"I couldn't find any markets matching '{' '.join(market_keywords)}'. Try a different search term."

        # Get price for the first matching market
        market = markets[0]
        response = f"📈 **{market.get('question', 'Unknown Market')}**\\n"

        # Get token prices
        tokens = market.get('tokens', [])
        if tokens:
            for token in tokens:
                token_id = token.get('token_id')
                outcome = token.get('outcome', 'Unknown')

                if token_id:
                    price_data = self.client.get_market_prices(token_id)
                    if price_data and 'price' in price_data:
                        price = float(price_data['price']) * 100
                        response += f"  • {outcome}: {price:.1f}¢\\n"
                    else:
                        response += f"  • {outcome}: Price unavailable\\n"
        else:
            response += "Price data unavailable for this market."

        return response

    def _handle_search_query(self, message: str) -> str:
        """Handle search queries."""
        # Remove search keywords and extract the actual query
        search_terms = re.sub(r'\\b(search|find|look for)\\b', '', message).strip()

        if not search_terms:
            return "What would you like me to search for?"

        markets = self.client.search_markets(search_terms, limit=5)

        if not markets:
            return f"No markets found for '{search_terms}'. Try different keywords."

        response = f"🔍 Found {len(markets)} market(s) for '{search_terms}': \\n\\n"

        for i, market in enumerate(markets, 1):
            question = market.get('question', 'Unknown Market')
            end_date = market.get('end_date_iso', 'Unknown')
            response += f"{i}. {question}\\n   Ends: {end_date}\\n\\n"

        return response

    def _handle_market_query(self, message: str) -> str:
        """Handle general market queries."""
        if "trending" in message or "popular" in message:
            markets = self.client.get_markets(limit=5)
            if markets:
                response = "🔥 **Trending Markets:**\\n\\n"
                for i, market in enumerate(markets, 1):
                    question = market.get('question', 'Unknown Market')
                    response += f"{i}. {question}\\n"
                return response
            else:
                return "Unable to fetch trending markets at the moment."
        else:
            return "I can help you with market prices, searches, and trending markets. What would you like to know?"

    def _handle_help_query(self) -> str:
        """Handle help queries."""
        return """🤖 **Polymarket Chatbot Help**

Here's what I can help you with:

📈 **Price Queries:**
- "What's the price of [market name]?"
- "Show me prices for Trump election"

🔍 **Search Markets:**
- "Search for Bitcoin markets"
- "Find markets about AI"

📊 **Market Info:**
- "Show me trending markets"
- "What are the popular markets?"

💡 **Tips:**
- Be specific with market names
- I search through active markets
- Prices are shown in cents (¢)

Type your question naturally - I'll do my best to help!"""

    def _handle_general_query(self, message: str) -> str:
        """Handle general queries."""
        return "I'm a Polymarket chatbot! I can help you with market prices, search for markets, and show trending markets. Type 'help' to see what I can do."

    def _extract_market_keywords(self, message: str) -> List[str]:
        """Extract potential market keywords from message."""
        # Remove common words and price-related terms
        stop_words = {"what", "is", "the", "price", "of", "for", "show", "me", "get", "about"}
        words = message.split()
        keywords = [word for word in words if word not in stop_words and len(word) > 2]
        return keywords