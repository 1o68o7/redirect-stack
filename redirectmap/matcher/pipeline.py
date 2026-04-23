"""
Matching pipeline — orchestration des 4 phases + ajustement d'intention.

  Phase 1 — Exact hash match         (O(1), identité parfaite de chemin)
  Phase 2 — Cosine similarity         (similarité sémantique TF-IDF sur titre+h1+desc+path)
  Phase 3 — Fuzzy URL path match      (rapidfuzz token_set_ratio sur le chemin)
  Phase 4 — Fallback hiérarchique     (L1 → L2 → L3 → root → URL par défaut)

Post-traitement d'intention (après toutes les phases) :
  - Chaque redirect reçoit source_intention et target_intention
  - apply_intent_adjustment() ajuste la confiance selon l'alignement d'intention
  - Un flag intent_mismatch est ajouté pour alerter sur les redirections risquées

La classification (classify_pages) est automatiquement lancée avant le matching
si les pages ne sont pas encore classifiées. Elle n'est pas optionnelle car
l'ajustement d'intention améliore significativement la qualité des règles.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from tqdm import tqdm

from redirectmap import db as _db
from redirectmap.classifier.intent import (
    apply_intent_adjustment,
    classify_pages,
    get_page_intentions,
)
from redirectmap.matcher.cosine import build_cosine_index, cosine_match_batch
from redirectmap.matcher.fuzzy import (
    _confidence,
    batch_fuzzy_match,
    build_fuzzy_index,
)
from redirectmap.matcher.normalizer import url_hash

logger = logging.getLogger(__name__)


def _ensure_classified(db_path: str | Path, classify_cfg: dict) -> dict[int, str]:
    """
    Vérifie si les pages sont déjà classifiées.
    Si non, lance classify_pages automatiquement.
    Retourne {page_id: intention}.
    """
    with sqlite3.connect(str(db_path)) as conn:
        n_classified = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        n_pages      = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    if n_classified < n_pages * 0.5:
        logger.info(
            "Classification manquante (%d/%d pages) — lancement automatique...",
            n_classified, n_pages,
        )
        classify_pages(db_path=str(db_path), cfg=classify_cfg)

    return get_page_intentions(str(db_path))


def run_matching(db_path: str | Path, cfg: dict, classify_cfg: dict | None = None) -> dict:
    """
    Exécute le pipeline de matching complet et persiste les résultats dans la DB.

    cfg keys :
      - fuzzy_threshold   (int,   default 80)
      - cosine_threshold  (float, default 0.30)
      - fallback_url      (str,   default "/")
      - batch_size        (int,   default 1000)

    classify_cfg : configuration du classifier (passé depuis la config globale).
    Si None, utilise les valeurs par défaut.

    Retourne un dict de compteurs par phase.
    """
    fuzzy_threshold:  int   = cfg.get("fuzzy_threshold", 80)
    cosine_threshold: float = cfg.get("cosine_threshold", 0.30)
    fallback_url:     str   = cfg.get("fallback_url", "/")
    batch_size:       int   = cfg.get("batch_size", 1000)

    if classify_cfg is None:
        classify_cfg = {}

    # ── Chargement des pages ──────────────────────────────────────────────────
    with sqlite3.connect(str(db_path)) as raw:
        raw.row_factory = sqlite3.Row
        source_pages = [dict(r) for r in raw.execute("SELECT * FROM pages WHERE site='source'").fetchall()]
        target_pages = [dict(r) for r in raw.execute("SELECT * FROM pages WHERE site='target'").fetchall()]

    if not source_pages:
        logger.warning(
            "Aucune page source dans la DB (site='source'). "
            "La DB est peut-être corrompue ou le crawl n'a pas abouti. "
            "Conseil : supprimez redirect.db et relancez le pipeline."
        )
        return {}
    if not target_pages:
        logger.warning(
            "Aucune page cible dans la DB (site='target'). "
            "La DB est peut-être corrompue ou le crawl n'a pas abouti. "
            "Conseil : supprimez redirect.db et relancez le pipeline."
        )
        return {}

    logger.info("Matching : %d sources → %d cibles", len(source_pages), len(target_pages))

    # ── Classification (obligatoire, auto-déclenchée si besoin) ──────────────
    intentions = _ensure_classified(db_path, classify_cfg)

    with sqlite3.connect(str(db_path)) as raw:
        raw.row_factory = sqlite3.Row
        src_id_map = {r["url"]: r["id"] for r in raw.execute("SELECT id, url FROM pages WHERE site='source'")}
        tgt_id_map = {r["url"]: r["id"] for r in raw.execute("SELECT id, url FROM pages WHERE site='target'")}

    def get_intent(url: str, id_map: dict) -> str:
        pid = id_map.get(url)
        return intentions.get(pid, "") if pid else ""

    # ── Construction des index ────────────────────────────────────────────────
    hash_index:  dict[str, str] = {p["url_hash"]: p["url"] for p in target_pages}
    fuzzy_index: dict[str, str] = build_fuzzy_index(target_pages)
    vectorizer, target_matrix, target_urls = build_cosine_index(target_pages)

    # ── Compteurs ─────────────────────────────────────────────────────────────
    counters: dict[str, int] = {
        "exact": 0, "cosine": 0, "fuzzy": 0,
        "hierarchical_L1": 0, "hierarchical_L2": 0,
        "hierarchical_L3": 0, "hierarchical_root": 0,
        "fallback": 0, "intent_adjusted": 0,
    }
    all_redirects:           list[dict] = []
    unmatched_after_exact:   list[dict] = []
    unmatched_after_cosine:  list[dict] = []

    # ── Phase 1 : Exact hash ──────────────────────────────────────────────────
    for page in tqdm(source_pages, desc="Phase 1 — Exact"):
        tgt = hash_index.get(page["url_hash"])
        if tgt:
            src_int = get_intent(page["url"], src_id_map)
            tgt_int = get_intent(tgt, tgt_id_map)
            conf, _ = apply_intent_adjustment("high", src_int, tgt_int)
            all_redirects.append({
                "source_url":        page["url"],
                "target_url":        tgt,
                "match_type":        "exact",
                "score":             100.0,
                "confidence":        conf,
                "source_intention":  src_int,
                "target_intention":  tgt_int,
            })
            counters["exact"] += 1
        else:
            unmatched_after_exact.append(page)

    logger.info("Phase 1 — exact : %d matches, %d restants", counters["exact"], len(unmatched_after_exact))

    # ── Phase 2 : Cosine ──────────────────────────────────────────────────────
    for i in tqdm(range(0, len(unmatched_after_exact), batch_size), desc="Phase 2 — Cosine"):
        batch = unmatched_after_exact[i: i + batch_size]
        cosine_results = cosine_match_batch(batch, vectorizer, target_matrix, target_urls, cosine_threshold)
        matched_in_batch = {src for src, _, _ in cosine_results}

        for src_url, tgt_url, score in cosine_results:
            src_int = get_intent(src_url, src_id_map)
            tgt_int = get_intent(tgt_url, tgt_id_map)
            raw_conf = _confidence(score, "cosine")
            adj_conf, mismatch = apply_intent_adjustment(raw_conf, src_int, tgt_int)
            if adj_conf != raw_conf:
                counters["intent_adjusted"] += 1

            all_redirects.append({
                "source_url":        src_url,
                "target_url":        tgt_url,
                "match_type":        "cosine",
                "score":             round(score, 4),
                "confidence":        adj_conf,
                "source_intention":  src_int,
                "target_intention":  tgt_int,
            })
            counters["cosine"] += 1

        for page in batch:
            if page["url"] not in matched_in_batch:
                unmatched_after_cosine.append(page)

    logger.info("Phase 2 — cosine : %d matches, %d restants", counters["cosine"], len(unmatched_after_cosine))

    # ── Phase 3+4 : Fuzzy + hiérarchique L1/L2/L3/root + fallback ────────────
    for i in tqdm(range(0, len(unmatched_after_cosine), batch_size), desc="Phase 3/4 — Fuzzy+Hiérarchique"):
        batch = unmatched_after_cosine[i: i + batch_size]
        fuzzy_results = batch_fuzzy_match(batch, fuzzy_index, fuzzy_threshold, fallback_url)

        for row in fuzzy_results:
            mt      = row["match_type"]
            src_int = get_intent(row["source_url"], src_id_map)
            tgt_int = get_intent(row["target_url"], tgt_id_map)
            raw_conf = row["confidence"]
            adj_conf, mismatch = apply_intent_adjustment(raw_conf, src_int, tgt_int)
            if adj_conf != raw_conf:
                counters["intent_adjusted"] += 1

            row["source_intention"] = src_int
            row["target_intention"] = tgt_int
            row["confidence"]       = adj_conf
            counters[mt] = counters.get(mt, 0) + 1
            all_redirects.append(row)

    logger.info(
        "Phase 3/4 — fuzzy: %d | L1: %d | L2: %d | L3: %d | root: %d | fallback: %d",
        counters["fuzzy"], counters["hierarchical_L1"], counters["hierarchical_L2"],
        counters["hierarchical_L3"], counters["hierarchical_root"], counters["fallback"],
    )
    logger.info("Ajustements d'intention (bonus/malus) : %d", counters["intent_adjusted"])

    # ── Persistance ───────────────────────────────────────────────────────────
    with _db.get_conn(db_path) as conn:
        conn.execute("DELETE FROM redirects")
        n = _db.bulk_insert_redirects(conn, all_redirects)

    logger.info("Matching terminé — %d règles de redirection enregistrées", n)
    return counters
