# Intelligent Multi-Platform Prediction Market Chatbot

A sophisticated chatbot application for querying prediction markets from **Polymarket** and **Kalshi** using natural language. Combines SQL queries for structured data retrieval with AI-powered semantic search for complex queries across both platforms.

## Features

- **Multi-Platform Support**: Query both Polymarket (~3,000 markets) and Kalshi (~135,000 markets) simultaneously
- **Intelligent Query Processing**: Automatically chooses between SQL (fast) and AI semantic search (comprehensive)
- **Natural Language Interface**: Ask questions in plain English about prediction markets
- **Real-time Data**: Market data updates every 20 seconds from both APIs
- **Advanced Filtering**: Filter results by volume, liquidity, relevance, and keywords
- **Domain Categories**: Markets organized by categories across both platforms
- **Dual Database Architecture**: Separate write and read databases for optimal performance
- **Unified Results**: See markets from both platforms ranked by relevance in a single view

## Prerequisites

- Python 3.8+
- Gemini API key (free tier supported)
- SQLite3

## Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd polymarket-chatbot
```

2. **Install Python dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables**
```bash
# Create .env file
echo "GEMINI_API_KEY=your_api_key_here" > .env
echo "PORT=5002" >> .env
echo "DEBUG=False" >> .env
```

## MCP Server Bridge

Expose the same dataset and Gemini workflow inside MCP-compatible IDEs with the new `prediction-mcp-server` package (see `prediction-mcp-server/README.md`).

```bash
# one-stop setup (creates .venv, bootstraps DB, writes config snippet)
cd prediction-mcp-server
python install.py
```

```bash
# optional: create/update .env with DB path + Gemini key
uvx prediction-mcp-server init

# run the server (stdio transport for Claude Desktop, Cursor, etc.)
uvx prediction-mcp-server serve
```

Add this server to your MCP client config with the command `prediction-mcp-server` and ensure `polymarket_read.db` stays in sync via `db_sync.py`.

## 10/7

Follow these terminals to bring the full stack online:

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment**
   ```bash
   echo "GEMINI_API_KEY=your_api_key_here" > .env
   echo "PORT=5002" >> .env
   echo "DEBUG=False" >> .env
   ```
3. **Start market data ingestion** – keeps `polymarket.db` populated.
   ```bash
   python update_market_data.py
   ```
4. **Run the sync service** – mirrors writes into the read replica.
   ```bash
   python db_sync.py
   ```
5. **Launch the Flask app** – serves the UI at `http://localhost:5002`.
   ```bash
   python intelligent_app.py
   ```
6. **Open the web UI** at `http://localhost:5002` and optional logs at `/logs`.

## Running the Application

### Quick Start (All Components)

Run all three components in separate terminal windows:

**Terminal 1 - Backend/Frontend:**
```bash
python3 intelligent_app.py
```
Access the web interface at: http://localhost:5002

**Terminal 2 - Database Sync:**
```bash
python3 db_sync.py
```

**Terminal 3 - Market Data Updates:**
```bash
python3 update_market_data.py
```

### Component Details

#### 1. Backend & Frontend (`intelligent_app.py`)

The main Flask application that serves the web interface and handles chat queries.

```bash
python3 intelligent_app.py
```

**Features:**
- Web interface at http://localhost:5002
- REST API endpoints for chat, stats, and filtering
- Intelligent query routing (SQL vs AI)
- Real-time logging at http://localhost:5002/logs

**Key Endpoints:**
- `POST /api/chat` - Process natural language queries
- `GET /api/stats` - Get database statistics
- `GET /api/top-events` - Get top events by volume
- `POST /api/filter-events` - Filter events by criteria
- `GET /health` - Health check

#### 2. Database Sync (`db_sync.py`)

Synchronizes the write database to the read-only database every 20 seconds.

```bash
python3 db_sync.py
```

**Purpose:**
- Ensures read queries don't block write operations
- Maintains data consistency between databases
- Tracks read operations to prevent sync conflicts

#### 3. Market Data Updates (`update_market_data.py`)

Fetches live market data from Polymarket API every 20 seconds.

```bash
python3 update_market_data.py
```

**Updates:**
- Market volume
- Outcome prices
- Liquidity
- Open interest
- Active/inactive status

**Performance:**
- Uses 50 parallel workers for fast fetching
- Processes ~2000 markets in under 10 seconds

## Database Architecture

### Two-Database System

1. **`polymarket.db`** (Write Database)
   - Used by `update_market_data.py` for writes
   - Updated every 20 seconds with fresh market data

2. **`polymarket_read.db`** (Read Database)
   - Used by `intelligent_app.py` for queries
   - Synced from write DB every 20 seconds
   - No blocking from write operations

### Schema

**Events Table:**
- `id` - Unique event ID
- `title` - Market question
- `slug` - URL slug
- `domain` - Category (Sports, Politics, etc.)
- `volume` - Trading volume in USD
- `liquidity` - Available liquidity
- `outcome_prices` - Current market odds
- `is_active` - Active/closed status
- `open_interest` - Total positions
- `created_at` - Creation timestamp

## Query Mechanism

### How It Works

1. **User Input** → Single Gemini API call analyzes:
   - Query intent (find events, compare, statistics, etc.)
   - Strategy needed (SQL or AI semantic search)
   - Domain filter (if specified)
   - Output format (list, table, comparison, etc.)
   - Result limit

2. **Strategy Execution:**

   **SQL Strategy** (Fast - <1 second):
   - Direct database queries
   - Used for: top events, domain filtering, volume/liquidity queries

   **AI Batch Strategy** (Comprehensive - 15-30 seconds):
   - Splits active events into batches (~1000 each)
   - Parallel processing with 4 workers
   - Each batch scored for relevance (0-100)
   - Returns events with score ≥ 75

3. **Output Formatting** → Gemini formats results based on determined output type

### Example Queries

**SQL Strategy (Fast):**
- "Top 10 sports events"
- "All finance markets"
- "Events with volume over $100k"

**AI Batch Strategy (Semantic):**
- "Markets affected by Fed rate changes"
- "Events related to AI regulation"
- "What happens if Microsoft acquires Google?"

## Rate Limits & Optimization

### Gemini API Free Tier Limits
- 15 requests per minute
- 125,000 tokens per minute

### Optimizations Applied
- Reduced batch workers from 5 to 4 (keeps under token limit)
- Each query uses 1 analysis call + 2-10 batch calls
- Token usage: ~26,604 tokens per batch × 4 workers = ~106k tokens

## Frontend Features

### Main Interface
- Clean chat interface with message history
- Real-time response streaming
- Markdown formatting support

### Advanced Filtering
After query results appear, you can filter by:
- **Volume**: Min/max trading volume
- **Liquidity**: Min/max liquidity
- **Relevance**: Minimum relevance score
- **Keyword**: Search in titles and explanations
- **Sort**: By volume, liquidity, or relevance

### Live Logs
View application logs at http://localhost:5002/logs:
- Query tracking
- Response times
- Error messages
- System events

## Troubleshooting

### Rate Limit Errors (429)
If you see "quota exceeded" errors:
- Reduce query frequency
- The system already optimized for 4 parallel workers
- Free tier allows ~8-10 complex queries per minute

### Database Not Updating
1. Check if `update_market_data.py` is running
2. Check if `db_sync.py` is running
3. Verify databases exist: `ls -lh *.db`

### Port Already in Use
Change the port in `.env`:
```bash
PORT=5003
```

## Project Structure

```
prediction-market-chatbot/
├── intelligent_app.py                  # Main Flask application
├── intelligent_gemini_bot.py           # AI query processor (Polymarket only)
├── intelligent_multi_platform_bot.py   # NEW: AI query processor (both platforms)
├── db_sync.py                          # Database synchronization
├── update_market_data.py               # Polymarket data fetcher
├── update_kalshi_data.py               # NEW: Kalshi data fetcher
├── database.py                         # Polymarket database models
├── kalshi_database.py                  # NEW: Kalshi database models
├── requirements.txt                    # Python dependencies
├── templates/                          # HTML templates
│   ├── index.html                     # Main chat interface
│   └── logs.html                      # Logging interface
├── polymarket.db                      # Polymarket write database
├── polymarket_read.db                 # Polymarket read database
├── kalshi.db                          # NEW: Kalshi write database
└── kalshi_read.db                     # NEW: Kalshi read database
```

## Platform Coverage

- **Polymarket**: ~3,000 active markets
  - Categories: Sports, Politics, Finance, Entertainment, Technology
  - Update frequency: 20 seconds

- **Kalshi**: ~135,000 active markets
  - Categories: Sports, Politics, Economics, Weather, and more
  - Update frequency: 20 seconds

## Multi-Platform Intelligent Bot

The new `intelligent_multi_platform_bot.py` provides unified querying across both platforms:

```python
from intelligent_multi_platform_bot import IntelligentMultiPlatformBot

bot = IntelligentMultiPlatformBot(api_key=GEMINI_API_KEY)

# Query both platforms simultaneously
response = bot.process_query("Top markets about interest rates")

# Results show markets from both Polymarket (🔵) and Kalshi (🟢) ranked by relevance
```

**Features:**
- Automatic platform detection (queries "polymarket" or "kalshi" or both)
- Unified relevance scoring across platforms
- Visual platform indicators: 🔵 Polymarket, 🟢 Kalshi
- Combined results sorted by AI relevance score

## API Rate Limits

### Polymarket API
- No strict limits observed
- Fetches ~2000 events every 20 seconds without issues

### Gemini API (Free Tier)
- 15 requests/minute
- 125,000 tokens/minute input
- Optimized to stay within limits

## Performance Metrics

- **SQL Queries**: <1 second
- **AI Semantic Search**: 15-30 seconds (depending on batch count)
- **Market Data Updates**: 20 second intervals
- **Database Sync**: 20 second intervals
- **Parallel Batch Processing**: 4 workers
- **Market Fetch Workers**: 50 workers

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with `test_*.py` scripts
5. Submit a pull request

## License

MIT License
