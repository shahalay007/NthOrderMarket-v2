"""
Test the logger to see queries appear in the UI.
"""
from query_logger import QueryLogger
import time

logger = QueryLogger()

# Test Query 1: SQL Query
print("Testing SQL query logging...")
logger.start_query("top 5 markets by volume")
logger.log_strategy("FAST SQL", "Simple ranking query detected (has ranking keyword + metric)")
logger.log_sql(
    "SELECT * FROM events WHERE is_active=1 ORDER BY volume DESC LIMIT 5",
    "Polymarket"
)
logger.log_results(5, 0.23)
logger.end_query()

print("\n✅ SQL query logged!")
print("\n" + "="*80)

# Wait a bit
time.sleep(2)

# Test Query 2: AI Query
print("\nTesting AI query logging...")
logger.start_query("markets that would benefit from higher interest rates")
logger.log_strategy("AI SEMANTIC SEARCH", "Complex query requiring semantic understanding")

# Simulate AI batch 1
prompt1 = """You are a prediction market evaluator.

USER QUERY: markets that would benefit from higher interest rates
USER INTENT: Find markets related to interest rate increases

BATCH 1 of markets to evaluate:
[
  {"platform": "polymarket", "id": "456", "title": "Will banks increase savings rates?", "category": "Finance"},
  {"platform": "polymarket", "id": "457", "title": "Treasury yields above 5%", "category": "Finance"}
]

YOUR TASK:
1. Evaluate relevance (0-100)
2. Provide reasoning"""

response1 = "polymarket:456:93:Banks directly benefit from rate hikes|polymarket:457:91:Treasury yields track Fed rates"

logger.log_ai_prompt("Batch 1 Polymarket Matching", prompt1, response1)

# Simulate AI batch 2
prompt2 = """You are a prediction market evaluator.

USER QUERY: markets that would benefit from higher interest rates

BATCH 2 of markets to evaluate:
[
  {"platform": "polymarket", "id": "789", "title": "Real estate prices decline", "category": "Real Estate"},
  {"platform": "polymarket", "id": "790", "title": "Home sales decrease", "category": "Real Estate"}
]"""

response2 = "polymarket:789:85:Higher rates slow real estate|polymarket:790:82:Mortgage rates impact sales"

logger.log_ai_prompt("Batch 2 Polymarket Matching", prompt2, response2)

logger.log_results(12, 19.67)
logger.end_query()

print("\n✅ AI query logged!")
print("\n" + "="*80)
print("\n🎉 Test complete! Check the UI at http://localhost:5001")
print("The queries should appear in the dashboard.")
