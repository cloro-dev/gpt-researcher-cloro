"""cloro retrievers for GPT Researcher.

Install next to GPT Researcher (0.16.1 or later) and select a retriever by name::

    pip install gpt-researcher-cloro
    export CLORO_API_KEY=...
    export RETRIEVER=cloro          # Google organic results
    export RETRIEVER=cloro_aimode   # Google AI Mode answer and its sources

The two retrievers are registered under the ``gpt_researcher.retrievers``
entry-point group. Both return ``[]`` on any failure, so one provider cannot
stop a research run.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote_plus

import requests

__all__ = ["CloroAIModeSearch", "CloroSearch"]
__version__ = "0.1.0"

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloro.dev"
DEFAULT_COUNTRY = "US"
# The body of a link result is a preview. GPT Researcher scrapes the page.
MAX_BODY_CHARS = 500
# Google results arrive in a few seconds. AI Mode answers can take a minute.
GOOGLE_TIMEOUT_SECONDS = 60
AIMODE_TIMEOUT_SECONDS = 180


def _settings() -> tuple[str, str]:
    api_key = (os.environ.get("CLORO_API_KEY") or "").strip()
    country = (os.environ.get("CLORO_COUNTRY") or DEFAULT_COUNTRY).strip().upper()
    return api_key, country


def _preview(text: Any) -> str:
    return " ".join(str(text or "").split())[:MAX_BODY_CHARS]


def _is_direct_link(url: Any) -> bool:
    # A link can be empty, a Google redirect (/goto) or a Google search or
    # shopping page (/search). Keep only direct links to a site.
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    return "google.com/goto" not in url and "google.com/search" not in url


def _post(path: str, payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any] | None:
    """Send one request to the cloro API. Return ``result``, or None on any failure."""
    if not api_key:
        logger.error(
            "cloro: CLORO_API_KEY is not set. Get a key at https://dashboard.cloro.dev/api-keys?utm_source=gpt-researcher-cloro&utm_medium=byok"
        )
        return None
    try:
        response = requests.post(
            f"{API_BASE}{path}",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"gpt-researcher-cloro/{__version__}",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("cloro: request to %s failed: %s", path, type(exc).__name__)
        return None
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code >= 400 or not isinstance(data, dict) or not data.get("success"):
        error = data.get("error") if isinstance(data, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        logger.warning("cloro: %s returned HTTP %s (%s)", path, response.status_code, code or "no error code")
        return None
    result = data.get("result")
    return result if isinstance(result, dict) else None


class CloroSearch:
    """Google organic results from ``POST /v1/monitor/google``.

    Results are links with a short snippet (``requires_scraping = True``).
    GPT Researcher scrapes each page for its content. One request costs
    5 cloro credits and returns one page of Google results (about 10 links).
    """

    requires_scraping = True

    def __init__(self, query: str, query_domains: list[str] | None = None, **kwargs: Any):
        self.query = query
        self.query_domains = [d.strip() for d in (query_domains or []) if d and d.strip()]
        self.api_key, self.country = _settings()

    def _query(self) -> str:
        if not self.query_domains:
            return self.query
        sites = " OR ".join(f"site:{domain}" for domain in self.query_domains)
        return f"{self.query} {sites}"

    def search(self, max_results: int = 7) -> list[dict[str, Any]]:
        limit = max(1, int(max_results or 7))
        result = _post(
            "/v1/monitor/google",
            {"query": self._query(), "country": self.country},
            self.api_key,
            GOOGLE_TIMEOUT_SECONDS,
        )
        if result is None:
            return []
        results = [
            {
                "title": item.get("title") or "",
                "href": item["link"],
                "body": _preview(item.get("snippet")),
            }
            for item in result.get("organicResults") or []
            if isinstance(item, dict) and _is_direct_link(item.get("link"))
        ]
        return results[:limit]


class CloroAIModeSearch:
    """Google AI Mode answer and its cited sources from ``POST /v1/monitor/aimode``.

    The first result is the AI Mode answer text, given as ``raw_content`` so
    GPT Researcher uses it without a scrape. Its ``href`` is the Google AI Mode
    URL for the query. The other results are the sources that the answer cites.
    They have no ``raw_content``, so GPT Researcher scrapes them. One request
    costs 6 cloro credits. ``query_domains`` is accepted but not applied.
    """

    requires_scraping = False

    def __init__(self, query: str, query_domains: list[str] | None = None, **kwargs: Any):
        self.query = query
        self.query_domains = list(query_domains or [])
        self.api_key, self.country = _settings()

    def search(self, max_results: int = 7) -> list[dict[str, Any]]:
        limit = max(1, int(max_results or 7))
        result = _post(
            "/v1/monitor/aimode",
            {"prompt": self.query, "country": self.country, "include": {"markdown": True}},
            self.api_key,
            AIMODE_TIMEOUT_SECONDS,
        )
        if result is None:
            return []
        answer = result.get("markdown") or result.get("text") or ""
        results: list[dict[str, Any]] = []
        if answer.strip():
            results.append(
                {
                    "title": f"Google AI Mode: {self.query}",
                    "href": f"https://www.google.com/search?udm=50&q={quote_plus(self.query)}",
                    "body": _preview(answer),
                    "raw_content": f"Google AI Mode answer to: {self.query}\n\n{answer}",
                }
            )
        seen = set()
        for source in result.get("sources") or []:
            url = source.get("url") if isinstance(source, dict) else None
            if not _is_direct_link(url) or url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "title": source.get("label") or "",
                    "href": url,
                    "body": _preview(source.get("description")),
                }
            )
        return results[:limit]
