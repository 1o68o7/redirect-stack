"""
Content-based cosine similarity matcher.

Uses TF-IDF on (title + h1 + description + url path segments) to find
the semantically closest target page for each source page.

Optimised for 10k–100k URLs:
  - Operates on sparse sklearn matrices (memory-efficient)
  - Processes source URLs in batches to avoid OOM
  - Returns only the best match above the threshold
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

logger = logging.getLogger(__name__)


def _page_text(page: Any) -> str:
    """Build a searchable text representation of a page."""
    title = (page["title"] or "").strip()
    h1 = (page["h1"] or "").strip()
    desc = (page["description"] or "").strip()
    path = (page["normalized_url"] or "").replace("/", " ").replace("-", " ").replace("_", " ")
    return " ".join([title, h1, desc, path])


def build_cosine_index(target_pages: list[Any]) -> tuple[TfidfVectorizer, Any, list[str]]:
    """
    Fit TF-IDF vectorizer on target pages and return:
      (vectorizer, target_matrix, target_urls_list)
    """
    target_texts = [_page_text(p) for p in target_pages]
    target_urls = [p["url"] for p in target_pages]

    vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        max_df=0.90,
        min_df=1,
        max_features=10_000,
        sublinear_tf=True,
    )
    target_matrix = vectorizer.fit_transform(target_texts)
    logger.info("Cosine index built: %d target pages, vocab size %d",
                len(target_pages), len(vectorizer.vocabulary_))
    return vectorizer, target_matrix, target_urls


def cosine_match_batch(
    source_pages: list[Any],
    vectorizer: TfidfVectorizer,
    target_matrix: Any,
    target_urls: list[str],
    threshold: float = 0.30,
) -> list[tuple[str, str, float]]:
    """
    For each source page, find best target match by cosine similarity.

    Returns list of (source_url, target_url, score) only for matches
    above threshold. Sources with no match above threshold are skipped
    (will fall through to fuzzy matcher).
    """
    if not source_pages:
        return []

    source_texts = [_page_text(p) for p in source_pages]
    source_urls = [p["url"] for p in source_pages]

    source_matrix = vectorizer.transform(source_texts)
    # linear_kernel is equivalent to cosine_similarity when vectors are L2-normalized
    sim_matrix = linear_kernel(source_matrix, target_matrix)

    results = []
    for i, src_url in enumerate(source_urls):
        best_idx = int(np.argmax(sim_matrix[i]))
        best_score = float(sim_matrix[i][best_idx])
        if best_score >= threshold:
            results.append((src_url, target_urls[best_idx], best_score))

    return results
