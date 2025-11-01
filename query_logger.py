"""
Standalone Query Logger for tracking SQL and AI query execution.
Logs all query details to query_execution.log with detailed information about:
- Query text and timestamp
- Strategy chosen (SQL vs AI)
- SQL queries executed (for SQL strategy)
- All AI prompts and responses (for AI strategy)
- Results count and execution time
"""
from datetime import datetime


class QueryLogger:
    """Logs detailed query execution information."""

    def __init__(self, log_file='query_execution.log'):
        """Initialize the query logger.

        Args:
            log_file: Path to log file (default: query_execution.log)
        """
        self.log_file = log_file
        self.current_query_log = []
        self.start_time = None

    def start_query(self, query):
        """Start logging a new query.

        Args:
            query: The user's query text
        """
        self.current_query_log = []
        self.start_time = datetime.now()
        self.log(f"\n{'='*80}")
        self.log(f"QUERY: {query}")
        self.log(f"TIMESTAMP: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"{'='*80}")

    def log(self, message):
        """Add a log entry.

        Args:
            message: The message to log
        """
        self.current_query_log.append(message)
        # Write to file immediately
        with open(self.log_file, 'a') as f:
            f.write(message + '\n')
        # Print to console
        print(message)

    def log_strategy(self, strategy, reason):
        """Log the chosen strategy.

        Args:
            strategy: Strategy name (e.g., "FAST SQL", "AI SEMANTIC SEARCH")
            reason: Reason for choosing this strategy
        """
        self.log(f"\nSTRATEGY CHOSEN: {strategy}")
        self.log(f"REASON: {reason}")

    def log_sql(self, query, platform, params=None):
        """Log SQL query execution.

        Args:
            query: The SQL query string
            platform: Platform name (e.g., "Polymarket", "Kalshi")
            params: Optional query parameters
        """
        self.log(f"\n--- SQL QUERY ---")
        self.log(f"Platform: {platform}")
        self.log(f"Query: {query}")
        if params:
            self.log(f"Parameters: {params}")

    def log_ai_prompt(self, step_name, prompt, response=None):
        """Log AI prompt and response.

        Args:
            step_name: Name of this AI step (e.g., "Batch 1 Multi-Platform Matching")
            prompt: The prompt sent to the AI
            response: The AI's response (optional)
        """
        self.log(f"\n--- AI PROMPT: {step_name} ---")
        self.log(f"Input ({len(prompt)} chars):")
        # Truncate long prompts for readability
        self.log(f"{prompt[:500]}..." if len(prompt) > 500 else prompt)

        if response:
            self.log(f"\nOutput ({len(response)} chars):")
            # Truncate long responses for readability
            self.log(f"{response[:500]}..." if len(response) > 500 else response)

    def log_results(self, count, time_elapsed):
        """Log final results.

        Args:
            count: Number of results/markets found
            time_elapsed: Time elapsed in seconds
        """
        self.log(f"\n--- RESULTS ---")
        self.log(f"Markets Found: {count}")
        self.log(f"Time Elapsed: {time_elapsed:.2f}s")

    def log_error(self, error_message):
        """Log an error.

        Args:
            error_message: The error message to log
        """
        self.log(f"\n❌ ERROR: {error_message}")

    def end_query(self):
        """End current query logging."""
        self.log(f"{'='*80}\n")
        self.start_time = None

    def get_log_contents(self):
        """Get the current query log contents.

        Returns:
            List of log messages for the current query
        """
        return self.current_query_log.copy()

    def clear_log_file(self):
        """Clear the entire log file."""
        with open(self.log_file, 'w') as f:
            f.write("")
        print(f"Log file {self.log_file} cleared")


# Example usage
if __name__ == "__main__":
    # Create logger
    logger = QueryLogger()

    # Example 1: SQL Query
    logger.start_query("top 10 markets by volume in polymarket")
    logger.log_strategy("FAST SQL", "Simple ranking query detected (has ranking keyword + metric)")
    logger.log_sql(
        "SELECT * FROM events WHERE is_active=1 ORDER BY volume DESC LIMIT 10",
        "Polymarket"
    )
    logger.log_results(10, 0.34)
    logger.end_query()

    # Example 2: AI Query
    logger.start_query("markets affected by Federal Reserve rate changes")
    logger.log_strategy("AI SEMANTIC SEARCH", "Complex query requiring semantic understanding")

    example_prompt = """You are a prediction market evaluator.

USER QUERY: markets affected by Federal Reserve rate changes
USER INTENT: Find markets related to: markets affected by Federal Reserve rate changes

BATCH 1 of markets to evaluate (from Polymarket and Kalshi):
[
  {
    "platform": "polymarket",
    "id": "12345",
    "title": "Will the Fed raise rates in March 2025?",
    "category": "Politics"
  }
]

YOUR TASK:
1. Evaluate each market's relevance to the user query
2. Assign a relevance score (0-100)
..."""

    example_response = "polymarket:12345:95:Directly about Fed rate decision|polymarket:67890:88:Treasury yields tied to Fed policy"

    logger.log_ai_prompt("Batch 1 Multi-Platform Matching", example_prompt, example_response)
    logger.log_results(15, 18.45)
    logger.end_query()

    print("\n✅ Example queries logged to query_execution.log")
