"""
SQLite storage layer — all pipeline stages read/write through this module.
Uses WAL mode for safe concurrent access and proper indexing for performance.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable


_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    url              TEXT    NOT NULL,
    normalized_url   TEXT    NOT NULL,
    url_hash         TEXT    NOT NULL,        -- MD5 of normalized path (for exact match)
    path_segments    TEXT    NOT NULL,        -- JSON list of path segments
    site             TEXT    NOT NULL,        -- 'source' | 'target'
    status_code      INTEGER,
    title            TEXT    DEFAULT '',
    description      TEXT    DEFAULT '',
    h1               TEXT    DEFAULT '',
    body_text        TEXT    DEFAULT '',
    content_hash     TEXT    DEFAULT '',      -- MD5 of body_text (dedup)
    depth            INTEGER DEFAULT 0,
    structured_data  TEXT    DEFAULT '{}',   -- JSON: EAN, price, SKU, breadcrumb (e-commerce)
    crawled_at       TEXT    DEFAULT (datetime('now')),
    UNIQUE(url, site)                         -- une URL peut exister en source ET en target
);

CREATE INDEX IF NOT EXISTS idx_pages_site      ON pages(site);
CREATE INDEX IF NOT EXISTS idx_pages_url_hash  ON pages(url_hash);
CREATE INDEX IF NOT EXISTS idx_pages_norm_url  ON pages(normalized_url);

CREATE TABLE IF NOT EXISTS classifications (
    page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    cluster_label   INTEGER NOT NULL,
    intention       TEXT    NOT NULL,
    classified_at   TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (page_id)
);

CREATE TABLE IF NOT EXISTS redirects (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url          TEXT    NOT NULL,
    target_url          TEXT    NOT NULL,
    match_type          TEXT    NOT NULL,   -- 'exact'|'cosine'|'fuzzy'|'hierarchical'|'fallback'
    score               REAL    DEFAULT 0.0,
    confidence          TEXT    DEFAULT 'low', -- 'high'|'medium'|'low'
    source_intention    TEXT    DEFAULT '',
    target_intention    TEXT    DEFAULT '',
    created_at          TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_redirects_source ON redirects(source_url);
"""


def init_db(db_path: str | Path) -> None:
    """Initialize database schema."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def get_conn(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a connection with row_factory."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Pages ────────────────────────────────────────────────────────────────────

def insert_page(conn: sqlite3.Connection, page: dict) -> int | None:
    """Insert a crawled page. Returns rowid or None on conflict."""
    sql = """
        INSERT OR IGNORE INTO pages
            (url, normalized_url, url_hash, path_segments, site,
             status_code, title, description, h1, body_text, content_hash, depth, structured_data)
        VALUES
            (:url, :normalized_url, :url_hash, :path_segments, :site,
             :status_code, :title, :description, :h1, :body_text, :content_hash, :depth,
             :structured_data)
    """
    page.setdefault("structured_data", "{}")
    cur = conn.execute(sql, page)
    return cur.lastrowid if cur.rowcount else None


def bulk_insert_pages(conn: sqlite3.Connection, pages: Iterable[dict]) -> int:
    """Bulk insert pages. Returns number of actually inserted rows (ignores conflicts)."""
    rows = list(pages)
    if not rows:
        return 0
    for r in rows:
        r.setdefault("structured_data", "{}")
    sql = """
        INSERT OR IGNORE INTO pages
            (url, normalized_url, url_hash, path_segments, site,
             status_code, title, description, h1, body_text, content_hash, depth, structured_data)
        VALUES
            (:url, :normalized_url, :url_hash, :path_segments, :site,
             :status_code, :title, :description, :h1, :body_text, :content_hash, :depth,
             :structured_data)
    """
    before = conn.total_changes
    conn.executemany(sql, rows)
    return conn.total_changes - before


def get_pages_by_site(conn: sqlite3.Connection, site: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM pages WHERE site = ?", (site,)
    ).fetchall()


def count_pages(conn: sqlite3.Connection, site: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM pages WHERE site = ?", (site,)
    ).fetchone()[0]


# ─── Classifications ──────────────────────────────────────────────────────────

def upsert_classification(conn: sqlite3.Connection, page_id: int, cluster_label: int, intention: str) -> None:
    conn.execute("""
        INSERT INTO classifications (page_id, cluster_label, intention)
        VALUES (?, ?, ?)
        ON CONFLICT(page_id) DO UPDATE SET
            cluster_label = excluded.cluster_label,
            intention     = excluded.intention,
            classified_at = datetime('now')
    """, (page_id, cluster_label, intention))


# ─── Redirects ────────────────────────────────────────────────────────────────

def bulk_insert_redirects(conn: sqlite3.Connection, redirects: Iterable[dict]) -> int:
    rows = list(redirects)
    if not rows:
        return 0
    sql = """
        INSERT INTO redirects
            (source_url, target_url, match_type, score, confidence,
             source_intention, target_intention)
        VALUES
            (:source_url, :target_url, :match_type, :score, :confidence,
             :source_intention, :target_intention)
    """
    conn.executemany(sql, rows)
    return len(rows)


def get_redirects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM redirects ORDER BY match_type, score DESC"
    ).fetchall()


def get_redirect_stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("""
        SELECT match_type, confidence, COUNT(*) as cnt
        FROM redirects
        GROUP BY match_type, confidence
        ORDER BY match_type, confidence
    """).fetchall()
    return [dict(r) for r in rows]
