# redirect-stack

> **Crawl d'URLs → classification SEO → matching 4 phases → export plan de redirections**

CLI Python qui automatise le pipeline complet de migration SEO — des listes d'URLs brutes aux règles `.htaccess` / nginx prêtes à déployer, avec scoring de confiance et matching basé sur l'intention SEO.

---

## Sommaire

- [Vue d'ensemble](#vue-densemble)
- [Architecture](#architecture)
- [Skill Cowork — mode sans terminal](#skill-cowork--mode-sans-terminal)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Référence CLI](#référence-cli)
- [Modes de crawl](#modes-de-crawl)
- [Classification par intention SEO](#classification-par-intention-seo)
- [Pipeline de matching](#pipeline-de-matching)
- [Formats d'export](#formats-dexport)
- [Configuration](#configuration)
- [Comprendre les résultats](#comprendre-les-résultats)
- [Dépannage](#dépannage)
- [Relancer des étapes partielles](#relancer-des-étapes-partielles)

---

## Vue d'ensemble

Lors d'une migration de site, chaque ancienne URL doit être explicitement redirigée (301) vers son équivalent ou vers la page la plus proche. Le faire manuellement sur des centaines ou milliers d'URLs est laborieux et source d'erreurs.

`redirect-stack` résout ce problème en :

1. **Crawlant** les sites source et cible pour extraire les métadonnées complètes (titre, H1, description, contenu, données structurées)
2. **Classifiant** les pages par intention SEO via TF-IDF + clustering K-Means
3. **Matchant** chaque URL source vers la meilleure URL cible via une cascade de 4 algorithmes
4. **Exportant** le plan de redirections dans le format adapté à votre stack technique

---

## Skill Cowork — mode sans terminal

redirect-stack inclut un skill pour [Claude Cowork](https://claude.ai) qui exécute le pipeline
complet à votre place — sans ligne de commande.

**Ce que ça fait :** déposez vos fichiers CSV dans le chat → Claude pose quelques questions
(domaines, mode, formats) → lance le pipeline → livre les fichiers de sortie directement dans
la conversation.

**Comment l'installer :**

1. Cloner le repo et sélectionner le dossier dans Cowork
2. Double-cliquer sur `skill/redirectmap.skill` pour l'installer
3. Démarrer une nouvelle conversation — le skill s'active automatiquement dès que vous mentionnez des redirections ou une migration d'URLs

Le skill installe automatiquement redirectmap dans le sandbox Cowork au premier usage. Aucune
configuration manuelle nécessaire. Le mode HTTP tourne entièrement dans Cowork ; le mode navigateur
(camoufox) nécessite une exécution depuis le terminal local.

**Partage avec des collègues :** chaque collègue clone le repo, installe le skill, et c'est prêt.
Le skill détecte dynamiquement l'emplacement du repo — aucun chemin codé en dur, fonctionne sur
toutes les machines.

```
redirect-stack/
└── skill/
    ├── SKILL.md            ← source du skill (versionné)
    └── redirectmap.skill   ← skill packagé (gitignored, à reconstruire avec package_skill.py)
```

Pour reconstruire le package `.skill` après modification du `SKILL.md` :
```bash
cd /chemin/vers/skill-creator
python -m scripts.package_skill /chemin/vers/redirect-stack/skill ./redirect-stack/skill
```

---

## Architecture

```
redirect-stack/
├── redirectmap/
│   ├── cli.py                  ← Point d'entrée (commandes Click)
│   ├── config.py               ← Chargement de la config avec valeurs par défaut
│   ├── db.py                   ← Couche SQLite (pages, classifications, redirections)
│   ├── crawler/
│   │   ├── async_crawler.py    ← Mode HTTP (httpx, BFS, sitemaps)
│   │   ├── browser_crawler.py  ← Mode navigateur (camoufox stealth Firefox)
│   │   └── sitemap.py          ← Découverte et parsing de sitemaps
│   ├── classifier/
│   │   └── intent.py           ← TF-IDF + KMeans + ajustement d'intention
│   ├── matcher/
│   │   ├── pipeline.py         ← Orchestration des 4 phases
│   │   ├── cosine.py           ← Phase 2 : similarité cosine TF-IDF
│   │   ├── fuzzy.py            ← Phase 3+4 : rapidfuzz + fallback hiérarchique
│   │   └── normalizer.py       ← Normalisation et hachage d'URLs
│   └── exporter/
│       ├── csv_export.py       ← CSV + Excel
│       ├── htaccess.py         ← Apache mod_rewrite
│       ├── nginx.py            ← Nginx map{} + server{}
│       └── json_export.py      ← JSON machine-readable
├── skill/
│   ├── SKILL.md                ← source du skill Cowork
│   └── redirectmap.skill       ← skill packagé (gitignored)
├── pyproject.toml
├── config.example.yaml
├── install.sh
└── Dockerfile / docker-compose.yml
```

Toutes les données de crawl, classifications et règles de redirection sont stockées dans une **base SQLite** (`redirect.db`), ce qui rend chaque étape reprise et ré-exécutable indépendamment.

---

## Installation

**Prérequis :** Python 3.11+

```bash
git clone https://github.com/1o68o7/redirect-stack.git
cd redirect-stack

# Mode HTTP uniquement (rapide, sans navigateur)
python3.11 -m venv .venv
source .venv/bin/activate       # Windows : .venv\Scripts\activate
pip install -e .

# Avec support navigateur (rendu JS, contournement bot-protection)
pip install -e ".[browser]"
python -m camoufox fetch        # Télécharge Firefox stealth ~100MB (une seule fois)
```

Ou via le script automatisé (Ubuntu/Debian) :

```bash
chmod +x install.sh
./install.sh           # Mode HTTP
./install.sh --browser # Avec support camoufox
```

**Toujours activer le venv avant utilisation :**
```bash
source .venv/bin/activate
redirectmap --version
```

**Installation du skill Cowork (optionnel — mode sans terminal) :**
```bash
# Après le clone, ouvrir Cowork → sélectionner le dossier redirect-stack
# → double-cliquer sur skill/redirectmap.skill pour installer
```

---

## Démarrage rapide

```bash
# 1. Activer l'environnement
cd redirect-stack
source .venv/bin/activate

# 2. Préparer les fichiers d'URLs
#    source.csv — URLs de l'ancien site
#    target.csv — URLs du nouveau site
#    (CSV avec colonne 'url', ou TXT avec une URL par ligne)

# 3. Lancer le pipeline complet
redirectmap run \
  --source-urls source.csv \
  --target-urls target.csv \
  --source-domain https://ancien-site.com \
  --target-domain https://nouveau-site.com \
  --fallback https://nouveau-site.com \
  --formats csv,htaccess \
  --output ./output

# 4. Consulter les résultats
redirectmap stats
ls ./output/
```

---

## Référence CLI

### `redirectmap run` — Pipeline complet en une commande

```
redirectmap run [OPTIONS]

  --source-urls TEXT     Fichier CSV/TXT des URLs sources           [requis]
  --target-urls TEXT     Fichier CSV/TXT des URLs cibles            [requis]
  --db TEXT              Chemin de la DB SQLite    [défaut: redirect.db]
  --output / -o TEXT     Répertoire de sortie      [défaut: ./output]
  --fallback TEXT        URL de repli (aucun match trouvé)          [défaut: /]
  --source-domain TEXT   ex: https://ancien-site.com
  --target-domain TEXT   ex: https://nouveau-site.com
  --formats TEXT         Formats d'export, séparés par virgule      [défaut: csv]
                         Valeurs : csv, excel, htaccess, nginx, json
  --browser              Mode navigateur camoufox (JS, e-commerce)
  --no-sitemaps          Désactiver la découverte de sitemaps
  --config TEXT          Chemin vers config.yaml
```

Exécute les 4 étapes en séquence : crawl source → crawl cible → classify → match → export.

---

### `redirectmap crawl` — Crawler des URLs dans SQLite

```
redirectmap crawl [OPTIONS]

  --urls / -u TEXT       Fichier CSV/TXT d'URLs à crawler
  --seed / -s TEXT       URL(s) de départ pour la découverte BFS (répétable)
  --site [source|target] Rôle du site pour les pages crawlées       [requis]
  --db TEXT              [défaut: redirect.db]
  --browser              Mode navigateur (camoufox)
  --no-sitemaps          Désactiver la découverte de sitemaps
  --config TEXT
```

**Sélection du mode :**
- `--urls` → mode liste : crawle exactement ces URLs, sans suivre les liens
- `--seed` → mode découverte : BFS depuis le seed + expansion via sitemap
- Les deux peuvent être combinés

---

### `redirectmap classify` — Classifier par intention SEO

```
redirectmap classify [OPTIONS]

  --db TEXT              [défaut: redirect.db]
  --site TEXT            Restreindre à 'source' ou 'target' (défaut : tout)
  --config TEXT
```

Lance TF-IDF + K-Means sur le contenu des pages crawlées. Les résultats sont stockés en DB et utilisés automatiquement par l'étape de matching. Déclenché automatiquement si absent avant le matching.

---

### `redirectmap match` — Pipeline de matching 4 phases

```
redirectmap match [OPTIONS]

  --db TEXT                    [défaut: redirect.db]
  --fallback TEXT              URL par défaut si aucun match     [défaut: /]
  --fuzzy-threshold INT        Score rapidfuzz minimum (0–100)   [défaut: 80]
  --cosine-threshold FLOAT     Score cosine minimum (0.0–1.0)    [défaut: 0.30]
  --batch-size INT             URLs par batch de traitement       [défaut: 1000]
  --config TEXT
```

---

### `redirectmap export` — Exporter le plan de redirections

```
redirectmap export [OPTIONS]

  --db TEXT              [défaut: redirect.db]
  --output / -o TEXT     [défaut: ./output]
  --formats / -f TEXT    [défaut: csv]
  --source-domain TEXT
  --target-domain TEXT
  --config TEXT
```

---

### `redirectmap stats` — Statistiques de la DB

```
redirectmap stats [--db TEXT]
```

Affiche : pages crawlées (source/cible), pages classifiées, total des règles de redirection, répartition par niveau de confiance (high / medium / low).

---

## Modes de crawl

### Mode HTTP (par défaut)

Utilise **httpx** avec concurrence asynchrone. Rapide, léger, sans rendu JavaScript.

**Idéal pour :**
- Sites statiques, CMS simples (WordPress, Drupal)
- Sites dont vous avez déjà la liste complète d'URLs (Screaming Frog, sitemap)
- Grands sites où la vitesse est prioritaire (10–50k URLs)

**Fonctionnement :**
1. Récupère les pages avec httpx (asynchrone, concurrence configurable)
2. Parse le HTML avec BeautifulSoup + lxml
3. Extrait : titre, meta description, H1, body text (tronqué à 20k caractères), données structurées
4. Respecte `robots.txt` (règles Disallow)
5. Découvre des URLs supplémentaires via sitemap (sauf `--no-sitemaps`)
6. Suivi de liens BFS si mode `--seed` (désactivé quand `--urls` est fourni)

**Reprise automatique :** Les URLs déjà en base sont ignorées.

---

### Mode navigateur (`--browser`)

Utilise **camoufox** — un Firefox stealth basé sur Playwright avec anti-fingerprinting. Rend le JavaScript, contourne les systèmes de bot-detection (Cloudflare, DataDome, PerimeterX).

**Idéal pour :**
- Plateformes e-commerce (PrestaShop, Magento, Shopify, WooCommerce)
- Sites avec contenu chargé en lazy-loading ou métadonnées SEO rendues en JS
- Sites qui retournent un HTML minimal aux navigateurs headless

**Fonctionnement :**
1. Ouvre des instances Firefox stealth (patches anti-fingerprinting appliqués)
2. Navigue vers chaque URL avec `wait_until="domcontentloaded"` (timeout 25s)
3. Extrait le contenu complet incluant les éléments rendus en JS
4. Extrait les données structurées e-commerce : JSON-LD `Product`, `BreadcrumbList`, `ItemList` (EAN13, prix, SKU, marque, fil d'Ariane)
5. Pour les pages bloquées par bot-protection (< 200 caractères HTML), bascule automatiquement sur **httpx**
6. Timeout maximum de 40s par URL pour éviter les blocages infinis
7. Concurrence recommandée : 2 (consommation mémoire Firefox)

---

### Format des fichiers CSV pour `--urls`

Le fichier d'URLs peut être :
- **CSV** avec une colonne nommée `url`, `URL`, `Url`, `address`, `Address` ou `Adresse` (première colonne utilisée par défaut)
- **TXT** avec une URL par ligne

Les exports Screaming Frog fonctionnent nativement (colonne `Address`).

```csv
Address
https://ancien-site.com/produits/robot-5200xl
https://ancien-site.com/produits/robot-expert
https://ancien-site.com/categorie/robots
```

---

## Classification par intention SEO

Avant le matching, chaque page est classifiée dans l'une des 5 catégories d'intention SEO via **vectorisation TF-IDF + clustering K-Means** sur le contenu textuel.

### Taxonomie des intentions

| Intention | Description | Exemples |
|-----------|-------------|---------|
| `informationnelle` | Éducatif, guides, articles, FAQ | Articles de blog, tutoriels, pages how-to |
| `navigationnelle` | Pages catégorie, landing marque, menus | `/produits/`, `/marque/`, listings catégorie |
| `transactionnelle` | Fiche produit, checkout, ajout panier | PDPs, `/commander/`, pages panier |
| `commerciale` | Comparatifs, prix, pages offres | `/tarifs/`, guides comparatifs, pages promo |
| `divers` | Légal, CGV, 404, pages génériques | CGV, politique cookies, pages d'erreur |

### Construction du corpus

Pour chaque page, le classifier construit un texte pondéré :

```
texte = titre × 3 + h1 × 3 + meta_description + body_text[:5000]
```

Le titre et le H1 sont répétés 3× car ils portent le signal d'intention le plus fort.

### Paramètres TF-IDF (configurables)

```yaml
classify:
  n_clusters: 5        # Nombre de clusters = nombre de catégories d'intention
  max_features: 5000   # Taille du vocabulaire TF-IDF
  min_df: 2            # Ignorer les termes présents dans moins de 2 docs
  max_df: 0.85         # Ignorer les termes dans plus de 85% des docs
  language: "french"   # "french" ou "english"
```

---

## Pipeline de matching

Le matching s'exécute en **4 phases séquentielles**. Chaque phase ne traite que les URLs non matchées par la précédente.

### Phase 1 — Correspondance exacte (hash)

**Algorithme :** Hash MD5 du chemin URL normalisé  
**Complexité :** O(1) par URL (lookup dans une hash map)  
**Confiance :** toujours `high`  
**Score :** 100.0

L'URL est normalisée avant le hash : mise en minuscules, slashes finaux supprimés, paramètres de requête retirés. Si le chemin normalisé d'une URL source correspond exactement à une URL cible, la redirection est parfaite.

**Exemple :**
```
source: https://ancien-site.com/produits/robot-cuiseur-5200xl
cible:  https://nouveau-site.com/produits/robot-cuiseur-5200xl
→ exact match, score 100, confiance high
```

---

### Phase 2 — Similarité cosine (matching sémantique)

**Algorithme :** TF-IDF sur `(titre + H1 + description + chemin normalisé)` avec unigrammes + bigrammes, puis `linear_kernel` (équivalent à la similarité cosine sur vecteurs L2-normalisés)  
**Bibliothèque :** scikit-learn  
**Seuil par défaut :** 0.30 (configurable via `--cosine-threshold`)

Pour chaque page source non matchée, le vectoriseur la transforme en vecteur TF-IDF creux, puis calcule la similarité par produit scalaire contre tous les vecteurs des pages cibles. Retourne le meilleur match au-dessus du seuil.

**Niveaux de confiance (avant ajustement d'intention) :**

| Score cosine | Confiance brute |
|-------------|-----------------|
| ≥ 0.70 | `high` |
| ≥ 0.40 | `medium` |
| < 0.40 (mais ≥ seuil) | `low` |

**Cas d'usage typique :** Détecter des pages renommées, réorganisées ou déplacées vers une structure d'URL différente mais au contenu similaire.

**Exemple :**
```
source: /ancienne-categorie/robot-multifonction-5200xl → titre: "Robot 5200 XL"
cible:  /robots/serie-cook/5200-xl                    → titre: "Cuiseur 5200 XL"
→ cosine match, score 0.68, confiance medium
```

---

### Phase 3 — Matching fuzzy du chemin URL

**Algorithme :** `rapidfuzz.fuzz.token_set_ratio` sur les chemins URL normalisés  
**Seuil par défaut :** 80 (configurable via `--fuzzy-threshold`)  
**Complexité :** O(n × m) — optimisé via `process.extractOne`

Compare la **composante chemin** des URLs source et cible avec le token set ratio, qui gère bien la réorganisation de mots et les correspondances partielles.

**Exemple :**
```
source: /accessoires/disque-ondule-mini-plus
cible:  /accessories/mini-plus-wavy-disc
→ fuzzy match, score 82, confiance medium
```

**Niveaux de confiance :**

| Score fuzzy | Confiance brute |
|------------|-----------------|
| ≥ 85 | `high` |
| ≥ 70 | `medium` |
| < 70 (mais ≥ seuil) | `low` |

---

### Phase 4 — Fallback hiérarchique

Quand aucun match fuzzy n'atteint le seuil, le matcher **remonte l'arborescence** du chemin source niveau par niveau, en cherchant des segments parents correspondants dans le site cible.

**Remontée pour `/fr/produits/robot-cuiseur/cook-expert-premium/` :**

| Niveau | Chemin testé | Score | Confiance |
|--------|-------------|-------|-----------|
| fuzzy | `/fr/produits/robot-cuiseur/cook-expert-…` | ≥ seuil | high/medium |
| L1 | `/fr/produits/robot-cuiseur` | 40.0 | `medium` |
| L2 | `/fr/produits` | 25.0 | `low` |
| L3 | `/fr` | 15.0 | `low` |
| root | `/` | 5.0 | `low` |
| fallback | `<URL configurée>` | 0.0 | `low` |

**Pourquoi L2/L3 est utile :** Sur les sites e-commerce à arborescences profondes (4–5 niveaux), une migration peut restructurer complètement les catégories. Sans fallback hiérarchique, ces URLs tombent directement sur l'URL de repli alors qu'une catégorie parente pertinente existe côté cible.

---

### Ajustement d'intention (post-traitement)

Après les 4 phases, le niveau de confiance de chaque redirection est **ajusté selon l'alignement d'intention SEO** entre les pages source et cible.

#### Bonus : même famille d'intention → montée en confiance

```
(transactionnelle → transactionnelle) : low → medium, medium → high
(commerciale      → commerciale)      : low → medium, medium → high
(informationnelle → informationnelle) : low → medium, medium → high
(navigationnelle  → navigationnelle)  : low → medium, medium → high
```

#### Malus : conflit sémantique → forcé à `low` + flag `intent_mismatch`

```
(transactionnelle → informationnelle)  ← fiche produit vers article de blog
(transactionnelle → divers)            ← fiche produit vers page légale
(commerciale      → informationnelle)  ← page tarifs vers article
(commerciale      → divers)
(informationnelle → transactionnelle)  ← article vers fiche produit
```

Ces cas sont conservés dans l'export pour revue manuelle — ils ne sont pas supprimés silencieusement.

---

### Tableau récapitulatif du matching

| Phase | Algorithme | Idéal pour | Confiance en sortie |
|-------|-----------|------------|---------------------|
| 1 — Exact | Hash URL | Chemins identiques, migrations sans restructuration | toujours `high` |
| 2 — Cosine | TF-IDF sémantique | Contenu renommé, arbres restructurés au contenu préservé | `high`/`medium`/`low` |
| 3 — Fuzzy | token_set_ratio | Chemins similaires, légères réécriture d'URLs | `high`/`medium`/`low` |
| 4 — Hiérarchique | Remontée d'arbre | Arbres profonds, restructurations complètes | `medium`/`low` |
| Fallback | URL configurée | Aucun match trouvé | toujours `low` |

---

## Formats d'export

### CSV (`--formats csv`)

Léger, toujours recommandé. Une ligne par règle de redirection.

```
source_url, target_url, match_type, score, confidence, source_intention, target_intention
```

### Excel (`--formats excel`)

Classeur `.xlsx` avec deux feuilles :
- **Redirect Plan** — règles complètes avec toutes les colonnes
- **Summary** — statistiques par type de match et niveau de confiance

Utile pour la revue manuelle par des équipes non techniques.

### Apache htaccess (`--formats htaccess`)

Génère des règles `mod_rewrite` 301 groupées par niveau de confiance :

```apache
RewriteEngine On

# ── Confiance élevée (exact / cosine fort / fuzzy ≥85) ───────────────────
RewriteRule ^ancien-chemin/page\.html$ https://nouveau-site.com/nouveau-chemin/page [R=301,L]

# ── Confiance moyenne (cosine / fuzzy / hiérarchique L1) ─────────────────
RewriteRule ^ancien/chemin$ https://nouveau-site.com/meilleur-match [R=301,L]
```

À placer dans `<VirtualHost>` ou `.htaccess`. Nécessite `mod_rewrite` activé (`a2enmod rewrite`).

### Nginx (`--formats nginx`)

Génère deux fichiers :
- `redirect_map.conf` — bloc `map $request_uri $redirect_target { ... }`
- `redirect_server.conf` — bloc `server {}` avec la condition `if`

### JSON (`--formats json`)

Tableau machine-readable. Utile pour l'intégration avec des CDN (Cloudflare, Fastly), middleware custom ou plugins CMS.

---

## Configuration

Copier `config.example.yaml` en `config.yaml` et ajuster :

```yaml
crawl:
  concurrency: 10       # Requêtes simultanées (mode navigateur : 2 recommandé, max 5)
  delay: 1.0            # Délai de politesse entre requêtes (secondes)
  timeout: 60           # Timeout par requête — critique en mode navigateur
  max_depth: 5          # Profondeur BFS maximale depuis l'URL de départ
  max_pages: 50000      # Pages maximum par site
  user_agent: "redirectmap/1.1"
  respect_robots: true
  # proxies:            # Liste de proxies optionnelle pour le mode navigateur
  #   - "http://proxy1:8080"

classify:
  n_clusters: 5         # = nombre de catégories d'intention SEO
  max_features: 5000    # Taille du vocabulaire TF-IDF
  min_df: 2             # Fréquence doc minimale pour un terme
  max_df: 0.85          # Fréquence doc maximale (supprime les stop-words domaine)
  language: "french"    # "french" ou "english"

match:
  fuzzy_threshold: 80   # Score fuzzy minimum pour accepter un match (0–100)
  cosine_threshold: 0.30 # Score cosine minimum (0.0–1.0)
  fallback_url: "/"     # Utilisé quand aucun match trouvé à aucune phase
  batch_size: 1000      # URLs par batch de traitement

export:
  output_dir: "./output"
  formats:
    - csv
    - htaccess
  source_domain: "https://ancien-site.com"
  target_domain: "https://nouveau-site.com"
```

Passer avec `--config config.yaml` sur n'importe quelle commande.

---

## Comprendre les résultats

### Colonnes du CSV

| Colonne | Type | Description |
|---------|------|-------------|
| `source_url` | string | Ancienne URL à rediriger (FROM) |
| `target_url` | string | Nouvelle URL de destination (TO) |
| `match_type` | enum | Comment le match a été trouvé (voir ci-dessous) |
| `score` | float | Score de correspondance (0–100) |
| `confidence` | enum | `high` / `medium` / `low` |
| `source_intention` | enum | Intention SEO de la page source |
| `target_intention` | enum | Intention SEO de la page cible |

### Valeurs de `match_type`

| Valeur | Phase | Signification |
|--------|-------|---------------|
| `exact` | 1 | Chemins normalisés identiques |
| `cosine` | 2 | Meilleur match sémantique de contenu |
| `fuzzy` | 3 | Meilleur match fuzzy de chemin |
| `hierarchical_L1` | 4 | Matchée sur la catégorie parente directe |
| `hierarchical_L2` | 4 | Matchée sur la catégorie grand-parente |
| `hierarchical_L3` | 4 | Matchée sur la catégorie arrière-grand-parente |
| `hierarchical_root` | 4 | Matchée sur la racine `/` |
| `fallback` | 4 | Aucun match — utilise l'URL de repli configurée |

### Recommandations de déploiement

- **Confiance `high`** → déploiement direct sans revue
- **Confiance `medium`** → vérification spot recommandée avant déploiement
- **Confiance `low`** → revue manuelle requise, en particulier les lignes hiérarchiques et fallback
- **`intent_mismatch`** → revue obligatoire : conflit sémantique entre les types de pages source et cible

---

## Dépannage

| Symptôme | Cause | Solution |
|----------|-------|----------|
| `command not found: redirectmap` | Venv non activé | `source .venv/bin/activate` |
| Toutes les URLs timeout à 20s | Valeur par défaut config écrase le code | Mettre `timeout: 60` dans `config.yaml` |
| `0 pages cibles stockées` | Contrainte UNIQUE DB sur l'URL | `rm redirect.db` et relancer |
| Le site retourne 39 caractères HTML | Bot-protection détectée | Normal — outil bascule automatiquement sur httpx |
| BFS crawle tout le site | `--seed` utilisé sans `--urls` | Utiliser `--urls monfichier.csv` pour le mode liste exacte |
| `source_intention` vide dans le CSV | body_text vide après crawl navigateur | Cosmétique — n'affecte pas le matching |
| Erreur import `camoufox` | Extras navigateur non installés | `pip install 'camoufox[geoip]' && python -m camoufox fetch` |
| `Aucune page cible — matching annulé` | Crawl cible a stocké 0 pages | Vérifier `--site target` pour le crawl cible ; `rm redirect.db` et réessayer |

---

## Relancer des étapes partielles

La DB SQLite rend chaque étape indépendante. Vous pouvez ne relancer que ce dont vous avez besoin :

```bash
# Relancer uniquement le matching (seuils différents, mêmes données crawlées)
sqlite3 redirect.db "DELETE FROM redirects;"
redirectmap match --db redirect.db \
  --fallback https://nouveau-site.com \
  --fuzzy-threshold 75 \
  --cosine-threshold 0.25
redirectmap export --db redirect.db --formats csv,htaccess --output ./output

# Relancer uniquement l'export (format différent)
redirectmap export --db redirect.db --formats excel,nginx --output ./output

# Reclassifier (n_clusters ou langue modifiés)
sqlite3 redirect.db "DELETE FROM classifications;"
redirectmap classify --db redirect.db
redirectmap match --db redirect.db --fallback https://nouveau-site.com
redirectmap export --db redirect.db --formats csv,htaccess --output ./output

# Remise à zéro complète
rm redirect.db
```

---

## Docker

```bash
docker-compose up
```

Ou build manuel :

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

## Licence

Privée — tous droits réservés.
