#!/usr/bin/env python3
"""
Polymarket Chatbot - Main Entry Point
"""

import os
import sys
from dotenv import load_dotenv
from src.chatbot.bot import PolymarketChatbot
from src.api.polymarket_client import PolymarketClient

def main():
    """Main entry point for the Polymarket chatbot."""
    load_dotenv()

    print("🎯 Polymarket Chatbot")
    print("=" * 40)

    # Initialize Polymarket client
    polymarket_client = PolymarketClient()

    # Initialize chatbot
    chatbot = PolymarketChatbot(polymarket_client)

    print("Chatbot initialized! Type 'quit' to exit.")
    print("-" * 40)

    try:
        while True:
            user_input = input("\n👤 You: ").strip()

            if user_input.lower() in ['quit', 'exit', 'bye']:
                print("👋 Goodbye!")
                break

            if not user_input:
                continue

            response = chatbot.process_message(user_input)
            print(f"🤖 Bot: {response}")

    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()