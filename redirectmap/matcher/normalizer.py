"""
URL normalization utilities shared across crawler, matcher and exporter.
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """
    Canonical form of a URL:
      - lowercase scheme + netloc
      - strip trailing slash from path
      - drop query string and fragment
    """
    try:
        p = urlparse(url.strip().lower())
        path = p.path.rstrip("/") or "/"
        return urlunparse((p.scheme, p.netloc, path, "", "", ""))
    except Exception:
        return url.strip().lower()


def normalize_path(url: str) -> str:
    """Return only the normalized path component (lowercase, no trailing slash)."""
    try:
        path = urlparse(url.strip().lower()).path.rstrip("/") or "/"
        return path
    except Exception:
        return "/"


def url_hash(url: str) -> str:
    """MD5 of the normalized *path* — used for exact-match lookup."""
    return hashlib.md5(normalize_path(url).encode("utf-8")).hexdigest()


def path_segments(url: str) -> list[str]:
    """['fr', 'produits', 'robot-cuiseur'] from any URL."""
    try:
        return [s for s in urlparse(url).path.strip("/").lower().split("/") if s]
    except Exception:
        return []


def path_segments_json(url: str) -> str:
    """JSON-serialized path segments for SQLite storage."""
    return json.dumps(path_segments(url), ensure_ascii=False)


def parent_path(url: str) -> str | None:
    """Return the parent directory path, or None if already at root."""
    segs = path_segments(url)
    if len(segs) <= 1:
        return None
    return "/" + "/".join(segs[:-1])


def level_one_path(url: str) -> str | None:
    """Return the first path segment as a root path, e.g. /produits."""
    segs = path_segments(url)
    if not segs:
        return None
    return "/" + segs[0]
