# Query Logger Web UI Guide

## 🎯 Overview

The Query Logger Web UI provides a **beautiful, real-time dashboard** to monitor and analyze your query execution logs through your web browser.

## 🚀 Quick Start

### Start the UI

```bash
cd /Users/alayshah/Desktop/NthOrderMarket
python3 logger_ui.py
```

### Access the Dashboard

Open your browser and go to:
```
http://localhost:5001
```

The UI will automatically open in your default browser.

## 📊 Dashboard Features

### 1. Statistics Overview

At the top of the dashboard, you'll see **6 key metrics**:

- **Total Queries** - Total number of logged queries
- **⚡ SQL Queries** - Count of fast SQL queries
- **🧠 AI Queries** - Count of AI semantic search queries
- **Avg Response Time** - Average execution time across all queries
- **Avg SQL Time** - Average execution time for SQL queries
- **Avg AI Time** - Average execution time for AI queries

### 2. Controls

- **🔄 Refresh** - Manually refresh the data (auto-refreshes every 10 seconds)
- **📥 Export Log** - Download the complete log file
- **🗑️ Clear Log** - Clear all logged queries (requires confirmation)

### 3. Filters

- **Strategy Filter** - Filter by "All", "SQL Only", or "AI Only"
- **Search Box** - Search queries by text

### 4. Query Details

Each query entry shows:

#### Header
- **Query Text** - The original user query
- **Timestamp** - When the query was executed

#### Strategy Badge
- 🟢 **Green badge** - FAST SQL strategy
- 🟣 **Purple badge** - AI SEMANTIC SEARCH strategy

#### Strategy Reason
- Explanation of why this strategy was chosen

#### SQL Section (for SQL queries)
- **Platform Tag** - Polymarket platform
- **SQL Query** - The actual SQL executed (syntax highlighted)

#### AI Section (for AI queries)
- **Prompt Name** - Name of the AI step (e.g., "Batch 1 Multi-Platform Matching")
- **Input** - The prompt sent to the AI (truncated for readability)
- **Output** - The AI's response (truncated for readability)

#### Results
- **📊 Markets Found** - Number of results returned
- **⏱️ Execution Time** - How long the query took

## 🎨 Visual Design

### Color Coding

- **SQL Strategy** - Green badges and highlights
- **AI Strategy** - Purple badges and highlights
- **Platform Tags** - Blue badges
- **SQL Queries** - Dark background with green text (terminal-like)
- **AI Prompts** - Light gray background

### Auto-Refresh

The dashboard automatically refreshes every **10 seconds** to show new queries as they're logged.

## 🔧 API Endpoints

The UI exposes these REST API endpoints:

### `GET /api/queries`
Returns all logged queries as JSON.

**Example:**
```bash
curl http://localhost:5001/api/queries
```

### `GET /api/stats`
Returns statistics about logged queries.

**Example:**
```bash
curl http://localhost:5001/api/stats
```

**Response:**
```json
{
  "total_queries": 4,
  "sql_count": 2,
  "ai_count": 2,
  "total_time": 37.58,
  "avg_time": 9.40,
  "avg_sql_time": 0.34,
  "avg_ai_time": 18.45
}
```

### `POST /api/clear_log`
Clears the log file.

**Example:**
```bash
curl -X POST http://localhost:5001/api/clear_log
```

### `GET /api/export`
Exports the complete log file as text.

**Example:**
```bash
curl http://localhost:5001/api/export
```

## 📱 Mobile Responsive

The UI is fully responsive and works on:
- 💻 Desktop browsers
- 📱 Mobile phones
- 📱 Tablets

## 🎯 Use Cases

### 1. Real-time Monitoring

Leave the dashboard open while running queries to see them appear in real-time.

### 2. Performance Analysis

Compare execution times between SQL and AI strategies to optimize query routing.

### 3. Debugging

Inspect SQL queries and AI prompts to understand why certain results were returned.

### 4. Query History

Review all past queries with full details about strategy, execution, and results.

### 5. Export for Analysis

Export log data for further analysis in other tools.

## 🛠️ Configuration

### Change Port

Edit `logger_ui.py` and change the port:

```python
app.run(debug=True, port=5002, host='0.0.0.0')  # Use port 5002 instead
```

### Change Log File

Edit `logger_ui.py` and change the log file path:

```python
LOG_FILE = 'my_custom_log.log'
```

### Disable Auto-Refresh

In the browser console:
```javascript
autoRefresh = false;
```

To re-enable:
```javascript
autoRefresh = true;
```

## 🚨 Troubleshooting

### Port Already in Use

If port 5001 is in use:

```bash
# Kill process using port 5001
lsof -ti:5001 | xargs kill -9

# Or change port in logger_ui.py
```

### Can't Access UI

Check if the server is running:

```bash
curl http://localhost:5001
```

If no response:
```bash
python3 logger_ui.py
```

### Log File Not Found

The UI will show an empty state. Run some queries using the `query_logger.py` to generate logs:

```bash
python3 query_logger.py
```

### Browser Shows Old Data

Hard refresh the page:
- **Mac:** Cmd + Shift + R
- **Windows/Linux:** Ctrl + Shift + R

## 📊 Example Workflow

1. **Start the UI server**
   ```bash
   python3 logger_ui.py
   ```

2. **Open dashboard in browser**
   ```
   http://localhost:5001
   ```

3. **Run test queries**
   ```bash
   python3 query_logger.py
   ```

4. **Watch queries appear** in the dashboard (auto-refreshes every 10s)

5. **Analyze performance**
   - Compare SQL vs AI query times
   - Review strategy decisions
   - Inspect SQL queries and AI prompts

6. **Export data** for further analysis
   - Click "📥 Export Log" button
   - Downloads as `.log` file

## 🎉 Features Summary

✅ **Real-time dashboard** - Auto-refreshes every 10 seconds
✅ **Statistics overview** - Key metrics at a glance
✅ **Beautiful UI** - Gradient background, smooth animations
✅ **Search & filter** - Find queries quickly
✅ **Detailed views** - Full SQL queries and AI prompts
✅ **Export functionality** - Download logs for analysis
✅ **Mobile responsive** - Works on all devices
✅ **REST API** - Programmatic access to data

## 🌐 URLs

- **Dashboard:** http://localhost:5001
- **API Queries:** http://localhost:5001/api/queries
- **API Stats:** http://localhost:5001/api/stats
- **API Export:** http://localhost:5001/api/export

---

**Server Command:**
```bash
python3 logger_ui.py
```

**Access URL:**
```
http://localhost:5001
```

Enjoy your beautiful query logging dashboard! 🎉
