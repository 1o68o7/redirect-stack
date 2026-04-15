"""
Apache .htaccess exporter.

Generates ready-to-deploy 301 RewriteRule directives.
Source domain is stripped from URLs so rules work as path-based patterns.

Consolidated from 5-generate_htaccess_rules.py with improvements:
  - Proper regex escaping of source paths
  - Groups rules by confidence level (high first)
  - Adds header comment with generation metadata
  - Handles fallback redirects separately as a catch-all
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from redirectmap import db as _db


def _path_from_url(url: str, source_domain: str) -> str:
    """Strip domain prefix to get the path portion."""
    if source_domain:
        url = url.replace(source_domain.rstrip("/"), "")
    parsed = urlparse(url)
    return parsed.path or "/"


def _escape_regex(path: str) -> str:
    """Escape regex special chars in a URL path for RewriteRule."""
    # Escape dots and question marks; leave slashes as-is
    return re.sub(r"([.?+*^${}()|[\]\\])", r"\\\1", path)


_HEADER = """\
# ─────────────────────────────────────────────────────────────────────────────
# redirectmap — Apache .htaccess redirect rules
# Generated: {ts}
# Total rules: {total}
# ─────────────────────────────────────────────────────────────────────────────
# Instructions:
#   1. Place this block inside your <VirtualHost> or .htaccess file
#   2. Make sure mod_rewrite is enabled: a2enmod rewrite
#   3. Verify with: apachectl configtest
# ─────────────────────────────────────────────────────────────────────────────

RewriteEngine On

"""


def export_htaccess(db_path: str, output_dir: str, source_domain: str = "", target_domain: str = "") -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _db.get_conn(db_path) as conn:
        rows = _db.get_redirects(conn)

    rules_high:    list[str] = []
    rules_medium:  list[str] = []
    rules_low:     list[str] = []
    fallbacks:     list[str] = []

    for row in rows:
        src_path = _path_from_url(row["source_url"], source_domain)
        tgt_url  = row["target_url"]
        # Prepend target domain if target is a bare path
        if tgt_url.startswith("/") and target_domain:
            tgt_url = target_domain.rstrip("/") + tgt_url

        if row["match_type"] == "fallback":
            fallbacks.append(f"RewriteRule ^{_escape_regex(src_path.lstrip('/'))}$ {tgt_url} [R=301,L]")
            continue

        rule = f"RewriteRule ^{_escape_regex(src_path.lstrip('/'))}$ {tgt_url} [R=301,L]"
        if row["confidence"] == "high":
            rules_high.append(rule)
        elif row["confidence"] == "medium":
            rules_medium.append(rule)
        else:
            rules_low.append(rule)

    total = len(rules_high) + len(rules_medium) + len(rules_low) + len(fallbacks)
    lines = [_HEADER.format(ts=datetime.now().isoformat(timespec="seconds"), total=total)]

    if rules_high:
        lines.append("# ── High confidence (exact / strong cosine / fuzzy ≥85) ──────────────────\n")
        lines.extend(r + "\n" for r in rules_high)

    if rules_medium:
        lines.append("\n# ── Medium confidence ──────────────────────────────────────────────────────\n")
        lines.extend(r + "\n" for r in rules_medium)

    if rules_low:
        lines.append("\n# ── Low confidence (hierarchical) ──────────────────────────────────────────\n")
        lines.extend(r + "\n" for r in rules_low)

    if fallbacks:
        lines.append("\n# ── Fallback (no match found) ───────────────────────────────────────────────\n")
        lines.extend(r + "\n" for r in fallbacks)

    path = out / "redirect_plan.htaccess"
    path.write_text("".join(lines), encoding="utf-8")
    return path
