"""
CSV and Excel export.
Outputs the redirect plan as a spreadsheet with one row per redirect:
  source_url | target_url | match_type | score | confidence |
  source_intention | target_intention
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from redirectmap import db as _db


_COLUMNS = [
    "source_url", "target_url", "match_type", "score",
    "confidence", "source_intention", "target_intention",
]

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_TYPE_ORDER = {"exact": 0, "cosine": 1, "fuzzy": 2, "hierarchical": 3, "fallback": 4}


def _build_df(db_path: str) -> pd.DataFrame:
    with _db.get_conn(db_path) as conn:
        rows = _db.get_redirects(conn)
    data = [dict(r) for r in rows]
    df = pd.DataFrame(data, columns=_COLUMNS + ["id", "created_at"])
    df = df[_COLUMNS].copy()
    df["match_order"] = df["match_type"].map(_TYPE_ORDER).fillna(99)
    df["conf_order"]  = df["confidence"].map(_CONFIDENCE_ORDER).fillna(99)
    df = df.sort_values(["match_order", "conf_order", "score"], ascending=[True, True, False])
    df = df.drop(columns=["match_order", "conf_order"])
    return df


def export_csv(db_path: str, output_dir: str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = _build_df(db_path)
    path = out / "redirect_plan.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig for Excel compat
    return path


def export_excel(db_path: str, output_dir: str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = _build_df(db_path)
    path = out / "redirect_plan.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Redirect Plan", index=False)

        # Auto-fit column widths
        ws = writer.sheets["Redirect Plan"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 80)

        # Summary sheet
        with _db.get_conn(db_path) as conn:
            stats = _db.get_redirect_stats(conn)
        stats_df = pd.DataFrame(stats)
        if not stats_df.empty:
            stats_df.to_excel(writer, sheet_name="Summary", index=False)

    return path
