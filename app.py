"""
Flask API Server — Exposes the crawler and search functionality via REST API
and serves the web-based dashboard UI.
"""

import os
import sys

from flask import Flask, jsonify, request, render_template

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.storage import Storage
from core.rate_limiter import DomainRateLimiter
from services.crawler_service import CrawlerService
from services.search_service import SearchService

# ── Initialize app ────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# Data directory
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Core components
storage = Storage(data_dir=DATA_DIR)
rate_limiter = DomainRateLimiter(
    global_rate=10.0,
    global_capacity=20,
    domain_rate=2.0,
    domain_capacity=5,
)
crawler_service = CrawlerService(storage, rate_limiter)
search_service = SearchService(storage)


# ── Page routes ───────────────────────────────────────────────

@app.route("/")
def dashboard():
    """Main dashboard page."""
    return render_template("index.html")


@app.route("/search-page")
def search_page():
    """Search page UI."""
    return render_template("search.html")


@app.route("/status/<crawler_id>")
def status_page(crawler_id):
    """Detailed status page for a specific crawler."""
    return render_template("status.html", crawler_id=crawler_id)


# ── API: Crawling ─────────────────────────────────────────────

@app.route("/api/index", methods=["POST"])
def start_crawl():
    """
    Start a new web crawl.

    POST body: {"origin": "https://...", "depth": 2, "max_workers": 8, "max_queue_size": 10000}
    """
    data = request.get_json(force=True)
    origin = data.get("origin", "").strip()
    depth = int(data.get("depth", 2))
    max_workers = int(data.get("max_workers", 8))
    max_queue_size = int(data.get("max_queue_size", 10000))

    if not origin:
        return jsonify({"error": "origin URL is required"}), 400

    if not origin.startswith(("http://", "https://")):
        origin = "https://" + origin

    if depth < 0 or depth > 10:
        return jsonify({"error": "depth must be between 0 and 10"}), 400

    crawler = crawler_service.create_crawler(
        origin=origin,
        max_depth=depth,
        max_workers=max_workers,
        max_queue_size=max_queue_size,
    )

    return jsonify({
        "message": "Crawl started",
        "crawler_id": crawler.crawler_id,
        "origin": origin,
        "depth": depth,
    }), 201


@app.route("/api/crawlers", methods=["GET"])
def list_crawlers():
    """List all crawlers with their status."""
    crawlers = crawler_service.list_crawlers()
    return jsonify({"crawlers": crawlers})


@app.route("/api/crawlers/<crawler_id>", methods=["GET"])
def get_crawler(crawler_id):
    """Get detailed status of a specific crawler."""
    crawler = crawler_service.get_crawler(crawler_id)
    if not crawler:
        return jsonify({"error": "Crawler not found"}), 404
    return jsonify(crawler.get_status())


@app.route("/api/crawlers/<crawler_id>/pause", methods=["POST"])
def pause_crawler(crawler_id):
    """Pause a running crawler."""
    if crawler_service.pause_crawler(crawler_id):
        return jsonify({"message": "Crawler paused"})
    return jsonify({"error": "Cannot pause crawler"}), 400


@app.route("/api/crawlers/<crawler_id>/resume", methods=["POST"])
def resume_crawler(crawler_id):
    """Resume a paused crawler."""
    if crawler_service.resume_running_crawler(crawler_id):
        return jsonify({"message": "Crawler resumed"})
    return jsonify({"error": "Cannot resume crawler"}), 400


@app.route("/api/crawlers/<crawler_id>/stop", methods=["POST"])
def stop_crawler(crawler_id):
    """Stop a running crawler."""
    if crawler_service.stop_crawler(crawler_id):
        return jsonify({"message": "Crawler stopped"})
    return jsonify({"error": "Cannot stop crawler"}), 400


# ── API: Search ───────────────────────────────────────────────

@app.route("/search", methods=["GET"])
def search_api():
    """
    Search indexed content.

    Query params: query=<word>&sortBy=relevance&limit=50
    Scoring: (frequency × 10) + 1000 - (depth × 5)
    """
    query = request.args.get("query", "").strip()
    sort_by = request.args.get("sortBy", "relevance")
    limit = int(request.args.get("limit", 50))

    if not query:
        return jsonify({"error": "query parameter is required"}), 400

    results = search_service.search(query, limit=limit, sort_by=sort_by)

    # Format response
    formatted = [
        {
            "relevant_url": r["url"],
            "origin_url": r["origin"],
            "depth": r["depth"],
            "relevance_score": r["relevance_score"],
            "frequency": r.get("frequency", 0),
        }
        for r in results
    ]

    return jsonify({
        "query": query,
        "count": len(formatted),
        "results": formatted,
    })


# Keep the old /api/search endpoint for backward compatibility
@app.route("/api/search", methods=["GET"])
def search_api_legacy():
    """Legacy search endpoint (backward compatible)."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "query parameter 'q' is required"}), 400

    results = search_service.search(query)

    triples = [
        {
            "relevant_url": r["url"],
            "origin_url": r["origin"],
            "depth": r["depth"],
            "relevance_score": r["relevance_score"],
        }
        for r in results
    ]

    return jsonify({
        "query": query,
        "count": len(triples),
        "results": triples,
    })


# ── API: System ───────────────────────────────────────────────

@app.route("/api/system/status", methods=["GET"])
def system_status():
    """Get overall system status."""
    return jsonify(crawler_service.get_system_status())


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🕷️  Web Crawler starting...")
    print("   Dashboard: http://localhost:3600")
    print("   Search:    http://localhost:3600/search?query=<word>&sortBy=relevance")
    print()
    app.run(host="0.0.0.0", port=3600, debug=False, threaded=True)
