"""Tests for the HTML parser."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.html_parser import parse_html


class TestParseHtml:
    """Tests for parse_html() function."""

    def test_extracts_title(self):
        html = "<html><head><title>Hello World</title></head><body></body></html>"
        result = parse_html(html, "https://example.com")
        assert result["title"] == "Hello World"

    def test_extracts_links(self):
        html = """
        <html><body>
            <a href="/about">About</a>
            <a href="https://other.com/page">Other</a>
            <a href="#section">Anchor</a>
        </body></html>
        """
        result = parse_html(html, "https://example.com")
        assert "https://example.com/about" in result["links"]
        assert "https://other.com/page" in result["links"]
        # Fragment-only links should be filtered
        assert not any("#section" in link for link in result["links"])

    def test_resolves_relative_urls(self):
        html = '<html><body><a href="/page">Link</a></body></html>'
        result = parse_html(html, "https://example.com/dir/")
        assert "https://example.com/page" in result["links"]

    def test_deduplicates_links(self):
        html = """
        <html><body>
            <a href="/page">Link 1</a>
            <a href="/page">Link 2</a>
        </body></html>
        """
        result = parse_html(html, "https://example.com")
        page_links = [l for l in result["links"] if "/page" in l]
        assert len(page_links) == 1

    def test_extracts_text_content(self):
        html = """
        <html><body>
            <h1>Main Heading</h1>
            <p>This is a paragraph.</p>
        </body></html>
        """
        result = parse_html(html, "https://example.com")
        assert "Main Heading" in result["text"]
        assert "paragraph" in result["text"]

    def test_extracts_headings(self):
        html = """
        <html><body>
            <h1>Title</h1>
            <h2>Subtitle</h2>
            <h3>Section</h3>
        </body></html>
        """
        result = parse_html(html, "https://example.com")
        assert "Title" in result["headings"]
        assert "Subtitle" in result["headings"]
        assert "Section" in result["headings"]

    def test_skips_script_and_style(self):
        html = """
        <html><body>
            <script>var x = 'secret';</script>
            <style>.hidden { display: none; }</style>
            <p>Visible text</p>
        </body></html>
        """
        result = parse_html(html, "https://example.com")
        assert "secret" not in result["text"]
        assert "hidden" not in result["text"]
        assert "Visible text" in result["text"]

    def test_extracts_meta_description(self):
        html = """
        <html><head>
            <meta name="description" content="A test page description">
        </head><body></body></html>
        """
        result = parse_html(html, "https://example.com")
        assert result["meta_description"] == "A test page description"

    def test_filters_non_http_schemes(self):
        html = """
        <html><body>
            <a href="javascript:void(0)">JS</a>
            <a href="mailto:test@example.com">Email</a>
            <a href="https://valid.com">Valid</a>
        </body></html>
        """
        result = parse_html(html, "https://example.com")
        assert len(result["links"]) == 1
        assert "https://valid.com" in result["links"]

    def test_handles_malformed_html(self):
        html = "<html><body><p>Unclosed <b>bold<p>New para</body>"
        result = parse_html(html, "https://example.com")
        # Should not crash
        assert isinstance(result["text"], str)

    def test_empty_html(self):
        result = parse_html("", "https://example.com")
        assert result["links"] == []
        assert result["title"] == ""
        assert result["text"] == ""

    def test_strips_fragments_from_urls(self):
        html = '<html><body><a href="/page#section">Link</a></body></html>'
        result = parse_html(html, "https://example.com")
        assert "https://example.com/page" in result["links"]
        assert not any("#" in link for link in result["links"])
