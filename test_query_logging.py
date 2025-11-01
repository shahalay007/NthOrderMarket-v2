"""
Test script to demonstrate the query logging system.
"""
import os
from intelligent_multi_platform_bot import IntelligentMultiPlatformBot

def main():
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("Error: GEMINI_API_KEY not set")
        return

    # Initialize bot with logging enabled
    bot = IntelligentMultiPlatformBot(
        api_key,
        enable_query_logging=True  # Enable detailed logging
    )

    print("=" * 80)
    print("QUERY LOGGING DEMONSTRATION")
    print("=" * 80)
    print("\nAll query details will be logged to: query_execution.log")
    print("Each query shows:")
    print("  - Query text and timestamp")
    print("  - Strategy chosen (SQL or AI)")
    print("  - SQL queries executed (if SQL strategy)")
    print("  - AI prompts and responses (if AI strategy)")
    print("  - Results count and time elapsed")
    print("=" * 80)

    # Test queries
    test_queries = [
        "top 10 markets by volume in polymarket",  # Should use SQL
        "markets affected by Federal Reserve rate changes",  # Should use AI
    ]

    for query in test_queries:
        print(f"\n\nProcessing: {query}")
        print("-" * 80)

        result = bot.process_query(query)

        print("\nQuery complete! Check query_execution.log for full details.")
        print(f"Preview of results:\n{result[:300]}...")

    bot.close()

    print("\n\n" + "=" * 80)
    print("DONE! Check query_execution.log for complete execution details")
    print("=" * 80)


if __name__ == "__main__":
    main()
