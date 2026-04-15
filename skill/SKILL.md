---
name: redirectmap
description: >
  Use this skill whenever the user wants to generate a redirect plan, map old URLs to new URLs,
  migrate a website, handle a site redesign, or produce 301 redirect rules for Apache (.htaccess)
  or Nginx. Triggers: "redirect plan", "URL mapping", "site migration", "redirections 301",
  "redirection htaccess", "redirection nginx", "ancien site vers nouveau site", "plan de redirections",
  "mapper des URLs", "crawl source et cible", "Screaming Frog export". Also trigger when the user
  uploads or mentions a CSV of URLs in a migration context. This skill EXECUTES the full pipeline
  on behalf of the user — it does not just give instructions.
---

# Redirectmap — Active Pipeline Skill

This skill runs the `redirectmap` CLI directly via bash on behalf of the user.
The user provides URL files; Claude executes the full pipeline (crawl → classify → match → export)
and delivers ready-to-use output files.

---

## Phase 0 — Bootstrap (run FIRST, every session)

The sandbox environment is ephemeral — redirectmap must be located and installed each session.
Run this block before any other command:

```bash
# 1. Locate the Cowork sandbox mount root (portable across all users)
SANDBOX_ROOT=$(find /sessions/*/mnt -maxdepth 0 -type d 2>/dev/null | head -1)
DOCS="$SANDBOX_ROOT/Documents"
UPLOADS="$SANDBOX_ROOT/uploads"

# 2. Locate the redirectmap repo (cloned anywhere under Documents)
REPO=$(find "$DOCS" -maxdepth 3 -name "pyproject.toml" \
       -exec grep -l "name = \"redirectmap\"" {} \; 2>/dev/null \
       | head -1 | xargs dirname)

echo "SANDBOX_ROOT=$SANDBOX_ROOT"
echo "REPO=$REPO"

# 3. Install redirectmap in sandbox if not already available
if ! command -v redirectmap &>/dev/null && [ -n "$REPO" ]; then
    echo "Installing redirectmap in sandbox..."
    cp -r "$REPO" /tmp/rdm-sandbox
    sed -i 's/requires-python = ">=3.11"/requires-python = ">=3.10"/' \
        /tmp/rdm-sandbox/pyproject.toml
    pip install -e /tmp/rdm-sandbox/ --break-system-packages -q
    export PATH="$PATH:$HOME/.local/bin"
fi

# 4. Verify
redirectmap --version
echo "READY: REPO=$REPO | DOCS=$DOCS | UPLOADS=$UPLOADS"
```

If `REPO` is empty, the user hasn't cloned the repo yet. Tell them:
> "Merci de cloner le repo d'abord : `git clone https://github.com/1o68o7/redirect-stack.git`
> puis de sélectionner ce dossier dans Cowork."

---

## Phase 1 — Gather information (use AskUserQuestion)

Once bootstrap is confirmed, ask:

1. **Fichiers CSV** — source (ancien site) et cible (nouveau site) déjà uploadés ?
   → Check `$UPLOADS/` for recently uploaded files before asking
2. **Domaine source** — ex: `https://ancien-site.com`
3. **Domaine cible** — ex: `https://nouveau-site.com`
4. **Type de site** — Simple (HTTP) ou E-commerce/JS/bot-protection (Navigateur) ?
5. **Formats d'export** — Proposer `csv,htaccess` par défaut
6. **URL de repli** — Si aucun match trouvé (défaut : domaine cible)

---

## Phase 2 — Crawl mode decision

**HTTP mode** (default) — use when:
- Complete URL lists already available (Screaming Frog, sitemap export)
- Simple CMS: WordPress, Drupal, static site
- Large sites where speed matters (10k–50k URLs)

**Browser mode (`--browser`)** — use when:
- E-commerce: PrestaShop, Magento, Shopify, WooCommerce
- JS-rendered content or lazy loading
- Bot protection: Cloudflare, DataDome, PerimeterX

> ⚠️ Browser mode requires `camoufox` installed on the user's machine (not available in sandbox).
> If browser mode is needed: provide the Windows terminal command instead of running it yourself,
> and offer to run the classify + match + export steps once the user has crawled locally.

---

## Phase 3 — Execute the pipeline

### Set up environment variables (reuse bootstrap values)
```bash
export PATH="$PATH:$HOME/.local/bin"
SANDBOX_ROOT=$(find /sessions/*/mnt -maxdepth 0 -type d 2>/dev/null | head -1)
DOCS="$SANDBOX_ROOT/Documents"
UPLOADS="$SANDBOX_ROOT/uploads"
REPO=$(find "$DOCS" -maxdepth 3 -name "pyproject.toml" \
       -exec grep -l "name = \"redirectmap\"" {} \; 2>/dev/null \
       | head -1 | xargs dirname)
WORKDIR="$REPO"
OUTPUT="$WORKDIR/output"
```

### Check uploaded files
```bash
ls -lh "$UPLOADS/"
```

### Wipe DB (always start fresh)
```bash
rm -f "$WORKDIR/redirect.db"
```

### Run — HTTP mode
```bash
redirectmap run \
  --source-urls "$UPLOADS/<source_file>" \
  --target-urls "$UPLOADS/<target_file>" \
  --source-domain "<source_domain>" \
  --target-domain "<target_domain>" \
  --fallback "<fallback_url>" \
  --formats "<formats>" \
  --output "$OUTPUT"
```

### Run — Browser mode (only if camoufox available on user machine)
Provide this command for the user to run in their Windows terminal:
```powershell
cd C:\path\to\redirect-stack
.venv\Scripts\activate
redirectmap run `
  --source-urls source.csv `
  --target-urls target.csv `
  --browser `
  --source-domain https://ancien-site.com `
  --target-domain https://nouveau-site.com `
  --fallback https://nouveau-site.com `
  --formats csv,htaccess `
  --output ./output
```

### Stats after run
```bash
redirectmap stats --db "$WORKDIR/redirect.db"
```

---

## Phase 4 — Deliver output files

Copy results to Documents root for easy access:
```bash
cp "$OUTPUT"/* "$DOCS/"
```

Then present with `computer://` links. Build the Windows path dynamically:
- Find the Windows username from the sandbox path: `echo $SANDBOX_ROOT | grep -oP '(?<=/mnt/)[^/]+'`
- Or simply tell the user the files are in their Documents folder and list them

Present:
- `redirect_plan.csv` — plan complet
- `redirect_plan.htaccess` — règles Apache (si demandé)
- `redirect_plan_nginx_map.conf` — règles Nginx (si demandé)
- `redirect_plan.xlsx` — classeur Excel (si demandé)

---

## Phase 5 — Summary

Always show after a successful run:

```
✅ Pipeline terminé — X règles de redirection générées

Répartition par confiance :
  🟢 high   : XX  → déploiement direct
  🟡 medium : XX  → vérification recommandée
  🔴 low    : XX  → revue manuelle requise

Répartition par type de match :
  exact          : XX  (chemins identiques)
  cosine         : XX  (contenu similaire)
  fuzzy          : XX  (chemin approchant)
  hierarchical   : XX  (catégorie parente)
  fallback       : XX  ⚠️ aucun match trouvé
```

Flag any rows where `source_intention ≠ target_intention` as potential SEO risk.

---

## Partial re-run (adjust thresholds without re-crawling)

```bash
export PATH="$PATH:$HOME/.local/bin"
SANDBOX_ROOT=$(find /sessions/*/mnt -maxdepth 0 -type d 2>/dev/null | head -1)
REPO=$(find "$SANDBOX_ROOT/Documents" -maxdepth 3 -name "pyproject.toml" \
       -exec grep -l "name = \"redirectmap\"" {} \; 2>/dev/null \
       | head -1 | xargs dirname)

sqlite3 "$REPO/redirect.db" "DELETE FROM redirects;"

redirectmap match \
  --db "$REPO/redirect.db" \
  --fallback "<fallback_url>" \
  --fuzzy-threshold <0-100> \
  --cosine-threshold <0.0-1.0>

redirectmap export \
  --db "$REPO/redirect.db" \
  --formats "<formats>" \
  --output "$REPO/output" \
  --source-domain "<source_domain>" \
  --target-domain "<target_domain>"
```

---

## Colleague onboarding

For a colleague to use this skill, they need to:

1. Clone the repo:
   ```bash
   git clone https://github.com/1o68o7/redirect-stack.git
   ```
2. Run the install script:
   ```bash
   cd redirect-stack
   ./install.sh          # HTTP mode
   ./install.sh --browser  # with camoufox
   ```
3. Select the `redirect-stack` folder in Cowork
4. Install the `.skill` file from `skill/redirectmap.skill`

The skill auto-installs in the Cowork sandbox on first use — no manual configuration needed.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `REPO` empty after bootstrap | Repo not in Documents — ask user to select the folder in Cowork |
| `command not found: redirectmap` | Re-run bootstrap block; add `export PATH="$PATH:$HOME/.local/bin"` |
| `0 pages stored` | `rm redirect.db` and retry |
| `Aucune page cible` | Wrong `--site` flag; wipe DB and retry |
| Browser mode needed | Provide Windows terminal commands; offer to run classify+match+export after crawl |
| `camoufox` not in sandbox | Expected — only HTTP mode in sandbox |
