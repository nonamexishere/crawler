# Product Requirements Document (PRD)

## Overview

Build a web crawler system that provides two core capabilities:

1. **index(origin, k)**: Crawl the web starting from `origin` URL up to depth `k` hops
2. **search(query)**: Search indexed content, returning `(relevant_url, origin_url, depth)` triples

The system must handle large-scale crawls on a single machine with back pressure controls.

## Goals

- **Scalable single-machine crawling** with configurable concurrency and rate limiting
- **Real-time search** that reflects new results as crawlers discover content
- **Controlled resource usage** through bounded queues and rate limiting (back pressure)
- **Resumability** after interruption without losing progress
- **Language-native implementation** using Python stdlib over heavy libraries

## Core Requirements

### index(origin, k)
| Requirement | Implementation |
|---|---|
| BFS depth-limited traversal | `queue.Queue` with `(url, depth)` tuples |
| Never crawl same page twice | Thread-safe `set` of visited URLs |
| Configurable depth k | Passed as parameter, enforced in crawl loop |
| Back pressure: queue limit | `queue.Queue(maxsize=10000)` — blocks on full |
| Back pressure: rate limiting | Token bucket algorithm (per-domain + global) |
| Large-scale design | Thread pool (8 workers default), async I/O-ready architecture |

### search(query)
| Requirement | Implementation |
|---|---|
| Return `(relevant_url, origin_url, depth)` triples | Stored in inverted index with origin/depth metadata |
| Relevance scoring | TF × position bonus (title 3×, heading 2×) × depth factor |
| Search during active indexing | Append-only index files, fresh reads on each query |
| Multi-word queries | Coverage bonus for matching more query terms |

### UI / Monitoring
| Requirement | Implementation |
|---|---|
| Initiate indexing | Dashboard form: URL, depth, workers, queue size |
| Initiate search | Search page with keyword input |
| View indexing progress | Live-updating stats: pages crawled, links found, queue size |
| View queue depth | Progress bar with numeric labels |
| View back pressure status | Color-coded indicator (normal/warning/critical) |
| Crawler control | Pause, resume, stop buttons |

### Resumability
| Requirement | Implementation |
|---|---|
| State checkpointing | Every 10 seconds, full state saved to `data/crawlers/{id}.json` |
| Queue persistence | Up to 1000 queued URLs saved in checkpoint |
| Visited URLs persistence | Saved in checkpoint + append-only log |
| Resume after restart | Crawler service loads saved states on startup |

## Non-Functional Requirements

- **Performance**: 8 concurrent workers per crawler, 10 req/s global rate
- **Storage**: File-based (JSONL), no database dependency
- **Dependencies**: Only Flask; core logic uses Python stdlib
- **Error handling**: Graceful degradation on fetch errors, SSL issues, malformed HTML
- **Monitoring**: Real-time dashboard with 2-second polling

## Architecture

```
Client (Browser/CLI)
    │
    ▼
Flask API (app.py)
    │
    ├── CrawlerService ──► CrawlerEngine (per crawl)
    │                          ├── ThreadPoolExecutor (8 workers)
    │                          ├── queue.Queue (bounded)
    │                          ├── DomainRateLimiter
    │                          └── HTMLParser (stdlib)
    │
    ├── SearchService ──► Storage.search_index()
    │
    └── Storage
         ├── data/index/*.jsonl    (inverted word index)
         ├── data/crawlers/*.json  (crawler state)
         └── data/visited.jsonl    (visit log)
```

## Trade-offs & Assumptions

1. **File-based storage over database**: Simpler setup, no external dependencies. Suitable for single-machine scale. Production would use a proper database.
2. **Simple tokenization**: Regex-based word extraction. Production would use NLP tokenization with stemming/lemmatization.
3. **No robots.txt**: Not implemented for this exercise. Production must respect robots.txt.
4. **SSL verification disabled**: For broad crawling compatibility. Production should verify SSL.
5. **In-memory visited set**: Fast but memory-bounded. For truly massive crawls, a disk-backed set (e.g., Bloom filter) would be needed.
