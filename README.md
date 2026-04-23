# redirect-stack

> **URL crawl → SEO intent classification → 4-phase matching → redirect plan export**

A Python CLI that automates the full SEO redirect migration pipeline — from raw URL lists to deployment-ready `.htaccess` / nginx rules, with confidence scoring and intent-aware matching.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Cowork Skill — no-code mode](#cowork-skill--no-code-mode)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Crawl Modes](#crawl-modes)
- [SEO Intent Classification](#seo-intent-classification)
- [Matching Pipeline](#matching-pipeline)
- [Export Formats](#export-formats)
- [Configuration](#configuration)
- [Understanding the Output](#understanding-the-output)
- [Troubleshooting](#troubleshooting)
- [Re-running Partial Steps](#re-running-partial-steps)

---

## Overview

When migrating a website, every old URL must be explicitly redirected (301) to its new equivalent — or to the closest relevant page. Doing this manually for hundreds or thousands of URLs is error-prone and time-consuming.

`redirect-stack` solves this by:

1. **Crawling** source and target sites to extract full page metadata (title, H1, description, body text, structured data)
2. **Classifying** pages by SEO intent using TF-IDF + K-Means clustering
3. **Matching** each source URL to the best target URL via a cascade of 4 algorithms
4. **Exporting** the redirect plan in the format your stack requires

---

## Cowork Skill — no-code mode

redirect-stack ships with a [Claude Cowork](https://claude.ai) skill that runs the full pipeline
on your behalf — no terminal required.

**What it does:** drop your CSV files into the chat → Claude asks a few questions (domains, mode,
formats) → executes the pipeline → delivers ready-to-use output files directly in the conversation.

### Setup (Windows — 3 steps)

1. **Install** — double-click `install.bat` (or `install.bat --browser` for e-commerce sites)
2. **Open Cowork** → click "Select a folder" → choose this `redirect-stack` folder
3. **Install the skill** — double-click `skill/redirectmap.skill`

That's it. Start a new conversation and say *"generate a redirect plan"* — Claude takes it from there.

> **HTTP mode** (standard sites) runs entirely inside Cowork — no terminal needed at all.  
> **Browser mode** (e-commerce, bot-protected sites) requires running the crawl locally, then handing
> the `redirect.db` file back to Claude for the remaining steps.

### Setup (Linux / Mac)

```bash
./install.sh           # HTTP mode
./install.sh --browser # With camoufox browser support
# Then: open Cowork → select folder → double-click skill/redirectmap.skill
```

### Sharing with teammates

Each teammate runs `install.bat` (Windows) or `install.sh` (Linux/Mac), then installs the skill.
The skill dynamically discovers the repo location — no hardcoded paths, works on any machine.

```
redirect-stack/
└── skill/
    ├── SKILL.md            ← skill source (versioned)
    └── redirectmap.skill   ← packaged skill (versioned — install by double-click)
```

To rebuild the `.skill` package after editing `SKILL.md`:
```python
# From the repo root:
python3 -c "
import zipfile, pathlib
skill_dir = pathlib.Path('skill')
with zipfile.ZipFile(skill_dir / 'redirectmap.skill', 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    zf.write(skill_dir / 'SKILL.md', 'SKILL.md')
print('skill/redirectmap.skill updated')
"
```

---

## Architecture

```
redirect-stack/
├── redirectmap/
│   ├── cli.py                  ← Entry point (Click commands)
│   ├── config.py               ← Config loading with defaults
│   ├── db.py                   ← SQLite layer (pages, classifications, redirects)
│   ├── crawler/
│   │   ├── async_crawler.py    ← HTTP mode (httpx, BFS, sitemaps)
│   │   ├── browser_crawler.py  ← Browser mode (camoufox stealth Firefox)
│   │   └── sitemap.py          ← Sitemap discovery & parsing
│   ├── classifier/
│   │   └── intent.py           ← TF-IDF + KMeans + intent adjustment
│   ├── matcher/
│   │   ├── pipeline.py         ← 4-phase orchestration
│   │   ├── cosine.py           ← Phase 2: TF-IDF cosine similarity
│   │   ├── fuzzy.py            ← Phase 3+4: rapidfuzz + hierarchical fallback
│   │   └── normalizer.py       ← URL normalization & hashing
│   └── exporter/
│       ├── csv_export.py       ← CSV + Excel
│       ├── htaccess.py         ← Apache mod_rewrite
│       ├── nginx.py            ← Nginx map{} + server{}
│       └── json_export.py      ← Machine-readable JSON
├── skill/
│   ├── SKILL.md                ← Cowork skill source
│   └── redirectmap.skill       ← packaged skill (gitignored)
├── pyproject.toml
├── config.example.yaml
├── install.sh
└── Dockerfile / docker-compose.yml
```

All crawl data, classifications, and redirect rules are stored in a single **SQLite database** (`redirect.db`), making each step resumable and re-runnable independently.

---

## Installation

**Requirements:** Python 3.10+

### Windows (recommended — no terminal)

```
1. git clone https://github.com/1o68o7/redirect-stack.git
   (or download and unzip the ZIP from GitHub)
2. Double-click install.bat
   (or install.bat --browser for e-commerce / JS-heavy sites)
3. Follow the on-screen instructions
```

`install.bat` auto-detects Python, creates the `.venv`, installs all dependencies,
and prints next steps for both Cowork and terminal use.

### Linux / Mac

```bash
git clone https://github.com/1o68o7/redirect-stack.git
cd redirect-stack
chmod +x install.sh
./install.sh           # HTTP mode
./install.sh --browser # With camoufox browser support
```

### Manual (any OS)

```bash
git clone https://github.com/1o68o7/redirect-stack.git
cd redirect-stack

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .

# With browser support (JS rendering, bot protection bypass)
pip install -e ".[browser]"
python -m camoufox fetch        # Downloads ~100MB stealth Firefox (once)
```

**Always activate the venv before running:**
```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
redirectmap --version
```

---

## Quick Start

```bash
# 1. Activate environment
cd redirect-stack
source .venv/bin/activate

# 2. Prepare your URL files
#    source.csv — URLs from the old site
#    target.csv — URLs from the new site
#    (CSV with a 'url' column, or plain TXT with one URL per line)

# 3. Run the full pipeline
redirectmap run \
  --source-urls source.csv \
  --target-urls target.csv \
  --source-domain https://old-site.com \
  --target-domain https://new-site.com \
  --fallback https://new-site.com \
  --formats csv,htaccess \
  --output ./output

# 4. Check results
redirectmap stats
ls ./output/
```

---

## CLI Reference

### `redirectmap run` — Full pipeline in one command

```
redirectmap run [OPTIONS]

  --source-urls TEXT     CSV/TXT file of source URLs           [required]
  --target-urls TEXT     CSV/TXT file of target URLs           [required]
  --db TEXT              SQLite DB path         [default: redirect.db]
  --output / -o TEXT     Output directory       [default: ./output]
  --fallback TEXT        Fallback URL (no match found)         [default: /]
  --source-domain TEXT   e.g. https://old-site.com
  --target-domain TEXT   e.g. https://new-site.com
  --formats TEXT         Export formats, comma-separated       [default: csv]
                         Values: csv, excel, htaccess, nginx, json
  --browser              Use camoufox browser mode (JS, e-commerce)
  --vhost                Vhost-portable rules: use %{HTTP_HOST} (htaccess) or
                         $host (nginx) instead of the hardcoded target domain.
                         Deploy the same rules on staging and prod unchanged.
  --no-sitemaps          Skip sitemap discovery
  --config TEXT          Path to config.yaml
```

Runs all 4 steps sequentially: crawl source → crawl target → classify → match → export.

---

### `redirectmap crawl` — Crawl URLs into SQLite

```
redirectmap crawl [OPTIONS]

  --urls / -u TEXT       CSV/TXT file of URLs to crawl
  --seed / -s TEXT       Seed URL(s) for BFS discovery (repeatable)
  --site [source|target] Which site role to assign crawled pages  [required]
  --db TEXT              [default: redirect.db]
  --browser              Use browser mode (camoufox)
  --no-sitemaps          Skip sitemap discovery
  --config TEXT
```

**Mode selection:**
- `--urls` → list mode: crawls exactly those URLs, no link following
- `--seed` → discovery mode: BFS from seed + sitemap expansion
- Both can be combined: seed provides starting points, `--urls` provides the explicit list

---

### `redirectmap classify` — Classify pages by SEO intent

```
redirectmap classify [OPTIONS]

  --db TEXT              [default: redirect.db]
  --site TEXT            Restrict to 'source' or 'target' (default: all)
  --config TEXT
```

Runs TF-IDF + K-Means on crawled page content. Results are stored in the DB and used automatically by the match step. Triggered automatically if skipped before matching.

---

### `redirectmap match` — Run 4-phase matching

```
redirectmap match [OPTIONS]

  --db TEXT                    [default: redirect.db]
  --fallback TEXT              Default URL when no match found  [default: /]
  --fuzzy-threshold INT        Minimum rapidfuzz score (0–100)  [default: 80]
  --cosine-threshold FLOAT     Minimum cosine score (0.0–1.0)   [default: 0.30]
  --batch-size INT             URLs per processing batch         [default: 1000]
  --config TEXT
```

---

### `redirectmap export` — Export redirect plan

```
redirectmap export [OPTIONS]

  --db TEXT              [default: redirect.db]
  --output / -o TEXT     [default: ./output]
  --formats / -f TEXT    [default: csv]
  --source-domain TEXT
  --target-domain TEXT
  --vhost                Vhost-portable rules (see --vhost in run command)
  --config TEXT
```

---

### `redirectmap stats` — DB stats

```
redirectmap stats [--db TEXT]
```

Prints: pages crawled (source/target), pages classified, total redirect rules, breakdown by confidence level (high / medium / low).

---

## Crawl Modes

### HTTP Mode (default)

Uses **httpx** with async concurrency. Fast, lightweight, no JavaScript rendering.

**Best for:**
- Static sites, simple CMS (WordPress, Drupal)
- Sites where you already have a complete URL list from Screaming Frog or a sitemap
- Large sites where speed matters (10–50k URLs)

**How it works:**
1. Fetches pages with httpx (async, configurable concurrency)
2. Parses HTML with BeautifulSoup + lxml
3. Extracts: title, meta description, H1, body text (truncated to 20k chars), structured data
4. Respects `robots.txt` (Disallow rules)
5. Discovers additional URLs via sitemap (unless `--no-sitemaps`)
6. BFS link following if `--seed` mode (disabled when `--urls` list provided)

**Resume support:** URLs already in the DB are skipped automatically.

---

### Browser Mode (`--browser`)

Uses **camoufox** — a hardened stealth Firefox based on Playwright. Renders JavaScript, bypasses bot-detection systems (Cloudflare, DataDome, PerimeterX).

**Best for:**
- E-commerce platforms (PrestaShop, Magento, Shopify, WooCommerce)
- Sites with lazy-loaded content or JS-rendered SEO metadata
- Sites that return minimal HTML to headless browsers

**How it works:**
1. Opens stealth Firefox instances (anti-fingerprinting patches applied)
2. Navigates each URL with `wait_until="domcontentloaded"` (25s timeout)
3. Extracts full page content including JS-rendered elements
4. Extracts e-commerce structured data: JSON-LD `Product`, `BreadcrumbList`, `ItemList` schemas (EAN13, price, SKU, brand, breadcrumbs)
5. For pages blocked by bot protection (< 200 chars HTML), falls back automatically to **httpx**
6. Hard timeout cap of 40s per URL prevents infinite hangs
7. Recommended concurrency: 2 (Firefox memory usage)

**Bot protection fallback:** If camoufox receives a challenge page (typically < 200 chars), the URL is queued for httpx retry in Phase 2 of the browser run.

---

### CSV Format for `--urls`

The URL file can be:
- **CSV** with a column named `url`, `URL`, `Url`, `address`, `Address`, or `Adresse` (first column used as fallback)
- **TXT** with one URL per line

Screaming Frog exports work out of the box (`Address` column).

```csv
Address
https://old-site.com/products/item-1
https://old-site.com/products/item-2
https://old-site.com/category/robots
```

---

## SEO Intent Classification

Before matching, every page is classified into one of 5 SEO intent categories using **TF-IDF vectorization + K-Means clustering** on the page's text content.

### Intent taxonomy

| Intent | Description | Examples |
|--------|-------------|---------|
| `informationnelle` | Educational, guides, articles, FAQ | Blog posts, tutorials, how-to pages |
| `navigationnelle` | Category pages, brand landing, menus | `/products/`, `/brand/`, category listings |
| `transactionnelle` | Product detail, checkout, add-to-cart | PDPs, `/checkout/`, basket pages |
| `commerciale` | Comparison, pricing, promo pages | `/pricing/`, comparison guides, offer pages |
| `divers` | Legal, CGV, 404, generic pages | T&Cs, cookie policy, error pages |

### How the corpus is built

For each page, the classifier builds a weighted text:

```
text = title × 3 + h1 × 3 + meta_description + body_text[:5000]
```

Title and H1 are repeated 3× because they are the strongest intent signals.

### TF-IDF parameters (configurable)

```yaml
classify:
  n_clusters: 5        # Number of clusters = number of intent categories
  max_features: 5000   # TF-IDF vocabulary size
  min_df: 2            # Ignore terms appearing in fewer than 2 docs
  max_df: 0.85         # Ignore terms in more than 85% of docs (domain stop-words)
  language: "french"   # "french" or "english" for stop-word list
```

---

## Matching Pipeline

Matching runs in **4 sequential phases**. Each phase only processes URLs not matched by the previous one.

### Phase 1 — Exact Hash Match

**Algorithm:** MD5 hash of the normalized URL path  
**Complexity:** O(1) per URL (hash map lookup)  
**Confidence:** always `high`  
**Score:** 100.0

The URL is normalized before hashing: lowercased, trailing slashes removed, query strings stripped. If the normalized path of a source URL matches a target URL exactly, it's a perfect redirect — no content analysis needed.

**Example:**
```
source: https://old-site.com/products/robot-cooker-5200xl
target: https://new-site.com/products/robot-cooker-5200xl
→ exact match, score 100, confidence high
```

---

### Phase 2 — Cosine Similarity (semantic content matching)

**Algorithm:** TF-IDF on `(title + H1 + description + normalized path)` with unigrams + bigrams, then `linear_kernel` (equivalent to cosine similarity on L2-normalized vectors)  
**Library:** scikit-learn  
**Default threshold:** 0.30 (configurable via `--cosine-threshold`)

For each unmatched source page, the vectorizer transforms it into a sparse TF-IDF vector, then computes dot product similarity against all target page vectors. Returns the best match above threshold.

**Confidence tiers (before intent adjustment):**

| Cosine score | Raw confidence |
|-------------|----------------|
| ≥ 0.70 | `high` |
| ≥ 0.40 | `medium` |
| < 0.40 (but ≥ threshold) | `low` |

**When it's most useful:** Detecting pages that have been renamed, reorganized, or moved to a different URL structure but kept similar content.

**Example:**
```
source: /ancienne-categorie/robot-multifonction-5200xl → title: "Robot 5200 XL"
target: /robots/cook-series/5200-xl                   → title: "Cuiseur 5200 XL"
→ cosine match, score 0.68, confidence medium
```

---

### Phase 3 — Fuzzy URL Path Matching

**Algorithm:** `rapidfuzz.fuzz.token_set_ratio` on normalized URL paths  
**Default threshold:** 80 (configurable via `--fuzzy-threshold`)  
**Complexity:** O(n × m) — optimized via `process.extractOne`

Compares the **path component** of source and target URLs using token set ratio, which handles word reordering and partial matches gracefully.

**Example:**
```
source: /accessoires/disque-ondule-mini-plus
target: /accessories/mini-plus-wavy-disc
→ fuzzy match, score 82, confidence medium
```

**Confidence tiers:**

| Fuzzy score | Raw confidence |
|------------|----------------|
| ≥ 85 | `high` |
| ≥ 70 | `medium` |
| < 70 (but ≥ threshold) | `low` |

---

### Phase 4 — Hierarchical Fallback

When no fuzzy match meets the threshold, the matcher **walks up the URL hierarchy** of the source path, looking for matching parent segments in the target site.

**Walk order for `/fr/produits/robot-cuiseur/cook-expert-premium/`:**

| Level | Path tested | Score | Confidence |
|-------|-------------|-------|------------|
| fuzzy | `/fr/produits/robot-cuiseur/cook-expert-…` | ≥ threshold | high/medium |
| L1 | `/fr/produits/robot-cuiseur` | 40.0 | `medium` |
| L2 | `/fr/produits` | 25.0 | `low` |
| L3 | `/fr` | 15.0 | `low` |
| root | `/` | 5.0 | `low` |
| fallback | `<configured URL>` | 0.0 | `low` |

**Why L2/L3 matters:** In deep e-commerce URL structures (4–5 levels), a migration may restructure categories entirely. Without hierarchical fallback, these URLs would hit the fallback URL directly — but a relevant parent category often exists and is a better destination than the homepage.

---

### Intent Adjustment (post-processing)

After all 4 phases, every redirect's confidence level is **adjusted based on the SEO intent alignment** between source and target pages.

#### Bonus: same intent family → confidence upgrade

```
(transactionnelle → transactionnelle) : low → medium, medium → high
(commerciale      → commerciale)      : low → medium, medium → high
(informationnelle → informationnelle) : low → medium, medium → high
(navigationnelle  → navigationnelle)  : low → medium, medium → high
```

#### Malus: semantic conflict → forced to `low` + `intent_mismatch` flag

```
(transactionnelle → informationnelle)  ← product page to blog post
(transactionnelle → divers)            ← product page to legal page
(commerciale      → informationnelle)  ← pricing page to article
(commerciale      → divers)
(informationnelle → transactionnelle)  ← article to product page
```

These cases are preserved in the export for manual review — not silently dropped.

---

### Matching summary table

| Phase | Algorithm | Best for | Output confidence |
|-------|-----------|----------|------------------|
| 1 — Exact | URL hash | Identical paths, URL preserving migrations | always `high` |
| 2 — Cosine | TF-IDF semantic | Renamed content, restructured trees with preserved content | `high`/`medium`/`low` |
| 3 — Fuzzy | token_set_ratio | Similar path names, minor URL rewrites | `high`/`medium`/`low` |
| 4 — Hierarchical | Path ancestor walk | Deep trees, full restructures | `medium`/`low` |
| Fallback | Configured URL | No match found anywhere | always `low` |

---

## Export Formats

### CSV (`--formats csv`)

Lightweight, always recommended. One row per redirect rule.

```
source_url, target_url, match_type, score, confidence, source_intention, target_intention
```

### Excel (`--formats excel`)

`.xlsx` workbook with two sheets:
- **Redirect Plan** — full rules with all columns
- **Summary** — stats by match type and confidence tier

Useful for manual review by non-technical team members.

### Apache htaccess (`--formats htaccess`)

Generates `mod_rewrite` 301 rules grouped by confidence level:

```apache
RewriteEngine On

# ── High confidence (exact / strong cosine / fuzzy ≥85) ──────────────────
RewriteRule ^old-path/page\.html$ https://new-site.com/new-path/page [R=301,L]
RewriteRule ^category/sub$ https://new-site.com/new-category/sub [R=301,L]

# ── Medium confidence (cosine / fuzzy / hierarchical L1) ─────────────────
RewriteRule ^old/path$ https://new-site.com/closest-match [R=301,L]
```

To use: place inside `<VirtualHost>` or `.htaccess`. Requires `mod_rewrite` enabled (`a2enmod rewrite`).

**`--vhost` mode** — rules work on any hostname (staging, prod, preview) without modification:

```apache
# Without --vhost (domain hardcoded):
RewriteRule ^old-path$ https://new-site.com/new-path [R=301,L]

# With --vhost (domain is dynamic):
RewriteRule ^old-path$ https://%{HTTP_HOST}/new-path [R=301,L]
```

### Nginx (`--formats nginx`)

Generates two files:
- `redirect_plan_map.conf` — `map $request_uri $redirect_uri { ... }` block (include in `http` context)
- `redirect_plan_server.conf` — `if` block to trigger the redirect (include in `server` block)

```nginx
# nginx.conf (http context):
include /path/to/redirect_plan_map.conf;

# your site config (server block):
server {
  include /path/to/redirect_plan_server.conf;
}
```

**`--vhost` mode** — map returns path only, server block uses `$host`:

```nginx
# redirect_plan_server.conf with --vhost:
if ($redirect_path) {
    return 301 https://$host$redirect_path;
}
```

### JSON (`--formats json`)

Machine-readable array of redirect objects. Useful for integration with CDNs (Cloudflare, Fastly), custom middleware, or CMS plugins.

```json
[
  {
    "source_url": "https://old-site.com/page",
    "target_url": "https://new-site.com/page",
    "match_type": "exact",
    "score": 100.0,
    "confidence": "high"
  }
]
```

---

## Configuration

Copy `config.example.yaml` to `config.yaml` and adjust:

```yaml
crawl:
  concurrency: 10       # Simultaneous requests (browser mode: 2 recommended, max 5)
  delay: 1.0            # Polite delay between requests (seconds)
  timeout: 60           # Per-request timeout — critical for browser mode
  max_depth: 5          # BFS max depth from seed URL
  max_pages: 50000      # Max pages per site
  user_agent: "redirectmap/1.1"
  respect_robots: true
  # proxies:            # Optional proxy list for browser mode
  #   - "http://proxy1:8080"

classify:
  n_clusters: 5         # = number of SEO intent categories
  max_features: 5000    # TF-IDF vocabulary size
  min_df: 2             # Min document frequency for a term
  max_df: 0.85          # Max document frequency (removes domain stop-words)
  language: "french"    # "french" or "english"

match:
  fuzzy_threshold: 80   # Minimum fuzzy score to accept a path match (0–100)
  cosine_threshold: 0.30 # Minimum cosine score (0.0–1.0)
  fallback_url: "/"     # Used when no match found at any phase
  batch_size: 1000      # URLs per processing batch

export:
  output_dir: "./output"
  formats:
    - csv
    - htaccess
  source_domain: "https://old-site.com"
  target_domain: "https://new-site.com"
```

Pass with `--config config.yaml` on any command.

---

## Understanding the Output

### CSV columns

| Column | Type | Description |
|--------|------|-------------|
| `source_url` | string | Old URL to redirect FROM |
| `target_url` | string | New URL to redirect TO |
| `match_type` | enum | How the match was found (see below) |
| `score` | float | Match score (0–100) |
| `confidence` | enum | `high` / `medium` / `low` |
| `source_intention` | enum | SEO intent of the source page |
| `target_intention` | enum | SEO intent of the target page |

### `match_type` values

| Value | Phase | Meaning |
|-------|-------|---------|
| `exact` | 1 | Identical normalized paths |
| `cosine` | 2 | Best semantic content match |
| `fuzzy` | 3 | Best fuzzy path match |
| `hierarchical_L1` | 4 | Matched to direct parent category |
| `hierarchical_L2` | 4 | Matched to grandparent category |
| `hierarchical_L3` | 4 | Matched to great-grandparent category |
| `hierarchical_root` | 4 | Matched to site root `/` |
| `fallback` | 4 | No match found — using configured fallback URL |

### Deployment recommendations

- **`high` confidence** → safe to deploy directly
- **`medium` confidence** → spot-check recommended before deployment
- **`low` confidence** → manual review required, especially hierarchical and fallback rows
- **`intent_mismatch`** → review mandatory: semantic conflict between source and target page types

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `command not found: redirectmap` | Venv not activated | `source .venv/bin/activate` |
| All URLs timeout at 20s | Config default overrides code | Set `timeout: 60` in `config.yaml` |
| `0 target pages stored` | DB UNIQUE constraint on URL | `rm redirect.db` and re-run |
| Site returns 39-char HTML | Bot protection detected browser | Normal — tool falls back to httpx automatically |
| BFS crawls entire site | `--seed` used without `--urls` | Use `--urls yourfile.csv` for exact list mode |
| Empty `source_intention` in CSV | Empty body_text from browser crawl | Cosmetic — doesn't affect matching |
| `camoufox` import error | Browser extras not installed | `pip install 'camoufox[geoip]' && python -m camoufox fetch` |
| `TargetClosedError` in logs | Orphaned browser tasks after close | Cosmetic — no impact on results |
| `Aucune page cible — matching annulé` | Target crawl stored 0 pages | Check `--site target` was used for target crawl; `rm redirect.db` and retry |

---

## Re-running Partial Steps

The SQLite DB makes each step independent. You can re-run only what you need:

```bash
# Re-run only the match phase (different thresholds, same crawl data)
sqlite3 redirect.db "DELETE FROM redirects;"
redirectmap match --db redirect.db \
  --fallback https://new-site.com \
  --fuzzy-threshold 75 \
  --cosine-threshold 0.25
redirectmap export --db redirect.db --formats csv,htaccess --output ./output

# Re-run only export (different format, with vhost)
redirectmap export --db redirect.db --formats excel,nginx --vhost \
  --source-domain https://old-site.com --target-domain https://new-site.com \
  --output ./output

# Re-classify (changed n_clusters or language)
sqlite3 redirect.db "DELETE FROM classifications;"
redirectmap classify --db redirect.db
redirectmap match --db redirect.db --fallback https://new-site.com
redirectmap export --db redirect.db --formats csv,htaccess --output ./output

# Full reset
rm redirect.db
```

---

## Docker

```bash
docker-compose up
```

Or build manually:

```bash
docker build -t redirect-stack .
docker run --rm \
  -v $(pwd)/data:/app/data \
  redirect-stack \
  redirectmap run \
    --source-urls /app/data/source.csv \
    --target-urls /app/data/target.csv \
    --output /app/data/output
```

---

## License

Private — all rights reserved.
