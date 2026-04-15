"""
Browser-based crawler using camoufox (stealth Firefox).

Why camoufox instead of httpx:
  - Renders JavaScript-heavy pages (Vue/React SPAs, lazy-loaded content)
  - Evades bot-detection (Cloudflare, DataDome, PerimeterX)
  - Extracts dynamically injected structured data (JSON-LD, microdata)
  - Critical for e-commerce: EAN13/GTIN, prices, SKU, stock status are
    often rendered client-side and invisible to a plain HTTP client

E-commerce data extracted per page:
  - Structured data (JSON-LD): Product, Offer, BreadcrumbList, Article
  - EAN13 / GTIN (from JSON-LD → offers.gtin* or meta[itemprop=gtin13])
  - Price + currency (from JSON-LD → offers.price)
  - SKU / product ID
  - Breadcrumb path (useful for hierarchical matching context)

Install:
  pip install "camoufox[geoip]"
  python -m camoufox fetch        # downloads Firefox (~100MB, once)

Usage in pipeline:
  crawler = BrowserCrawler(cfg=cfg["crawl"], db_path="redirect.db", site="source")
  await crawler.run(seed_urls=["https://example.com"])
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from redirectmap.crawler.sitemap import discover_sitemaps, fetch_urls_from_sitemap
from redirectmap.matcher.normalizer import normalize_url, url_hash, path_segments_json

logger = logging.getLogger(__name__)

# ─── E-commerce structured data extraction ───────────────────────────────────

def _extract_jsonld(html: str) -> list[dict]:
    """Parse all <script type='application/ld+json'> blocks."""
    soup = BeautifulSoup(html, "lxml")
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except Exception:
            pass
    return results


def _extract_ecommerce(html: str) -> dict:
    """
    Extract e-commerce signals from JSON-LD and HTML meta attributes.
    Returns a dict with keys: ean, gtin, sku, price, currency, brand,
    availability, breadcrumb, product_name, product_type.
    """
    data: dict = {
        "ean": None, "gtin": None, "sku": None,
        "price": None, "currency": None, "brand": None,
        "availability": None, "breadcrumb": [],
        "product_name": None, "product_type": None,
    }

    jsonld_blocks = _extract_jsonld(html)
    for block in jsonld_blocks:
        if not isinstance(block, dict):   # ignorer les strings/ints dans les tableaux JSON-LD
            continue
        btype = block.get("@type", "")

        # ── Product ──────────────────────────────────────────────────────────
        if btype == "Product":
            data["product_name"] = block.get("name") or data["product_name"]
            data["sku"]          = block.get("sku") or data["sku"]
            data["product_type"] = block.get("category") or data["product_type"]

            # brand peut être un dict {"@type":"Brand","name":"..."} ou une string
            brand = block.get("brand")
            if isinstance(brand, dict):
                data["brand"] = brand.get("name") or data["brand"]
            elif isinstance(brand, str):
                data["brand"] = brand or data["brand"]

            # GTIN variants (EAN13 = gtin13)
            for key in ("gtin13", "gtin8", "gtin14", "gtin12", "gtin", "isbn"):
                val = block.get(key)
                if val:
                    data["gtin"] = str(val)
                    if key == "gtin13":
                        data["ean"] = str(val)
                    break

            # Offers — peut être un dict, une liste, une string ou None
            offers = block.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                offers = {}
            data["price"]        = offers.get("price") or data["price"]
            data["currency"]     = offers.get("priceCurrency") or data["currency"]
            data["availability"] = offers.get("availability") or data["availability"]
            # GTIN inside offer
            if not data["gtin"]:
                for key in ("gtin13", "gtin8", "gtin14", "gtin12", "gtin"):
                    val = offers.get(key)
                    if val:
                        data["gtin"] = str(val)
                        if key == "gtin13":
                            data["ean"] = str(val)
                        break

        # ── BreadcrumbList ────────────────────────────────────────────────────
        elif btype == "BreadcrumbList":
            items = block.get("itemListElement", [])
            if not isinstance(items, list):
                items = []
            breadcrumb = []
            for el in sorted(
                (x for x in items if isinstance(x, dict)),
                key=lambda x: x.get("position", 0) if isinstance(x.get("position"), (int, float)) else 0,
            ):
                item_ref = el.get("item")
                item_url = ""
                if isinstance(item_ref, dict):
                    item_url = item_ref.get("@id", "") or item_ref.get("url", "")
                elif isinstance(item_ref, str):
                    item_url = item_ref
                breadcrumb.append({"name": el.get("name", ""), "url": item_url})
            data["breadcrumb"] = breadcrumb

    # Fallback: microdata / meta itemprop
    if not data["ean"]:
        soup = BeautifulSoup(html, "lxml")
        for attr in ("gtin13", "gtin", "ean"):
            tag = soup.find(attrs={"itemprop": attr})
            if tag:
                data["ean"] = tag.get("content") or tag.get_text(strip=True)
                data["gtin"] = data["ean"]
                break

    return data


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _extract_page_data(url: str, html: str, status_code: int, depth: int, site: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    # Standard SEO fields
    title = (soup.title.string.strip() if soup.title and soup.title.string else "") or ""
    desc_tag = (soup.find("meta", attrs={"name": "description"}) or
                soup.find("meta", attrs={"property": "og:description"}))
    description = desc_tag["content"].strip() if desc_tag and desc_tag.get("content") else ""
    h1_tags = soup.find_all("h1")
    h1 = " | ".join(t.get_text(strip=True) for t in h1_tags) if h1_tags else ""
    body_text = (soup.body.get_text(separator=" ", strip=True) if soup.body else "")[:20_000]

    # E-commerce structured data
    ecom = _extract_ecommerce(html)

    norm = normalize_url(url)
    return {
        "url":            url,
        "normalized_url": norm,
        "url_hash":       url_hash(url),
        "path_segments":  path_segments_json(url),
        "site":           site,
        "status_code":    status_code,
        "title":          title,
        "description":    description,
        "h1":             h1,
        "body_text":      body_text,
        "content_hash":   _content_hash(body_text),
        "depth":          depth,
        "structured_data": json.dumps(ecom, ensure_ascii=False),
    }


# ─── Camoufox crawler ─────────────────────────────────────────────────────────

class BrowserCrawler:
    """
    Async stealth-browser crawler based on camoufox.

    Designed for JS-heavy / bot-protected sites and e-commerce catalogues
    where plain HTTP clients miss dynamically injected content.

    Falls back gracefully if camoufox is not installed (raises ImportError
    with actionable message instead of crashing silently).
    """

    def __init__(self, cfg: dict, db_path: str, site: str):
        self.cfg     = cfg
        self.db_path = db_path
        self.site    = site

        self.concurrency:     int   = min(cfg.get("concurrency", 2), 5)  # browser : 2 par défaut, 5 max
        self.delay:           float = cfg.get("delay", 2.0)
        self.timeout:         int   = cfg.get("timeout", 60)   # 60s pour les sites lents
        self.max_depth:       int   = cfg.get("max_depth", 5)
        self.max_pages:       int   = cfg.get("max_pages", 50_000)
        self.respect_robots:  bool  = cfg.get("respect_robots", True)
        self._allowed_types:  list  = cfg.get("allowed_content_types", ["text/html"])
        self._proxies:        list  = cfg.get("proxies", [])  # ["http://ip:port", ...]

        self._visited:       set[str]   = set()
        self._disallowed:    list[str]  = []
        self._page_buffer:   list[dict] = []
        self._buffer_size:   int        = 50  # flush every N pages (browsers use more RAM)

    # ── Robots.txt ────────────────────────────────────────────────────────────

    async def _load_robots(self, base_url: str) -> None:
        """
        Charge robots.txt via httpx (texte brut, pas via le navigateur).
        Parse uniquement la section User-agent: * pour éviter les faux positifs.
        """
        import httpx
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(robots_url)
            if r.status_code != 200:
                return
            # Parse : ne retenir que les règles de la section User-agent: *
            active = False
            for raw_line in r.text.splitlines():
                line = raw_line.strip()
                if line.lower().startswith("user-agent:"):
                    agent = line.split(":", 1)[1].strip()
                    active = (agent == "*")
                elif active and line.lower().startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    if path and path != "/":   # Disallow: / bloquerait TOUT — on l'ignore
                        self._disallowed.append(path)
            logger.info("robots.txt chargé — %d règles Disallow", len(self._disallowed))
        except Exception as e:
            logger.warning("Impossible de charger robots.txt : %s", e)

    def _is_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        path = urlparse(url).path
        blocked = any(path.startswith(p) for p in self._disallowed)
        if blocked:
            logger.info("robots.txt bloque : %s", url)
        return not blocked

    # ── Link extraction ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_links(html: str, base_url: str, allowed_domain: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"])
            parsed = urlparse(href)
            if parsed.netloc == allowed_domain and parsed.scheme in ("http", "https"):
                clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                links.append(clean)
        return links

    # ── Buffer flush ──────────────────────────────────────────────────────────

    def _flush(self, conn) -> None:
        if not self._page_buffer:
            return
        from redirectmap import db as _db
        _db.bulk_insert_pages(conn, self._page_buffer)
        conn.commit()
        self._page_buffer.clear()

    # ── Single page fetch ─────────────────────────────────────────────────────

    async def _fetch_one(self, url: str, depth: int, browser, sem: asyncio.Semaphore) -> dict | None:
        """
        Fetch a single URL with the browser. Returns page_data dict or None on failure.

        Timeouts explicites sur chaque opération pour éviter tout blocage :
          - page.goto()    : 25s  (domcontentloaded)
          - page.content() : 8s   (récupération du DOM)
          - page.close()   : 5s   (fermeture du tab)
        Le timeout global par URL est appliqué dans run() via asyncio.wait_for.
        """
        if not self._is_allowed(url):
            return None

        logger.info("→ Browser : %s", url)
        async with sem:
            await asyncio.sleep(self.delay)
            page = None
            try:
                page = await browser.new_page()
                status = 0

                try:
                    response = await page.goto(
                        url,
                        timeout=25_000,            # 25s — fixe, indépendant du cfg timeout
                        wait_until="domcontentloaded",
                    )
                    status = response.status if response else 0
                except Exception as nav_err:
                    if "Timeout" in str(nav_err):
                        logger.debug("Navigation timeout %s — extraction partielle...", url)
                    else:
                        raise

                # 2s pour le JSON-LD (best-effort)
                try:
                    await page.wait_for_selector(
                        'script[type="application/ld+json"]',
                        timeout=2_000,
                    )
                except Exception:
                    pass

                html = ""
                try:
                    html = await asyncio.wait_for(page.content(), timeout=8.0)
                except Exception:
                    pass

                if html and len(html) >= 200:
                    logger.info("✓ browser [%d] %s", status, url)
                    return _extract_page_data(url, html, status, depth, self.site)

                logger.debug("Browser: HTML insuffisant (%d chars) %s", len(html), url)
                return None

            except Exception as e:
                logger.debug("Browser échec %s : %s", url, str(e).splitlines()[0])
                return None
            finally:
                if page:
                    try:
                        # Timeout sur close() — critique : un tab bloqué peut figer tout le gather
                        await asyncio.wait_for(page.close(), timeout=5.0)
                    except Exception:
                        pass

    async def _httpx_fetch(self, url: str, depth: int, http) -> dict | None:
        """
        Fallback httpx pour les URLs que le navigateur n'a pas pu charger.
        Utile pour les pages statiques bloquées par bot-protection sur le browser.
        """
        try:
            resp = await http.get(url, follow_redirects=True, timeout=20)
            html = resp.text
            if not html or len(html) < 100:
                logger.warning("✗ httpx: réponse vide %s", url)
                return None
            logger.info("↩ httpx  [%d] %s", resp.status_code, url)
            return _extract_page_data(url, html, resp.status_code, depth, self.site)
        except Exception as e:
            logger.warning("✗ httpx échec %s : %s", url, str(e).splitlines()[0])
            return None

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self, seed_urls: list[str], use_sitemaps: bool = True) -> int:
        """
        Crawl seed_urls avec un navigateur Firefox stealth (camoufox).
        Retourne le nombre de nouvelles pages stockées.

        Architecture :
          Phase 1 — Browser (camoufox) : asyncio.gather + Semaphore
          Phase 2 — httpx fallback     : pour les URLs que le browser n'a pas chargées
          Phase 3 — Bulk insert SQLite : hors contexte browser pour éviter les conflits
        """
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            raise ImportError(
                "camoufox est requis pour le mode navigateur.\n"
                "Installation :\n"
                "  pip install 'camoufox[geoip]'\n"
                "  python -m camoufox fetch\n"
            )

        import sqlite3
        import httpx
        from redirectmap import db as _db

        _db.init_db(self.db_path)

        # Chargement des URLs déjà crawlées (reprise)
        with sqlite3.connect(str(self.db_path)) as c:
            c.row_factory = sqlite3.Row
            existing = {r["url"] for r in c.execute(
                "SELECT url FROM pages WHERE site = ?", (self.site,)
            ).fetchall()}
        self._visited.update(existing)

        # Expansion par sitemap — une seule requête par domaine
        if use_sitemaps:
            seen_domains: set[str] = set()
            async with httpx.AsyncClient(
                headers={"User-Agent": self.cfg.get("user_agent", "redirectmap/1.0")}
            ) as http:
                for seed in list(seed_urls):
                    domain = urlparse(seed).netloc
                    if domain in seen_domains:
                        continue
                    seen_domains.add(domain)
                    sitemaps = await discover_sitemaps(seed, http)
                    for sm_url in sitemaps:
                        sm_urls = await fetch_urls_from_sitemap(sm_url, http)
                        seed_urls = list(dict.fromkeys(seed_urls + sm_urls))
                        logger.info("Sitemap %s → %d URLs", sm_url, len(sm_urls))

        # Filtrer les URLs déjà connues et respecter max_pages
        to_crawl = [
            u for u in seed_urls
            if u not in self._visited
        ][:self.max_pages]

        if not to_crawl:
            logger.info("Toutes les URLs sont déjà crawlées.")
            return 0

        logger.info("Démarrage crawl navigateur — %d URLs, site=%s", len(to_crawl), self.site)

        proxy_cfg = None
        if self._proxies:
            proxy_cfg = {"server": self._proxies[0]}

        # ── Phase 1 : Browser ─────────────────────────────────────────────────

        sem = asyncio.Semaphore(self.concurrency)
        results: list[dict] = []
        failed_urls: list[str] = []

        # Chargement robots.txt via httpx AVANT d'ouvrir le navigateur
        await self._load_robots(to_crawl[0])

        # Hard cap par URL = 25s navigation + 8s content + 5s close + 2s buffer = 40s
        _HARD_CAP = 40.0

        async def _safe_fetch(url: str) -> dict | None:
            """Wrap _fetch_one avec un timeout absolu — garantit qu'aucune coroutine ne bloque."""
            try:
                return await asyncio.wait_for(
                    self._fetch_one(url, 0, browser, sem),
                    timeout=_HARD_CAP,
                )
            except asyncio.TimeoutError:
                logger.warning("✗ Hard-cap dépassé (%ds) %s", int(_HARD_CAP), url)
                return None
            except Exception as e:
                logger.warning("✗ Erreur %s : %s", url, str(e).splitlines()[0])
                return None

        browser_ctx = AsyncCamoufox(headless=True, proxy=proxy_cfg)
        browser = await browser_ctx.__aenter__()
        try:
            fetched = await asyncio.gather(*[_safe_fetch(u) for u in to_crawl])
        finally:
            # Fermeture gracieuse — le browser peut crasher sur des runs longs, on ignore
            try:
                await browser_ctx.__aexit__(None, None, None)
            except Exception as close_err:
                logger.warning("Fermeture navigateur : %s", str(close_err).splitlines()[0])

        for url, item in zip(to_crawl, fetched):
            if isinstance(item, dict):
                results.append(item)
            else:
                failed_urls.append(url)

        logger.info("Browser : %d OK / %d à retenter via httpx", len(results), len(failed_urls))

        # ── Phase 2 : httpx fallback ──────────────────────────────────────────

        if failed_urls:
            logger.info("Fallback httpx pour %d URLs...", len(failed_urls))
            headers = {
                "User-Agent": self.cfg.get("user_agent", "redirectmap/1.0"),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            sem_http = asyncio.Semaphore(5)

            async def _bounded(u: str) -> dict | None:
                async with sem_http:
                    await asyncio.sleep(0.3)
                    return await self._httpx_fetch(u, 0, http)

            async with httpx.AsyncClient(headers=headers, follow_redirects=True) as http:
                http_results = await asyncio.gather(
                    *[_bounded(u) for u in failed_urls],
                    return_exceptions=True,
                )

            for item in http_results:
                if isinstance(item, dict):
                    results.append(item)

        # ── Phase 3 : Persistance ─────────────────────────────────────────────

        if results:
            with _db.get_conn(self.db_path) as conn:
                n = _db.bulk_insert_pages(conn, results)
            logger.info("Crawl terminé — %d pages stockées (site=%s)", n, self.site)
            return n

        logger.warning("Aucune page récupérée.")
        return 0
