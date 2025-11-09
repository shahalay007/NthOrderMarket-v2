# Cleanup Notes

## Kalshi Removal - Completed

The following changes have been made to remove Kalshi integration:

### Files Removed:
- `kalshi_database.py`
- `kalshi_all_markets.csv`
- `kalshi_category_summary.csv`  
- `kalshi_top_100_markets.csv`
- `update_kalshi_data.py`
- `MCP_INTELLIGENT_SEARCH.md`

### Files Updated:
- `intelligent_app.py` - Removed Kalshi search functions and API integration
- `intelligent_gemini_bot.py` - Removed Kalshi platform filter, database schema, examples
- `README.md` - Updated to Polymarket-only system
- `LOGGER_UI_GUIDE.md` - Already clean
- `QUERY_LOGGER_USAGE.md` - Already clean
- `QUERY_LOGGING_GUIDE.md` - Removed Kalshi examples
- `query_logger.py` - Removed Kalshi references
- `test_logger_with_ui.py` - Replaced Kalshi examples with Polymarket

### Still Needs Cleanup:
- `prediction-mcp-server/` - Contains Kalshi-specific tools and database references
  - This is a separate MCP server module that may need manual review

### Notes:
- Platform filter now only supports 'POLYMARKET' (removed 'KALSHI' and 'BOTH')
- All database references now point only to Polymarket databases
- All examples and documentation updated to Polymarket-only
