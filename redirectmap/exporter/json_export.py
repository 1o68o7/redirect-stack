"""
JSON structured export — machine-readable redirect plan.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from redirectmap import db as _db


def export_json(db_path: str, output_dir: str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _db.get_conn(db_path) as conn:
        rows = _db.get_redirects(conn)
        stats = _db.get_redirect_stats(conn)

    redirects = [
        {
            "source":     row["source_url"],
            "target":     row["target_url"],
            "match_type": row["match_type"],
            "score":      row["score"],
            "confidence": row["confidence"],
            "source_intent": row["source_intention"],
            "target_intent": row["target_intention"],
        }
        for row in rows
    ]

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(redirects),
        "summary": stats,
        "redirects": redirects,
    }

    path = out / "redirect_plan.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
