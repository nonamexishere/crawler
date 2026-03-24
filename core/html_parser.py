"""
HTML Parser — Pure stdlib implementation using html.parser.HTMLParser.

Extracts links and text content from HTML pages without any external
parsing libraries (no BeautifulSoup, lxml, etc.).
"""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag


# Tags whose text content we consider meaningful for indexing
_TEXT_TAGS = {
    "title", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "span", "a", "strong", "em", "b", "i",
    "blockquote", "caption", "label", "summary", "figcaption",
}

# Tags whose text we intentionally skip
_SKIP_TAGS = {"script", "style", "noscript", "svg", "code", "pre"}

# Heading tags get extra weight during indexing
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Schemes we consider valid for crawling
_VALID_SCHEMES = {"http", "https"}

# Simple regex to strip excess whitespace
_WS = re.compile(r"\s+")


class LinkTextExtractor(HTMLParser):
    """
    Feed HTML into this parser to extract:
      - links:    list of absolute URLs found in <a href="…">
      - title:    the page <title> text
      - headings: list of heading texts (h1-h6)
      - text:     concatenated visible text from meaningful tags
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[str] = []
        self.title: str = ""
        self.headings: list[str] = []
        self.text_chunks: list[str] = []
        self.meta_description: str = ""

        # Internal state
        self._tag_stack: list[str] = []
        self._current_text: list[str] = []
        self._in_skip = 0  # nesting depth inside skip tags
        self._in_title = False

    # ── Tag handling ──────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)

        if tag in _SKIP_TAGS:
            self._in_skip += 1
            return

        if tag == "title":
            self._in_title = True
            self._current_text = []

        if tag in HEADING_TAGS:
            self._current_text = []

        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._add_link(href)

        if tag == "meta":
            attr_dict = dict(attrs)
            name = (attr_dict.get("name") or "").lower()
            if name == "description":
                self.meta_description = attr_dict.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in _SKIP_TAGS and self._in_skip > 0:
            self._in_skip -= 1

        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join(self._current_text).strip()
            self.text_chunks.append(self.title)

        if tag in HEADING_TAGS and self._current_text:
            heading = " ".join(self._current_text).strip()
            if heading:
                self.headings.append(heading)

        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_skip > 0:
            return

        cleaned = _WS.sub(" ", data).strip()
        if not cleaned:
            return

        if self._in_title:
            self._current_text.append(cleaned)
            return

        current_tag = self._tag_stack[-1] if self._tag_stack else ""

        if current_tag in HEADING_TAGS:
            self._current_text.append(cleaned)
            self.text_chunks.append(cleaned)
        elif current_tag in _TEXT_TAGS or not current_tag:
            self.text_chunks.append(cleaned)

    # ── Link normalization ────────────────────────────────────

    def _add_link(self, href: str) -> None:
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return

        # Resolve relative URLs
        absolute = urljoin(self.base_url, href)
        # Strip fragment
        absolute, _ = urldefrag(absolute)

        parsed = urlparse(absolute)
        if parsed.scheme not in _VALID_SCHEMES:
            return

        # Normalize: lowercase scheme + host
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
        ).geturl()

        self.links.append(normalized)


def parse_html(html: str, base_url: str) -> dict:
    """
    Parse an HTML string and return extracted data.

    Returns:
        {
            "links": [str],        # absolute URLs
            "title": str,          # page title
            "headings": [str],     # heading texts
            "text": str,           # concatenated visible text
            "meta_description": str
        }
    """
    parser = LinkTextExtractor(base_url)
    try:
        parser.feed(html)
    except Exception:
        pass  # Tolerate malformed HTML

    # Deduplicate links while preserving order
    seen = set()
    unique_links = []
    for link in parser.links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    full_text = " ".join(parser.text_chunks)
    if parser.meta_description:
        full_text = parser.meta_description + " " + full_text

    return {
        "links": unique_links,
        "title": parser.title,
        "headings": parser.headings,
        "text": _WS.sub(" ", full_text).strip(),
        "meta_description": parser.meta_description,
    }
