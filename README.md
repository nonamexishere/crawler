# 🕷️ Web Crawler

A comprehensive web crawling platform built with Python Flask, featuring real-time monitoring, intelligent search, and a responsive web interface.

## 🌟 Features

- **Multi-threaded Web Crawler** with configurable depth (k hops) and BFS traversal
- **Back Pressure Management** — bounded queue (max 10K URLs) + token bucket rate limiting
- **Real-time Search** — inverted index with relevance scoring, returns `(relevant_url, origin_url, depth)` triples
- **Live Dashboard** — monitor crawl progress, queue utilization, and back pressure status
- **Search While Indexing** — search results reflect newly indexed pages in real-time
- **Pause/Resume/Stop** controls for active crawlers
- **Resumable** — crawler state checkpointed to disk; interrupted crawls can be resumed
- **Language-native** — core logic uses only Python stdlib (`html.parser`, `urllib`, `threading`, `queue`)

## 🚀 Quick Start

### Prerequisites
- Python 3.11+

### Installation & Setup

```bash
# Clone the project
cd crawler

# Install dependencies (Flask only)
pip install -r requirements.txt

# Run the server
python app.py
```

The server starts at **http://localhost:3600**

### Usage

1. **Start a crawl**: On the dashboard, enter a URL and depth, then click "Start Crawl"
2. **Monitor progress**: Watch real-time stats on the dashboard or click "Details" for per-crawler monitoring
3. **Search content**: Navigate to the Search page and enter keywords
4. **Control crawlers**: Pause, resume, or stop active crawlers from the dashboard

## 🔧 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `POST /api/index` | POST | Start crawl: `{"origin": "https://...", "depth": 2}` |
| `GET /api/crawlers` | GET | List all crawlers with status |
| `GET /api/crawlers/<id>` | GET | Detailed status of one crawler |
| `POST /api/crawlers/<id>/pause` | POST | Pause crawler |
| `POST /api/crawlers/<id>/resume` | POST | Resume crawler |
| `POST /api/crawlers/<id>/stop` | POST | Stop crawler |
| `GET /search?query=<word>&sortBy=relevance` | GET | Search indexed content |
| `GET /api/system/status` | GET | System-wide status |

### Example: Start a Crawl

```bash
curl -X POST http://localhost:3600/api/index \
  -H "Content-Type: application/json" \
  -d '{"origin": "https://example.com", "depth": 2}'
```

### Example: Search

```bash
curl "http://localhost:3600/search?query=example&sortBy=relevance"
```

Response:
```json
{
  "query": "example",
  "count": 3,
  "results": [
    {"relevant_url": "https://example.com", "origin_url": "https://example.com", "depth": 0, "relevance_score": 1010},
    ...
  ]
}
```

## 📁 Project Structure

```
crawler/
├── app.py                  # Flask API server
├── requirements.txt        # Flask only
├── core/
│   ├── crawler_engine.py   # Multi-threaded BFS crawler
│   ├── html_parser.py      # Stdlib html.parser link/text extraction
│   ├── storage.py          # File-based persistence layer
│   └── rate_limiter.py     # Token bucket rate limiter
├── services/
│   ├── crawler_service.py  # Crawler lifecycle management
│   └── search_service.py   # Search & relevance scoring
├── templates/
│   ├── index.html          # Dashboard
│   ├── search.html         # Search page
│   └── status.html         # Monitoring page
├── static/
│   ├── css/style.css       # Dark-themed styles
│   └── js/app.js           # Frontend utilities
├── tests/                  # Unit tests
├── data/                   # Storage (auto-created)
│   └── storage/            # Word index: {letter}.data
├── product_prd.md          # Product requirements document
└── recommendation.md       # Production deployment recommendations
```

## 🔍 How It Works

### Crawler Architecture
1. **BFS Traversal**: Starting from the origin URL, discover links at each depth level up to k hops
2. **Thread Pool**: `concurrent.futures.ThreadPoolExecutor` with configurable worker count (default 8)
3. **Deduplication**: Thread-safe `set` ensures each URL is crawled only once
4. **Back Pressure**: Two layers prevent resource exhaustion:
   - **Bounded queue** (`queue.Queue(maxsize=10000)`) — blocks link producers when full
   - **Token bucket rate limiter** — per-domain (2 req/s) + global (10 req/s) limits

### Search System
1. **Inverted Index**: Page content is tokenized and indexed in JSONL files sharded by first letter
2. **Relevance Scoring**: `frequency × position_bonus × depth_factor`
   - Title words: 3× bonus
   - Heading words: 2× bonus
   - Shallower pages preferred (1/(1+depth) factor)
3. **Live Results**: Search reads directly from disk, so active crawler results appear immediately

### Scoring Formula
`relevance_score = (frequency × 10) + 1000 − (depth × 5)`
- Higher word frequency = higher score
- Shallower pages (lower depth) = higher score
- Base bonus of 1000 for exact match

### Concurrent Search During Indexing
The crawler writes index entries in append-only JSONL files. The search service reads these files fresh on each query. This lock-free design means search results reflect newly discovered pages without any coordination overhead.

### Storage Format
- **Visited URLs**: `data/visited.jsonl` — `{url, crawler_id, depth, timestamp}`
- **Word Index**: `data/storage/{letter}.data` — `{word} {url} {origin} {depth} {frequency}` (space-separated plain text)
- **Crawler State**: `data/crawlers/{id}.json` — full checkpoint (queue, visited, stats)

## 🧪 Testing

```bash
cd crawler
python -m pytest tests/ -v
```

## ⚙️ Configuration

Default parameters (set in `app.py` and `core/` modules):

| Parameter | Default | Description |
|---|---|---|
| Global rate limit | 10 req/s | Max requests per second across all domains |
| Domain rate limit | 2 req/s | Max requests per second per domain |
| Max queue size | 10,000 | Back pressure: max URLs in queue |
| Workers | 8 | Thread pool size per crawler |
| Fetch timeout | 15s | HTTP request timeout |
| Max page size | 5MB | Max HTML content to download |
| Checkpoint interval | 10s | How often state is saved to disk |
