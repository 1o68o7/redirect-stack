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
# Total rules: {total}{vhost_note}
# ─────────────────────────────────────────────────────────────────────────────
# Instructions:
#   1. Include this file from your nginx.conf or site config:
#        include /etc/nginx/conf.d/redirects.conf;
#   2. Add in your server block:
#        include /path/to/redirect_plan_server.conf;
#   3. Test: nginx -t && systemctl reload nginx
# ─────────────────────────────────────────────────────────────────────────────

"""

_VHOST_NOTE = "\n# Mode: vhost — cible dynamique via $host (portable staging/prod)"


def _strip_origin(tgt_url: str, target_domain: str) -> str:
    """Return only the path portion of tgt_url, stripping the target origin."""
    if target_domain:
        from urllib.parse import urlparse as _up
        parsed = _up(target_domain.rstrip("/"))
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if tgt_url.startswith(origin):
            return tgt_url[len(origin):] or "/"
    if not tgt_url.startswith("/"):
        # absolute URL with unknown origin — extract path
        from urllib.parse import urlparse as _up
        return _up(tgt_url).path or "/"
    return tgt_url


def export_nginx(
    db_path: str,
    output_dir: str,
    source_domain: str = "",
    target_domain: str = "",
    vhost: bool = False,
) -> tuple[Path, Path]:
    """
    Returns (map_file_path, server_block_path).

    map_file    → redirect_plan_map.conf    (include in http block)
    server_file → redirect_plan_server.conf (include in server block)

    vhost=True  → map values are path-only; server block uses $host to rebuild
                  the full URL → rules work on staging and prod without changes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _db.get_conn(db_path) as conn:
        rows = _db.get_redirects(conn)

    map_lines: list[str] = []

    for row in rows:
        src_path = _path_from_url(row["source_url"], source_domain)
        tgt_url  = row["target_url"]
        if tgt_url.startswith("/") and target_domain:
            tgt_url = target_domain.rstrip("/") + tgt_url

        src_esc = src_path.replace(" ", "%20")

        if vhost:
            # Store only the path; the server block will prepend https://$host
            tgt_value = _strip_origin(tgt_url, target_domain)
        else:
            tgt_value = tgt_url

        map_lines.append(f'    "{src_esc}" "{tgt_value}";')

    total = len(map_lines)
    header = _HEADER.format(
        ts=datetime.now().isoformat(timespec="seconds"),
        total=total,
        vhost_note=_VHOST_NOTE if vhost else "",
    )

    # ── map block (http context) ──────────────────────────────────────────────
    map_var = "$redirect_path" if vhost else "$redirect_uri"
    map_content = header
    map_content += f"map $request_uri {map_var} {{\n"
    map_content += '    default "";\n'
    map_content += "\n".join(map_lines) + "\n"
    map_content += "}\n"

    map_path = out / "redirect_plan_map.conf"
    map_path.write_text(map_content, encoding="utf-8")

    # ── server block snippet ──────────────────────────────────────────────────
    if vhost:
        server_content = """\
# Add this block inside your server {} block:
# $host is the incoming Host header — works on staging and prod without changes.
if ($redirect_path) {
    return 301 https://$host$redirect_path;
}
"""
    else:
        server_content = """\
# Add this block inside your server {} block:
if ($redirect_uri) {
    return 301 $redirect_uri;
}
"""
    server_path = out / "redirect_plan_server.conf"
    server_path.write_text(server_content, encoding="utf-8")

    return map_path, server_path
