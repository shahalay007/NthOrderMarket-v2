# MCP Intelligent Multi-Platform Search

## Overview

The MCP server now includes **AI-powered semantic search** across both Polymarket and Kalshi platforms through a new tool: `intelligent_search_multi_platform`.

## What's New

### Before (Path 1 Only - Fast SQL)
Claude Desktop could only perform simple keyword-based searches:
- ✅ `search_markets("interest rates")` → SQL LIKE query
- ✅ `list_kalshi_markets(limit=10)` → Top 10 by volume
- ❌ **Could NOT understand**: "markets affected by Fed rate changes"

### After (Path 1 + Path 2 - AI Semantic)
Claude Desktop now has **both** capabilities:
- ✅ **Path 1**: Fast SQL keyword search (<1 second)
- ✅ **Path 2**: AI semantic search with relevance scoring (15-30 seconds)

## New Tool: `intelligent_search_multi_platform`

### Usage in Claude Desktop

Simply ask Claude a semantic question, and it will automatically use the intelligent search tool when appropriate:

**Example queries:**
- "What markets would be affected by a Federal Reserve rate increase?"
- "Show me prediction markets related to AI regulation"
- "Find markets that could benefit from higher oil prices"
- "Markets impacted by the 2024 election results"

### How It Works

```
1. You ask Claude: "Markets affected by Fed rate changes?"

2. Claude detects this needs semantic understanding

3. Claude calls: intelligent_search_multi_platform(
     question="Markets affected by Fed rate changes?",
     platform="both"
   )

4. MCP Server executes:
   a. Keyword pre-filter (SQL) → 800 candidate markets
   b. Batch processing with Gemini AI (4 parallel workers)
   c. Each market scored for relevance (0-100)
   d. Results sorted by relevance

5. Returns: Top 20 markets with relevance scores + reasoning
```

### Output Format

```
Found 15 markets (showing top 15):

1. 🔵 **Fed Rate Decision March 2025** (Relevance: 95/100 - Directly about Fed rates)
   - Volume: $2,450,000
   - Liquidity: $850,000.00
   - 🔗 Link: https://polymarket.com/event/fed-rate-march-2025

2. 🟢 **Treasury Yields Above 5%** (Relevance: 92/100 - Closely tied to Fed policy)
   - Volume: $1,850,000
   - Liquidity: $420,000.00
   - 🔗 Link: https://kalshi.com/markets/YIELDS-24

3. 🔵 **US Recession in 2025** (Relevance: 88/100 - Impacted by Fed decisions)
   - Volume: $3,200,000
   - Liquidity: $1,100,000.00
   - 🔗 Link: https://polymarket.com/event/recession-2025

...
```

**Legend:**
- 🔵 = Polymarket
- 🟢 = Kalshi

## Parameters

### `question` (required)
Natural language query describing what markets you're looking for.

**Examples:**
- "markets about climate change"
- "events affected by Supreme Court decisions"
- "what happens if Tesla stock crashes?"

### `platform` (optional, default: "both")
Which platform(s) to search:
- `"both"` - Search both Polymarket and Kalshi (default)
- `"polymarket"` - Only Polymarket markets
- `"kalshi"` - Only Kalshi markets

## Performance

| Metric | Value |
|--------|-------|
| **Speed** | 15-30 seconds |
| **API Calls** | 4-10 Gemini API calls |
| **Markets Analyzed** | Up to 2,000 candidates |
| **Parallel Workers** | 4 |
| **Batch Size** | 200 markets per batch |

## Comparison: Path 1 vs Path 2

| Feature | Path 1 (SQL) | Path 2 (AI Semantic) |
|---------|--------------|----------------------|
| **Tool** | `search_markets`, `search_kalshi_markets` | `intelligent_search_multi_platform` |
| **Speed** | <1 second | 15-30 seconds |
| **Understanding** | Keyword matching only | Semantic relationships |
| **Relevance Scoring** | ❌ No | ✅ Yes (0-100) |
| **Reasoning** | ❌ No | ✅ Yes (explanations) |
| **Best For** | Simple searches | Complex/semantic queries |
| **Example Query** | "Top 10 by volume" | "Markets affected by Fed rates" |

## When to Use Each Tool

### Use Path 1 (Fast SQL) For:
- ✅ "Top 10 markets by volume"
- ✅ "Markets about crypto"
- ✅ "Show me NFL markets"
- ✅ "Search for 'Trump'"

### Use Path 2 (AI Semantic) For:
- ✅ "Markets affected by inflation"
- ✅ "What events would benefit from oil price increases?"
- ✅ "Markets inversely related to tech stocks"
- ✅ "Events impacted by Supreme Court rulings"

## Technical Details

### Architecture

```
┌─────────────────────┐
│   Claude Desktop    │ (You chat here)
└──────────┬──────────┘
           │
           │ Uses intelligent_search_multi_platform tool
           ▼
┌─────────────────────┐
│    MCP Server       │
└──────────┬──────────┘
           │
           │ Initializes IntelligentMultiPlatformBot
           ▼
┌─────────────────────┐
│ Multi-Platform Bot  │
└──────────┬──────────┘
           │
           ├──► Polymarket DB (polymarket_read.db)
           ├──► Kalshi DB (kalshi_read.db)
           └──► Gemini API (semantic scoring)
```

### Dependencies

The tool requires:
1. `intelligent_multi_platform_bot.py` in project root
2. Both databases: `polymarket_read.db` and `kalshi_read.db`
3. `GEMINI_API_KEY` environment variable set
4. All dependencies from `requirements.txt`

### Error Handling

If the tool fails, Claude will receive an error message:

```python
"Multi-platform intelligent search failed: [error details]"
```

Common errors:
- Missing `GEMINI_API_KEY`
- Database files not found
- Gemini API rate limits exceeded
- Import errors for `intelligent_multi_platform_bot.py`

## Rate Limits

**Gemini API Free Tier:**
- 15 requests/minute
- 125,000 tokens/minute

**With intelligent search:**
- Each query uses 4-10 API calls
- ~1-2 queries per minute max
- Total: ~60-120 queries per hour

**Recommendation:** Use Path 1 (SQL) for simple queries to conserve API quota.

## Testing

To test the new tool:

1. **Restart Claude Desktop** (already done)

2. **Ask Claude a semantic question:**
   ```
   "What Kalshi markets would be affected if the Federal Reserve raises interest rates?"
   ```

3. **Claude should automatically use the tool** and return results with relevance scores

4. **Expected response time:** 15-30 seconds

## Troubleshooting

### Tool not appearing
- Restart Claude Desktop: `osascript -e 'quit app "Claude"' && open -a "Claude"`
- Check MCP server logs at `/tmp/mcp-server.log`

### "Bot import failed" error
- Ensure `intelligent_multi_platform_bot.py` exists in project root
- Check Python path in MCP server initialization

### Slow responses (>60 seconds)
- Reduce batch count in `intelligent_multi_platform_bot.py`
- Check Gemini API rate limits

### Empty results
- Verify databases have data: `sqlite3 kalshi_read.db "SELECT COUNT(*) FROM kalshi_markets WHERE is_active=1"`
- Check if background services are running

## Summary

You now have **full AI semantic search** available directly in Claude Desktop!

**Total MCP Tools Available:**

**Polymarket (4 tools):**
1. `list_top_markets` - Fast SQL
2. `search_markets` - Fast SQL
3. `market_details` - Fast SQL
4. `market_stats` - Fast SQL

**Kalshi (4 tools):**
5. `list_kalshi_markets` - Fast SQL
6. `search_kalshi_markets` - Fast SQL
7. `kalshi_market_details` - Fast SQL
8. `kalshi_market_stats` - Fast SQL

**Multi-Platform (2 tools):**
9. `intelligent_market_analysis` - AI (Polymarket only, legacy)
10. `intelligent_search_multi_platform` - **NEW: AI (Both platforms)**

**Total: 10 tools** covering ~138,000 prediction markets across both platforms!
