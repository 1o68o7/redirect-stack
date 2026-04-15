"""
SEO Intent Classifier — TF-IDF + K-Means sur le contenu des pages crawlées.

═══════════════════════════════════════════════════════════════════════════════
RÔLE DANS LE PIPELINE DE MATCHING (non optionnel)
═══════════════════════════════════════════════════════════════════════════════

La classification n'est pas un simple label d'affichage : elle intervient
directement dans la qualité et la confiance des redirections.

1. TIEBREAKER entre plusieurs candidats de score proche
   → Si deux URLs cibles ont un score cosine similaire (ex: 0.52 vs 0.55),
     on préfère celle qui partage la même intention SEO que la source.
     Ex: une page "transactionnelle" source → page "transactionnelle" cible.

2. BONUS DE CONFIANCE pour alignement d'intention
   → Match cosine avec intentions identiques : low → medium, medium → high
   → Match fuzzy avec intentions identiques  : low → medium

3. MALUS DE CONFIANCE pour incohérence sémantique
   → Rediriger une page "transactionnelle" (fiche produit) vers une page
     "informationnelle" (article de blog) est un signal d'alerte :
     le match est forcé à "low" même si le score path est élevé.
   → Visible dans l'export : colonne intent_mismatch = True

4. VISIBILITÉ DANS L'EXPORT
   → Chaque ligne d'export contient source_intention et target_intention,
     permettant à l'équipe de repérer et corriger manuellement les redirections
     à risque (ex: transactionnelle → divers).

Intentions SEO mappées (taxonomie standard) :
  0 → informationnelle  (guides, articles, FAQ, tutoriels)
  1 → navigationnelle   (pages catégorie, menus, landing brand)
  2 → transactionnelle  (fiches produit, checkout, add-to-cart)
  3 → commerciale       (comparatifs, pages prix, pages offres)
  4 → divers            (mentions légales, CGV, 404, etc.)
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

INTENT_LABELS = {
    0: "informationnelle",
    1: "navigationnelle",
    2: "transactionnelle",
    3: "commerciale",
    4: "divers",
}

# Incompatibilités d'intention qui déclenchent un malus de confiance.
# (source_intent, target_intent) → le match sera déclassé en "low"
INTENT_CONFLICTS: set[tuple[str, str]] = {
    ("transactionnelle", "informationnelle"),
    ("transactionnelle", "divers"),
    ("commerciale",      "informationnelle"),
    ("commerciale",      "divers"),
    ("informationnelle", "transactionnelle"),
}

# Paires qui déclenchent un bonus de confiance (même famille)
INTENT_BONUS: set[tuple[str, str]] = {
    ("transactionnelle", "transactionnelle"),
    ("commerciale",      "commerciale"),
    ("informationnelle", "informationnelle"),
    ("navigationnelle",  "navigationnelle"),
}

# Stop-words français minimaux (sklearn ne les embarque pas nativement)
_FRENCH_STOP_WORDS = [
    "le","la","les","de","du","des","un","une","et","en","au","aux",
    "à","a","que","qui","quoi","dont","où","ce","cet","cette","ces",
    "mon","ton","son","ma","ta","sa","mes","tes","ses","notre","votre",
    "leur","leurs","je","tu","il","elle","nous","vous","ils","elles",
    "me","te","se","lui","y","ne","pas","plus","par","sur","sous",
    "dans","avec","pour","est","être","avoir","faire","si","même",
    "mais","ou","car","donc","or","ni","comme","tout","très","bien",
    "aussi","puis","après","avant","déjà","encore","toujours","jamais",
    "ici","là","autre","autres","chaque","tous","toutes",
]


def apply_intent_adjustment(confidence: str, src_intent: str, tgt_intent: str) -> tuple[str, bool]:
    """
    Adjust confidence level based on intent alignment.

    Returns (adjusted_confidence, intent_mismatch_flag).
    """
    if not src_intent or not tgt_intent:
        return confidence, False

    pair = (src_intent, tgt_intent)

    # Malus : intentions incompatibles
    if pair in INTENT_CONFLICTS:
        return "low", True

    # Bonus : même famille d'intention
    if pair in INTENT_BONUS:
        if confidence == "low":
            return "medium", False
        if confidence == "medium":
            return "high", False

    return confidence, False


def _build_corpus(pages: list[Any]) -> list[str]:
    """
    Combine title + h1 + description + body_text.
    Title et H1 pondérés ×3 car porteurs du signal d'intention principal.
    """
    texts = []
    for p in pages:
        title = (p["title"] or "").strip()
        h1    = (p["h1"]    or "").strip()
        desc  = (p["description"] or "").strip()
        body  = (p["body_text"]   or "")[:5000].strip()
        text  = " ".join([title] * 3 + [h1] * 3 + [desc, body])
        texts.append(text)
    return texts


def classify_pages(db_path: str, cfg: dict, site: str | None = None) -> dict:
    """
    Classify all crawled pages and write intent labels to the DB.
    Runs automatically before the matching step.

    Returns a summary dict {intention: count}.
    """
    import sqlite3
    from redirectmap import db as _db

    n_clusters:   int   = cfg.get("n_clusters", 5)
    max_features: int   = cfg.get("max_features", 5000)
    min_df:       int   = cfg.get("min_df", 2)
    max_df:       float = cfg.get("max_df", 0.85)
    language:     str   = cfg.get("language", "french")

    stop_words: list[str] | str
    if language == "french":
        stop_words = _FRENCH_STOP_WORDS
    else:
        stop_words = "english"

    with sqlite3.connect(str(db_path)) as raw_conn:
        raw_conn.row_factory = sqlite3.Row
        query = "SELECT * FROM pages WHERE body_text != '' AND body_text IS NOT NULL"
        params: tuple = ()
        if site:
            query += " AND site = ?"
            params = (site,)
        pages = raw_conn.execute(query, params).fetchall()

    if not pages:
        logger.warning("No pages with body_text — classification skipped.")
        return {}

    logger.info("Classifying %d pages into %d intent clusters...", len(pages), n_clusters)

    corpus = _build_corpus(pages)

    vectorizer = TfidfVectorizer(
        max_df=max_df,
        min_df=min_df,
        max_features=max_features,
        stop_words=stop_words,
    )
    X = vectorizer.fit_transform(corpus)

    k = min(n_clusters, len(corpus))
    model = KMeans(n_clusters=k, random_state=42, n_init="auto")
    labels = model.fit_predict(X)

    with _db.get_conn(db_path) as conn:
        for page, label in zip(pages, labels):
            cluster_label = int(label)
            intention = INTENT_LABELS.get(cluster_label % len(INTENT_LABELS), "divers")
            _db.upsert_classification(conn, page["id"], cluster_label, intention)

    unique, counts = np.unique(labels, return_counts=True)
    summary = {
        INTENT_LABELS.get(int(lbl) % len(INTENT_LABELS), "divers"): int(cnt)
        for lbl, cnt in zip(unique, counts)
    }
    logger.info("Classification done: %s", summary)
    return summary


def get_page_intentions(db_path: str) -> dict[int, str]:
    """Returns {page_id: intention} for all classified pages."""
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT page_id, intention FROM classifications").fetchall()
    return {r[0]: r[1] for r in rows}
