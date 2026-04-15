"""
URL-path fuzzy matcher — rapidfuzz token_set_ratio + fallback hiérarchique L1/L2/L3+.

Stratégie de fallback hiérarchique (phase 4) :
══════════════════════════════════════════════

Pour une URL source comme :
  /fr/produits/robot-cuiseur/cook-expert-premium/

Le matcher descend par paliers si aucun match direct ou fuzzy n'est trouvé :

  Niveau   Chemin testé                               Score   Confiance
  ──────────────────────────────────────────────────────────────────────
  fuzzy    /fr/produits/robot-cuiseur/cook-expert-…   ≥80     high/medium
  L1       /fr/produits/robot-cuiseur                  40      medium
  L2       /fr/produits                                25      low
  L3       /fr                                         15      low
  root     /                                            5      low
  fallback <URL configurée>                             0      low
  ──────────────────────────────────────────────────────────────────────

Pourquoi L2/L3 ?
  Sur les sites e-commerce avec des arborescences profondes (4–5 niveaux),
  une migration peut restructurer complètement les catégories.
  Ex: /marque/categorie/sous-cat/produit → /produits/sous-cat/produit
  Sans L2/L3, ces URLs tombent directement en fallback alors qu'une catégorie
  parente pertinente existe côté cible.

Scores hiérarchiques pondérés :
  - Utilisés dans l'export pour trier les règles à réviser manuellement
  - Les exports Excel/CSV signalent les règles hiérarchiques avec
    une colonne dédiée (match_type = 'hierarchical_L1', 'L2', etc.)
"""
from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz, process

from redirectmap.matcher.normalizer import (
    normalize_path,
    path_segments,
)

logger = logging.getLogger(__name__)

# Scores pseudo-numériques pour le fallback hiérarchique
_HIERARCHICAL_SCORES = {
    "hierarchical_L1": 40.0,
    "hierarchical_L2": 25.0,
    "hierarchical_L3": 15.0,
    "hierarchical_root": 5.0,
    "fallback": 0.0,
}


def _confidence(score: float, match_type: str) -> str:
    """Calcule le tier de confiance brut (avant ajustement d'intention)."""
    if match_type == "exact":
        return "high"
    if match_type == "cosine" and score >= 0.70:
        return "high"
    if match_type == "cosine" and score >= 0.40:
        return "medium"
    if match_type == "cosine":
        return "low"
    if match_type == "fuzzy" and score >= 85:
        return "high"
    if match_type == "fuzzy" and score >= 70:
        return "medium"
    if match_type == "fuzzy":
        return "low"
    if match_type == "hierarchical_L1":
        return "medium"
    if match_type in ("hierarchical_L2", "hierarchical_L3", "hierarchical_root"):
        return "low"
    return "low"


def build_fuzzy_index(target_pages: list[Any]) -> dict[str, str]:
    """
    Construit {normalized_path: original_url} pour toutes les pages cibles.
    Utilisé à la fois pour la recherche exacte de chemin et le matching fuzzy.
    """
    return {normalize_path(p["url"]): p["url"] for p in target_pages}


def _walk_hierarchy(source_url: str, target_path_dict: dict[str, str]) -> tuple[str | None, float, str]:
    """
    Remonte l'arborescence du chemin source niveau par niveau (jusqu'à L3 + root).

    Retourne (target_url, score, match_type) ou (None, 0, 'none') si rien trouvé.
    match_type : 'hierarchical_L1' | 'hierarchical_L2' | 'hierarchical_L3' | 'hierarchical_root'
    """
    segs = path_segments(source_url)

    # On génère les niveaux de fallback : L1 = parent direct, L2, L3, root
    # ex: segs = ['fr', 'produits', 'robot', 'cook-expert']
    #   → L1: /fr/produits/robot
    #   → L2: /fr/produits
    #   → L3: /fr
    #   → root: /

    level_names = ["hierarchical_L1", "hierarchical_L2", "hierarchical_L3"]

    for level_idx in range(min(3, len(segs) - 1)):
        # Retire (level_idx + 1) segments depuis la fin
        trimmed = segs[:-(level_idx + 1)]
        candidate_path = ("/" + "/".join(trimmed)) if trimmed else "/"
        if candidate_path in target_path_dict:
            mt = level_names[level_idx]
            return target_path_dict[candidate_path], _HIERARCHICAL_SCORES[mt], mt

    # Essai root "/"
    if "/" in target_path_dict:
        return target_path_dict["/"], _HIERARCHICAL_SCORES["hierarchical_root"], "hierarchical_root"

    return None, 0.0, "none"


def fuzzy_match(
    source_url: str,
    target_path_dict: dict[str, str],
    threshold: int = 80,
) -> tuple[str | None, float, str]:
    """
    Phase 3+4 : fuzzy path matching puis remontée hiérarchique L1→L2→L3→root.

    Retourne (matched_url | None, score, match_type).
    """
    src_path = normalize_path(source_url)

    # ── Phase 3 : Fuzzy ──────────────────────────────────────────────────────
    result = process.extractOne(
        src_path,
        target_path_dict.keys(),
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold,
    )
    if result:
        matched_path, score, _ = result
        return target_path_dict[matched_path], float(score), "fuzzy"

    # ── Phase 4 : Hiérarchique L1 / L2 / L3 / root ───────────────────────────
    return _walk_hierarchy(source_url, target_path_dict)


def batch_fuzzy_match(
    source_pages: list[Any],
    target_path_dict: dict[str, str],
    threshold: int = 80,
    fallback_url: str = "/",
) -> list[dict]:
    """
    Applique fuzzy + hiérarchique + fallback sur un batch de pages source.
    Retourne une liste de dicts de redirection (sans intentions, remplies plus tard).
    """
    results = []
    for page in source_pages:
        src_url = page["url"]
        matched_url, score, match_type = fuzzy_match(src_url, target_path_dict, threshold)

        if matched_url is None:
            matched_url = fallback_url
            match_type  = "fallback"
            score       = 0.0

        results.append({
            "source_url":        src_url,
            "target_url":        matched_url,
            "match_type":        match_type,
            "score":             round(score, 2),
            "confidence":        _confidence(score, match_type),
            "source_intention":  "",
            "target_intention":  "",
        })

    return results
