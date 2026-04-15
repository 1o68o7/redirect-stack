"""
Nginx redirect configuration exporter.

Generates a map + server block snippet ready for inclusion in nginx.conf.
Uses the efficient `map` directive for large rule sets (avoids slow if-chains).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from redirectmap import db as _db


def _path_from_url(url: str, source_domain: str) -> str:
    if source_domain:
        url = url.replace(source_domain.rstrip("/"), "")
    return urlparse(url).path or "/"


_HEADER = """\
# ─────────────────────────────────────────────────────────────────────────────
# redirectmap — Nginx redirect rules
# Generated: {ts}
# Total rules: {total}
# ─────────────────────────────────────────────────────────────────────────────
# Instructions:
#   1. Include this file from your nginx.conf or site config:
#        include /etc/nginx/conf.d/redirects.conf;
#   2. Add in your server block:
#        include /path/to/redirect_plan_server.conf;
#   3. Test: nginx -t && systemctl reload nginx
# ─────────────────────────────────────────────────────────────────────────────

"""


def export_nginx(db_path: str, output_dir: str, source_domain: str = "", target_domain: str = "") -> tuple[Path, Path]:
    """
    Returns (map_file_path, server_block_path).

    map_file    → redirect_plan_map.conf    (include in http block)
    server_file → redirect_plan_server.conf (include in server block)
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _db.get_conn(db_path) as conn:
        rows = _db.get_redirects(conn)

    map_lines:    list[str] = []
    server_lines: list[str] = []

    for row in rows:
        src_path = _path_from_url(row["source_url"], source_domain)
        tgt_url  = row["target_url"]
        if tgt_url.startswith("/") and target_domain:
            tgt_url = target_domain.rstrip("/") + tgt_url

        # Escape spaces in path
        src_esc = src_path.replace(" ", "%20")
        map_lines.append(f'    "{src_esc}" "{tgt_url}";')

    total = len(map_lines)
    header = _HEADER.format(ts=datetime.now().isoformat(timespec="seconds"), total=total)

    # map block (http context)
    map_content = header
    map_content += "map $request_uri $redirect_uri {\n"
    map_content += "    default \"\";\n"
    map_content += "\n".join(map_lines) + "\n"
    map_content += "}\n"

    map_path = out / "redirect_plan_map.conf"
    map_path.write_text(map_content, encoding="utf-8")

    # server block snippet
    server_content = """\
# Add this block inside your server {} block:
if ($redirect_uri) {
    return 301 $redirect_uri;
}
"""
    server_path = out / "redirect_plan_server.conf"
    server_path.write_text(server_content, encoding="utf-8")

    return map_path, server_path
