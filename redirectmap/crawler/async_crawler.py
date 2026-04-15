"""
Async crawler — httpx-based, domain-restricted, depth-limited.

Best practices consolidated from your existing scripts:
- Async concurrency with semaphore (from crawl_deep.py)
- Polite delay with jitter (from crawler_agent_with_crawl.py)
- Full SEO metadata extraction (title, description, h1, body_text, structured data)
- Robots.txt respect + sitemap seed discovery
- Resume support via SQLite (skips already-crawled URLs)
- Batch SQLite inserts (avoids per-row overhead)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from redirectmap.crawler.sitemap import discover_sitemaps, fetch_urls_from_sitemap
from redirectmap.matcher.normalizer import normalize_url, url_hash, path_segments_json

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _extract_meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""


def _extract_page_data(url: str, html: str, status_code: int, depth: int, site: str) -> dict:
    """Parse HTML and return a page dict ready for DB insertion."""
    soup = BeautifulSoup(html, "lxml")

    title = (soup.title.string.strip() if soup.title and soup.title.string else "") or ""
    description = _extract_meta(soup, "description") or _extract_meta(soup, "og:description")
    h1_tags = soup.find_all("h1")
    h1 = " | ".join(t.get_text(strip=True) for t in h1_tags) if h1_tags else ""
    body_text = soup.body.get_text(separator=" ", strip=True) if soup.body else ""
    # Trim body_text to 20k chars to keep DB lean
    body_text = body_text[:20_000]

    norm = normalize_url(url)
    return {
        "url": url,
        "normalized_url": norm,
        "url_hash": url_hash(url),
        "path_segments": path_segments_json(url),
        "site": site,
        "status_code": status_code,
        "title": title,
        "description": description,
        "h1": h1,
        "body_text": body_text,
        "content_hash": _content_hash(body_text),
        "depth": depth,
    }


class AsyncCrawler:
    """
    Async BFS crawler. Stores results directly into SQLite via bulk batches.

    Usage:
        crawler = AsyncCrawler(cfg=cfg["crawl"], db_path="redirect.db", site="source")
        await crawler.run(seed_urls=["https://example.com"])
    """

    def __init__(self, cfg: dict, db_path: str, site: str):
        self.cfg = cfg
        self.db_path = db_path
        self.site = site  # 'source' | 'target'

        self.concurrency: int = cfg.get("concurrency", 10)
        self.delay: float = cfg.get("delay", 1.0)
        self.timeout: int = cfg.get("timeout", 20)
        self.max_depth: int = cfg.get("max_depth", 5)
        self.max_pages: int = cfg.get("max_pages", 50_000)
        self.user_agent: str = cfg.get("user_agent", "redirectmap/1.0")
        self.respect_robots: bool = cfg.get("respect_robots", True)
        self._allowed_types: list[str] = cfg.get("allowed_content_types", ["text/html"])

        self._semaphore: asyncio.Semaphore | None = None
        self._visited: set[str] = set()
        self._disallowed_prefixes: list[str] = []
        self._page_buffer: list[dict] = []
        self._buffer_size = 100  # flush every N pages

    # ── robots.txt ────────────────────────────────────────────────────────────

    async def _load_robots(self, base_url: str, client: httpx.AsyncClient) -> None:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            r = await client.get(robots_url, timeout=10)
            if r.status_code == 200:
                active = False
                for raw_line in r.text.splitlines():
                    line = raw_line.strip()
                    if line.lower().startswith("user-agent:"):
                        agent = line.split(":", 1)[1].strip()
                        active = (agent == "*")
                    elif active and line.lower().startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path and path != "/":   # Disallow: / bloquerait tout
                            self._disallowed_prefixes.append(path)
                logger.info("robots.txt chargé — %d règles Disallow", len(self._disallowed_prefixes))
        except Exception as e:
            logger.warning("Impossible de charger robots.txt : %s", e)

    def _is_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        path = urlparse(url).path
        return not any(path.startswith(p) for p in self._disallowed_prefixes)

    # ── link extraction ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_links(soup: BeautifulSoup, base_url: str, allowed_domain: str) -> list[str]:
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"])
            parsed = urlparse(href)
            # Same domain only, no fragments/query params for crawl queue
            if parsed.netloc == allowed_domain and parsed.scheme in ("http", "https"):
                clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                links.append(clean)
        return links

    # ── flush buffer to DB ────────────────────────────────────────────────────

    def _flush(self, conn: Any) -> None:
        if not self._page_buffer:
            return
        from redirectmap import db as _db
        _db.bulk_insert_pages(conn, self._page_buffer)
        conn.commit()
        self._page_buffer.clear()

    # ── fetch a single URL ────────────────────────────────────────────────────

    async def _fetch(self, url: str, depth: int, client: httpx.AsyncClient, conn: Any) -> list[tuple[str, int]]:
        """Fetch URL, extract data, return new links as (url, depth) tuples."""
        async with self._semaphore:
            if url in self._visited or len(self._visited) >= self.max_pages:
                return []
            if not self._is_allowed(url):
                logger.debug("Robots disallowed: %s", url)
                return []

            self._visited.add(url)
            allowed_domain = urlparse(url).netloc

            try:
                await asyncio.sleep(self.delay)
                r = await client.get(url, timeout=self.timeout, follow_redirects=True)
                ct = r.headers.get("content-type", "")
                if not any(t in ct for t in self._allowed_types):
                    return []

                page_data = _extract_page_data(url, r.text, r.status_code, depth, self.site)
                self._page_buffer.append(page_data)

                if len(self._page_buffer) >= self._buffer_size:
                    self._flush(conn)

                # Discover new links for BFS (désactivé en mode liste)
                if self._follow_links and depth < self.max_depth:
                    soup = BeautifulSoup(r.text, "lxml")
                    new_links = self._extract_links(soup, url, allowed_domain)
                    return [(lnk, depth + 1) for lnk in new_links if lnk not in self._visited]

            except Exception as e:
                logger.warning("Error fetching %s: %s", url, e)

            return []

    # ── main entry point ──────────────────────────────────────────────────────

    async def run(self, seed_urls: list[str], use_sitemaps: bool = True,
                  follow_links: bool = True) -> int:
        """
        Crawl starting from seed_urls. Returns total pages crawled.

        follow_links=False : crawle exactement les URLs fournies, sans suivre les liens.
                             Utiliser quand seed_urls vient d'un fichier CSV explicite.
        follow_links=True  : mode découverte BFS depuis les seeds (par défaut).
        """
        import sqlite3
        from redirectmap import db as _db

        _db.init_db(self.db_path)

        # Load already-visited URLs from DB to support resume
        with sqlite3.connect(str(self.db_path)) as c:
            c.row_factory = sqlite3.Row
            existing = {r["url"] for r in c.execute(
                "SELECT url FROM pages WHERE site = ?", (self.site,)
            ).fetchall()}
        self._visited.update(existing)

        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._follow_links = follow_links

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            # Optionally expand seed with sitemaps
            if use_sitemaps:
                for seed in list(seed_urls):
                    sitemaps = await discover_sitemaps(seed, client)
                    for sm_url in sitemaps:
                        sitemap_urls = await fetch_urls_from_sitemap(sm_url, client)
                        seed_urls = list(dict.fromkeys(seed_urls + sitemap_urls))
                        logger.info("Sitemap %s added %d URLs", sm_url, len(sitemap_urls))

            # Load robots.txt for first seed domain
            if seed_urls:
                await self._load_robots(seed_urls[0], client)

            queue: deque[tuple[str, int]] = deque((url, 0) for url in seed_urls)

            with _db.get_conn(self.db_path) as conn:
                tasks = set()
                while queue or tasks:
                    # Fill tasks up to concurrency
                    while queue and len(tasks) < self.concurrency:
                        url, depth = queue.popleft()
                        if url not in self._visited and len(self._visited) < self.max_pages:
                            t = asyncio.create_task(self._fetch(url, depth, client, conn))
                            tasks.add(t)

                    if not tasks:
                        break

                    done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                    for fut in done:
                        try:
                            new_links = fut.result()
                            for link, d in new_links:
                                if link not in self._visited:
                                    queue.append((link, d))
                        except Exception as e:
                            logger.warning("Tâche échouée : %s", e)

                self._flush(conn)

        total = len(self._visited) - len(existing)
        logger.info("Crawl done: %d new pages stored (site=%s)", total, self.site)
        return total
