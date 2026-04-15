"""
Sitemap & robots.txt discovery helpers.
Returns a flat list of URLs found in sitemap(s).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx


_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_SITEMAP_INDEX_TAG = "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex"
_LOC_TAG = "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"


async def discover_sitemaps(base_url: str, client: httpx.AsyncClient) -> list[str]:
    """Try /robots.txt then /sitemap.xml — return list of sitemap URLs."""
    found: list[str] = []
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # 1. robots.txt
    try:
        r = await client.get(f"{origin}/robots.txt", timeout=10)
        if r.status_code == 200:
            for match in re.findall(r"(?i)^Sitemap:\s*(.+)$", r.text, re.MULTILINE):
                found.append(match.strip())
    except Exception:
        pass

    # 2. Fallback to /sitemap.xml
    if not found:
        found.append(f"{origin}/sitemap.xml")

    return found


async def fetch_urls_from_sitemap(sitemap_url: str, client: httpx.AsyncClient, visited: set[str] | None = None) -> list[str]:
    """Recursively fetch all page URLs from a sitemap or sitemap index."""
    if visited is None:
        visited = set()
    if sitemap_url in visited:
        return []
    visited.add(sitemap_url)

    urls: list[str] = []
    try:
        r = await client.get(sitemap_url, timeout=15)
        if r.status_code != 200:
            return urls
        root = ET.fromstring(r.text)

        # Sitemap index → recurse
        if root.tag == _SITEMAP_INDEX_TAG or root.find(f"{_SITEMAP_INDEX_TAG[1:-1]}", _NS) is not None:
            for loc_el in root.iter(_LOC_TAG):
                child_url = loc_el.text.strip() if loc_el.text else ""
                if child_url and child_url not in visited:
                    child_urls = await fetch_urls_from_sitemap(child_url, client, visited)
                    urls.extend(child_urls)
        else:
            # Regular sitemap
            for loc_el in root.iter(_LOC_TAG):
                url = loc_el.text.strip() if loc_el.text else ""
                if url:
                    urls.append(url)
    except Exception:
        pass

    return urls
