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

**Si `REPO` est vide**, le repo n'est pas accessible. Dire à l'utilisateur :
> "Pour utiliser ce skill, clonez d'abord le repo puis sélectionnez ce dossier dans Cowork :
> 1. Dans un terminal : `git clone https://github.com/1o68o7/redirect-stack.git`
> 2. Ou téléchargez le ZIP depuis GitHub et décompressez-le
> 3. Dans Cowork : cliquez 'Sélectionner un dossier' et choisissez le dossier `redirect-stack`
> 4. Relancez votre demande"

---

## Phase 1 — Gather information (use AskUserQuestion)

**Avant de poser des questions, inspecter les uploads :**
```bash
ls -lh "$UPLOADS/" 2>/dev/null || echo "Pas de fichiers uploadés"
```

Poser une seule question groupée avec AskUserQuestion (éviter les allers-retours) :

1. **Fichiers CSV** — source (ancien site) et cible (nouveau site)
   - Si des CSV sont dans `$UPLOADS/`, les proposer directement
   - Sinon : "Uploadez vos fichiers CSV d'URLs (exports Screaming Frog ou sitemap)"
2. **Domaine source** — ex: `https://ancien-site.com`
3. **Domaine cible** — ex: `https://nouveau-site.com` (peut être identique si restructuration interne)
4. **Type de site** — Simple (HTTP) ou E-commerce/JS/bot-protection (Navigateur) ?
5. **Formats d'export** — Proposer `csv,htaccess` par défaut
6. **URL de repli** — Si aucun match trouvé (défaut : domaine cible)
7. **Mode vhost ?** — "Les règles doivent-elles fonctionner sur staging ET prod sans modification ?" → si oui, ajouter `--vhost`

---

## Phase 2 — Crawl mode decision

**HTTP mode** (default) — use when:
- Fichiers CSV déjà disponibles (Screaming Frog, export sitemap)
- CMS simple : WordPress, Drupal, site statique
- Grands sites (10k–50k URLs) où la vitesse compte

**Browser mode (`--browser`)** — use when:
- E-commerce : PrestaShop, Magento, Shopify, WooCommerce
- Contenu rendu JS ou lazy loading
- Protection anti-bot : Cloudflare, DataDome, PerimeterX

> ⚠️ Browser mode = camoufox requis sur la machine de l'utilisateur (pas disponible dans le sandbox Cowork).
> Dans ce cas :
> 1. Donner la commande PowerShell à exécuter localement (voir Phase 3)
> 2. Proposer de reprendre les étapes classify + match + export une fois le crawl terminé

---

## Phase 3 — Execute the pipeline

### Variables d'environnement (à re-déclarer dans chaque appel bash)
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

### Vérifier les fichiers uploadés
```bash
ls -lh "$UPLOADS/"
```

> ⚠️ **Erreur fréquente — "Fichier introuvable"** : les CSV doivent être uploadés dans Cowork
> (glisser-déposer dans la conversation) OU être dans le dossier sélectionné.
> Ne jamais utiliser un chemin Windows comme `--source-urls` — utiliser `$UPLOADS/nom_fichier.csv`.

### Run — HTTP mode (dans le sandbox Cowork)

> ℹ️ `--db` n'est plus nécessaire dans `run` : une DB temporaire est créée automatiquement
> dans `/tmp` pour éviter les erreurs de permissions FUSE sur le filesystem monté.

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

Avec `--vhost` (staging/prod portables) :
```bash
redirectmap run \
  --source-urls "$UPLOADS/<source_file>" \
  --target-urls "$UPLOADS/<target_file>" \
  --source-domain "<source_domain>" \
  --target-domain "<target_domain>" \
  --fallback "<fallback_url>" \
  --formats "<formats>" \
  --vhost \
  --output "$OUTPUT"
```

### Run — Browser mode (commande à donner à l'utilisateur pour son terminal Windows)
```powershell
cd C:\chemin\vers\redirect-stack
.venv\Scripts\activate
redirectmap run `
  --source-urls "C:\chemin\vers\source.csv" `
  --target-urls "C:\chemin\vers\target.csv" `
  --browser `
  --source-domain https://ancien-site.com `
  --target-domain https://nouveau-site.com `
  --fallback https://nouveau-site.com `
  --formats csv,htaccess `
  --output .\output
```

Avec `--vhost` :
```powershell
redirectmap run `
  --source-urls "C:\chemin\vers\source.csv" `
  --target-urls "C:\chemin\vers\target.csv" `
  --browser `
  --source-domain https://ancien-site.com `
  --target-domain https://nouveau-site.com `
  --fallback https://nouveau-site.com `
  --formats csv,htaccess `
  --vhost `
  --output .\output
```

> Une fois le crawl browser terminé, l'utilisateur peut uploader la `redirect.db` dans Cowork
> et Claude prend le relais pour classify + match + export :
> ```bash
> redirectmap classify --db "$UPLOADS/redirect.db"
> redirectmap match --db "$UPLOADS/redirect.db" --fallback "<fallback>"
> redirectmap export --db "$UPLOADS/redirect.db" --formats csv,htaccess --vhost --output "$OUTPUT" \
>   --source-domain "<source>" --target-domain "<target>"
> ```

### Stats après le run
> La DB tmp est supprimée automatiquement après le run. Pour consulter les stats,
> passer `--db /tmp/mon_run.db` au `run` et utiliser ce chemin ici.
```bash
redirectmap stats --db "/tmp/mon_run.db"
```

---

## Phase 4 — Deliver output files

```bash
cp "$OUTPUT"/* "$DOCS/" 2>/dev/null || true
```

Présenter avec des liens `computer://`. Pour construire le chemin Windows :
```bash
WIN_USER=$(echo "$SANDBOX_ROOT" | grep -oP '(?<=/mnt/)[^/]+' | head -1)
echo "Chemin Windows : C:\\Users\\$WIN_USER\\Documents\\"
```

Fichiers livrés :
- `redirect_plan.csv` — plan complet (toujours)
- `redirect_plan.htaccess` — règles Apache (si demandé)
- `redirect_plan_map.conf` + `redirect_plan_server.conf` — règles Nginx (si demandé)
- `redirect_plan.xlsx` — classeur Excel (si demandé)

---

## Phase 5 — Summary

Toujours afficher après un run réussi :

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

Signaler toute ligne où `source_intention ≠ target_intention` comme risque SEO potentiel.

---

## Re-run partiel (ajuster les seuils sans re-crawler)

```bash
export PATH="$PATH:$HOME/.local/bin"
SANDBOX_ROOT=$(find /sessions/*/mnt -maxdepth 0 -type d 2>/dev/null | head -1)
REPO=$(find "$SANDBOX_ROOT/Documents" -maxdepth 3 -name "pyproject.toml" \
       -exec grep -l "name = \"redirectmap\"" {} \; 2>/dev/null \
       | head -1 | xargs dirname)

# Effacer uniquement les redirections, pas le crawl
sqlite3 "$REPO/redirect.db" "DELETE FROM redirects;"

redirectmap match \
  --db "$REPO/redirect.db" \
  --fallback "<fallback_url>" \
  --fuzzy-threshold <0-100> \
  --cosine-threshold <0.0-1.0>

redirectmap export \
  --db "$REPO/redirect.db" \
  --formats "<formats>" \
  --vhost \
  --output "$REPO/output" \
  --source-domain "<source_domain>" \
  --target-domain "<target_domain>"
```

---

## Onboarding collègue

Pour qu'un collègue utilise ce skill :

**Windows (recommandé)** :
1. Télécharger ou cloner le repo : `git clone https://github.com/1o68o7/redirect-stack.git`
2. Double-cliquer sur `install.bat` (ou `install.bat --browser` pour e-commerce)
3. Ouvrir Claude Cowork → "Sélectionner un dossier" → choisir `redirect-stack`
4. Double-cliquer sur `skill\redirectmap.skill` pour l'installer
5. Dire à Claude : "génère un plan de redirections"

**Linux / Mac** :
1. `git clone https://github.com/1o68o7/redirect-stack.git && cd redirect-stack`
2. `./install.sh` (ou `./install.sh --browser`)
3. Même étapes Cowork (3–5)

Le skill auto-installe redirectmap dans le sandbox Cowork à chaque session — aucune configuration supplémentaire.

---

## Troubleshooting

| Symptôme | Cause probable | Fix |
|----------|---------------|-----|
| `REPO` vide après bootstrap | Repo pas sélectionné dans Cowork | Cliquer "Sélectionner un dossier" → choisir le dossier redirect-stack |
| `command not found: redirectmap` | PATH non exporté | Re-lancer le bloc bootstrap complet |
| `Fichier introuvable : source.csv` | Chemin relatif sans upload | Uploader le CSV dans Cowork ou utiliser `$UPLOADS/nom.csv` |
| `0 pages stored` | DB corrompue | `rm redirect.db` et relancer |
| `Aucune page cible` | Mauvais flag `--site` | Wipe DB et relancer |
| Browser mode requis | camoufox pas dans le sandbox | Donner la commande PowerShell ; reprendre classify+match+export après |
| `camoufox` absent dans sandbox | Attendu | HTTP mode uniquement dans Cowork sandbox |
