"""
Configuration management — loads config.yaml with sane defaults.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_DEFAULTS: dict[str, Any] = {
    "crawl": {
        "concurrency": 10,
        "delay": 1.0,
        "timeout": 60,          # 60s — suffisant pour sites lents / mode navigateur
        "max_depth": 5,
        "max_pages": 50000,
        "user_agent": "redirectmap/1.0",
        "respect_robots": True,
        "follow_redirects": True,
        "allowed_content_types": ["text/html"],
    },
    "classify": {
        "n_clusters": 5,
        "max_features": 5000,
        "min_df": 2,
        "max_df": 0.85,
        "language": "french",
    },
    "match": {
        "fuzzy_threshold": 80,
        "cosine_threshold": 0.30,
        "fallback_url": "/",
        "batch_size": 1000,
    },
    "export": {
        "output_dir": "./output",
        "formats": ["csv", "excel", "htaccess", "nginx", "json"],
        "source_domain": "",
        "target_domain": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> dict:
    """Load configuration from YAML file, merged with defaults."""
    cfg = _DEFAULTS.copy()
    if path is None:
        # Look for config.yaml in CWD or parent dirs
        for candidate in [Path("config.yaml"), Path("config.yml")]:
            if candidate.exists():
                path = candidate
                break
    if path and Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user_cfg)
    return cfg
