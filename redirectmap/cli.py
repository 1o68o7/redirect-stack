"""
redirectmap CLI — entry point for all pipeline commands.

Commands:
  redirectmap crawl    — crawl source or target URLs into SQLite
  redirectmap classify — classify pages by SEO intent (TF-IDF + KMeans)
  redirectmap match    — run the 4-phase matching pipeline
  redirectmap export   — export redirect plan (choisir les formats)
  redirectmap run      — full pipeline in one shot (crawl → classify → match → export)
  redirectmap stats    — print stats about a DB

Usage examples:
  # Full pipeline (mode navigateur, sortie CSV + htaccess uniquement)
  redirectmap run \\
      --source-urls source_urls.csv \\
      --target-urls target_urls.csv \\
      --browser \\
      --fallback https://new.example.com \\
      --source-domain https://old.example.com \\
      --target-domain https://new.example.com \\
      --formats csv,htaccess \\
      --output ./output

  # Étape par étape :
  redirectmap crawl --urls source.csv --site source --browser
  redirectmap crawl --urls target.csv --site target --browser
  redirectmap classify --db redirect.db
  redirectmap match  --db redirect.db --fallback https://new.example.com
  redirectmap export --db redirect.db --formats csv,htaccess --output ./output
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
from pathlib import Path

# Force UTF-8 sur Windows (cp1252 par défaut ne gère pas les caractères Unicode)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.table import Table

from redirectmap.config import load_config

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

_VALID_FORMATS = {"csv", "excel", "htaccess", "nginx", "json"}


def _parse_formats(formats_str: str) -> list[str]:
    """Valide et déduplique la liste de formats fournie."""
    requested = [f.strip().lower() for f in formats_str.split(",") if f.strip()]
    unknown = set(requested) - _VALID_FORMATS
    if unknown:
        console.print(f"[red]Formats inconnus : {', '.join(unknown)}. "
                      f"Formats valides : {', '.join(sorted(_VALID_FORMATS))}[/red]")
        sys.exit(1)
    return list(dict.fromkeys(requested))  # préserve l'ordre, déduplique


@click.group()
@click.version_option()
def cli():
    """redirectmap — URL crawl → classify → match → redirect plan generator."""


# ─── crawl ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--urls",  "-u", required=False, help="Fichier CSV/TXT avec les URLs.")
@click.option("--seed",  "-s", multiple=True,  help="URL(s) de départ. Répétable.")
@click.option("--site",  type=click.Choice(["source", "target"]), required=True)
@click.option("--db",    default="redirect.db", show_default=True)
@click.option("--browser", is_flag=True, default=False,
              help="Mode navigateur camoufox (JS, e-commerce, bot-protection). "
                   "Nécessite: pip install 'camoufox[geoip]' && python -m camoufox fetch")
@click.option("--no-sitemaps", is_flag=True, help="Désactive la découverte de sitemap.")
@click.option("--config", "cfg_path", default=None)
def crawl(urls, seed, site, db, browser, no_sitemaps, cfg_path):
    """
    Crawle les URLs et stocke les résultats dans SQLite.

    Deux modes disponibles :

    \b
    --browser  (recommandé pour e-commerce) :
      Utilise camoufox (Firefox stealth) pour rendre le JS,
      extraire les données produits (EAN13, prix, SKU) et
      contourner les protections bot (Cloudflare, DataDome).

    \b
    Sans --browser (mode HTTP léger) :
      httpx async — rapide, sans JS. Adapté pour les sites
      simples ou quand on dispose déjà des URLs finales en CSV.
    """
    cfg = load_config(cfg_path)
    seed_urls = list(seed)

    if urls:
        seed_urls += _load_url_file(urls)

    if not seed_urls:
        console.print("[red]Erreur : fournir --urls ou au moins un --seed.[/red]")
        sys.exit(1)

    from redirectmap import db as _db
    _db.init_db(db)

    mode_label = "[bold magenta]browser (camoufox)[/bold magenta]" if browser else "[bold blue]HTTP (httpx)[/bold blue]"
    console.print(f"[cyan]Crawl — {len(seed_urls)} URLs → site=[bold]{site}[/bold] "
                  f"| mode={mode_label} | db=[bold]{db}[/bold][/cyan]")

    if browser:
        from redirectmap.crawler.browser_crawler import BrowserCrawler
        crawler = BrowserCrawler(cfg=cfg["crawl"], db_path=db, site=site)
    else:
        from redirectmap.crawler.async_crawler import AsyncCrawler
        crawler = AsyncCrawler(cfg=cfg["crawl"], db_path=db, site=site)

    # follow_links=False quand une liste explicite est fournie via --urls
    # follow_links=True  quand on part d'un --seed (mode découverte BFS)
    follow_links = not bool(urls)
    if browser:
        total = asyncio.run(crawler.run(seed_urls, use_sitemaps=not no_sitemaps))
    else:
        total = asyncio.run(crawler.run(
            seed_urls, use_sitemaps=not no_sitemaps, follow_links=follow_links
        ))
    console.print(f"[green]✓ {total} nouvelles pages stockées.[/green]")


# ─── classify ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db",     default="redirect.db", show_default=True)
@click.option("--site",   default=None, help="Restreindre à 'source' ou 'target'. Défaut : tout.")
@click.option("--config", "cfg_path", default=None)
def classify(db, site, cfg_path):
    """
    Classifie les pages par intention SEO (TF-IDF + K-Means).

    \b
    Intentions détectées :
      informationnelle  — guides, articles, FAQ
      navigationnelle   — catégories, menus, landing brand
      transactionnelle  — fiches produit, checkout
      commerciale       — comparatifs, pages prix/offres
      divers            — CGV, mentions légales, erreurs

    \b
    Rôle dans le matching :
      - Tiebreaker entre candidats de score proche
      - Bonus de confiance si source et cible partagent la même intention
      - Malus si redirection transactionnelle → informationnelle (alerte)
    """
    cfg = load_config(cfg_path)
    console.print(f"[cyan]Classification des pages dans [bold]{db}[/bold]...[/cyan]")

    from redirectmap.classifier.intent import classify_pages
    summary = classify_pages(db_path=db, cfg=cfg["classify"], site=site)

    if summary:
        table = Table(title="Répartition des intentions SEO")
        table.add_column("Intention", style="cyan")
        table.add_column("Nb pages",  justify="right")
        for intent, count in sorted(summary.items(), key=lambda x: -x[1]):
            table.add_row(intent, str(count))
        console.print(table)
    else:
        console.print("[yellow]Aucune page à classifier.[/yellow]")


# ─── match ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db",               default="redirect.db", show_default=True)
@click.option("--fallback",         default="/", show_default=True,
              help="URL par défaut quand aucun match n'est trouvé.")
@click.option("--fuzzy-threshold",  default=80,   show_default=True, type=int,
              help="Score minimum rapidfuzz (0–100).")
@click.option("--cosine-threshold", default=0.30, show_default=True, type=float,
              help="Score minimum cosine similarity (0.0–1.0).")
@click.option("--batch-size",       default=1000, show_default=True, type=int)
@click.option("--config",           "cfg_path", default=None)
def match(db, fallback, fuzzy_threshold, cosine_threshold, batch_size, cfg_path):
    """
    Exécute le pipeline de matching en 4 phases.

    \b
    Phase 1 — Exact hash    : identité parfaite de chemin normalisé
    Phase 2 — Cosine        : similarité sémantique (titre + H1 + description + path)
    Phase 3 — Fuzzy         : rapidfuzz token_set_ratio sur le chemin URL
    Phase 4 — Hiérarchique  : L1 → L2 → L3 → root → fallback URL

    La classification est automatiquement déclenchée si elle n'a pas encore
    été exécutée (nécessaire pour l'ajustement d'intention).
    """
    cfg = load_config(cfg_path)
    cfg["match"]["fallback_url"]     = fallback
    cfg["match"]["fuzzy_threshold"]  = fuzzy_threshold
    cfg["match"]["cosine_threshold"] = cosine_threshold
    cfg["match"]["batch_size"]       = batch_size

    console.print(f"[cyan]Matching source → cible dans [bold]{db}[/bold]...[/cyan]")
    from redirectmap.matcher.pipeline import run_matching
    counters = run_matching(db_path=db, cfg=cfg["match"], classify_cfg=cfg.get("classify", {}))

    table = Table(title="Résultats du matching")
    table.add_column("Phase",     style="cyan")
    table.add_column("Nb règles", justify="right")
    phase_order = ["exact", "cosine", "fuzzy",
                   "hierarchical_L1", "hierarchical_L2", "hierarchical_L3",
                   "hierarchical_root", "fallback", "intent_adjusted"]
    for phase in phase_order:
        count = counters.get(phase, 0)
        if count or phase == "fallback":
            style = "green" if phase == "exact" else ("yellow" if "hierarchical" in phase or phase == "fallback" else "")
            table.add_row(phase, f"[{style}]{count}[/{style}]" if style else str(count))
    console.print(table)


# ─── export ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db",             default="redirect.db", show_default=True)
@click.option("--output",  "-o",  default="./output",    show_default=True)
@click.option("--formats", "-f",  default="csv",         show_default=True,
              help="Formats à générer, séparés par virgule. "
                   "Valeurs: csv, excel, htaccess, nginx, json. "
                   "Défaut: csv uniquement (le plus léger).")
@click.option("--source-domain",  default="", help="ex: https://old.example.com")
@click.option("--target-domain",  default="", help="ex: https://new.example.com")
@click.option("--vhost", is_flag=True, default=False,
              help="Mode vhost : remplace le domaine cible par %%{HTTP_HOST} (htaccess) "
                   "ou $host (nginx). Utile pour déployer les mêmes règles sur staging et prod.")
@click.option("--config",         "cfg_path", default=None)
def export(db, output, formats, source_domain, target_domain, vhost, cfg_path):
    """
    Exporte le plan de redirection dans les formats demandés.

    \b
    Formats disponibles :
      csv       — Tableur CSV (léger, toujours recommandé)
      excel     — Fichier .xlsx avec onglets Summary + Redirect Plan
      htaccess  — Règles Apache RewriteRule 301 prêtes à déployer
      nginx     — Blocs map {} + if {} pour Nginx
      json      — Format machine-readable pour intégrations externes

    \b
    Option --vhost :
      Génère des règles portables sans domaine cible codé en dur.
      htaccess : RewriteRule ^old-path$ https://%{HTTP_HOST}/new-path [R=301,L]
      nginx    : return 301 https://$host/new-path;
      Idéal pour les projets multi-environnements (staging, recette, prod).

    \b
    Conseil ressources :
      Pour 50k+ URLs, générer seulement les formats nécessaires.
      Excel est plus lent que CSV. htaccess + nginx sont rapides.
    """
    cfg = load_config(cfg_path)
    exp_cfg = cfg.get("export", {})
    src_domain = source_domain or exp_cfg.get("source_domain", "")
    tgt_domain = target_domain or exp_cfg.get("target_domain", "")
    fmt_list = _parse_formats(formats)

    # Guard: abort early if there are no redirects to export
    import sqlite3 as _sqlite3
    _db_path = Path(db)
    if not _db_path.exists():
        console.print(f"[red]DB introuvable : {db}[/red]")
        sys.exit(1)
    with _sqlite3.connect(str(_db_path)) as _chk:
        _n = _chk.execute("SELECT COUNT(*) FROM redirects").fetchone()[0]
    if _n == 0:
        console.print(
            "[yellow]⚠️  Aucune règle de redirection dans la DB — export annulé.\n"
            "   Cause probable : le matching n'a pas abouti (DB corrompue ou crawl incomplet).\n"
            "   Conseil : supprimez redirect.db et relancez le pipeline complet.[/yellow]"
        )
        sys.exit(1)

    vhost_label = " [bold magenta]+vhost[/bold magenta]" if vhost else ""
    console.print(f"[cyan]Export → [bold]{output}[/bold] | formats : {', '.join(fmt_list)}{vhost_label}[/cyan]")

    if "csv" in fmt_list:
        from redirectmap.exporter.csv_export import export_csv
        p = export_csv(db, output)
        console.print(f"  ✓ CSV      → {p}")

    if "excel" in fmt_list:
        from redirectmap.exporter.csv_export import export_excel
        p = export_excel(db, output)
        console.print(f"  ✓ Excel    → {p}")

    if "htaccess" in fmt_list:
        from redirectmap.exporter.htaccess import export_htaccess
        p = export_htaccess(db, output, src_domain, tgt_domain, vhost=vhost)
        console.print(f"  ✓ htaccess → {p}")

    if "nginx" in fmt_list:
        from redirectmap.exporter.nginx import export_nginx
        p_map, p_srv = export_nginx(db, output, src_domain, tgt_domain, vhost=vhost)
        console.print(f"  ✓ Nginx    → {p_map} + {p_srv}")

    if "json" in fmt_list:
        from redirectmap.exporter.json_export import export_json
        p = export_json(db, output)
        console.print(f"  ✓ JSON     → {p}")

    console.print("[green]Export terminé.[/green]")


# ─── run (pipeline complet) ───────────────────────────────────────────────────

@cli.command()
@click.option("--source-urls",   required=True,  help="Fichier CSV/TXT des URLs sources.")
@click.option("--target-urls",   required=True,  help="Fichier CSV/TXT des URLs cibles.")
@click.option("--db",            default=None, show_default=True,
              help="Chemin de la DB SQLite. Défaut: fichier temporaire dans /tmp "
                   "(évite les problèmes de permissions sur filesystems montés).")
@click.option("--output",  "-o", default="./output",    show_default=True)
@click.option("--fallback",      default="/",           show_default=True)
@click.option("--source-domain", default="")
@click.option("--target-domain", default="")
@click.option("--formats",       default="csv",         show_default=True,
              help="Formats d'export (csv, excel, htaccess, nginx, json). Défaut: csv.")
@click.option("--browser",       is_flag=True, default=False,
              help="Mode navigateur camoufox (recommandé pour e-commerce).")
@click.option("--vhost",         is_flag=True, default=False,
              help="Mode vhost : règles htaccess/nginx portables sans domaine cible codé en dur.")
@click.option("--no-sitemaps",   is_flag=True)
@click.option("--config",        "cfg_path", default=None)
def run(source_urls, target_urls, db, output, fallback, source_domain, target_domain,
        formats, browser, vhost, no_sitemaps, cfg_path):
    """Pipeline complet : crawl source + target → classify → match → export."""
    import tempfile, os
    cfg = load_config(cfg_path)
    ctx = click.get_current_context()

    # Si --db non fourni, utiliser un fichier temporaire dans /tmp
    # Cela évite les erreurs "Operation not permitted" sur filesystems FUSE/montés.
    _tmp_db = None
    if db is None:
        _tmp_fd, db = tempfile.mkstemp(suffix=".db", prefix="redirectmap_")
        os.close(_tmp_fd)
        os.unlink(db)  # laisser redirectmap créer la DB proprement
        _tmp_db = db
        console.print(f"[dim]DB temporaire : {db}[/dim]")

    console.rule("[bold cyan]Étape 1/4 — Crawl source[/bold cyan]")
    ctx.invoke(crawl, urls=source_urls, seed=(), site="source",
               db=db, browser=browser, no_sitemaps=no_sitemaps, cfg_path=cfg_path)

    console.rule("[bold cyan]Étape 2/4 — Crawl cible[/bold cyan]")
    ctx.invoke(crawl, urls=target_urls, seed=(), site="target",
               db=db, browser=browser, no_sitemaps=no_sitemaps, cfg_path=cfg_path)

    console.rule("[bold cyan]Étape 3/4 — Classification SEO[/bold cyan]")
    ctx.invoke(classify, db=db, site=None, cfg_path=cfg_path)

    console.rule("[bold cyan]Étape 4/4 — Matching[/bold cyan]")
    ctx.invoke(match,
               db=db, fallback=fallback,
               fuzzy_threshold=cfg["match"]["fuzzy_threshold"],
               cosine_threshold=cfg["match"]["cosine_threshold"],
               batch_size=cfg["match"]["batch_size"],
               cfg_path=cfg_path)

    console.rule("[bold cyan]Export[/bold cyan]")
    ctx.invoke(export,
               db=db, output=output, formats=formats,
               source_domain=source_domain, target_domain=target_domain,
               vhost=vhost, cfg_path=cfg_path)

    console.rule("[bold green]✓ Pipeline terminé[/bold green]")

    # Nettoyage de la DB temporaire si auto-générée
    if _tmp_db:
        try:
            Path(_tmp_db).unlink(missing_ok=True)
        except Exception:
            pass


# ─── stats ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db", default="redirect.db", show_default=True)
def stats(db):
    """Affiche les statistiques d'une redirect.db."""
    import sqlite3

    if not Path(db).exists():
        console.print(f"[red]DB introuvable : {db}[/red]")
        sys.exit(1)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        n_src    = conn.execute("SELECT COUNT(*) FROM pages WHERE site='source'").fetchone()[0]
        n_tgt    = conn.execute("SELECT COUNT(*) FROM pages WHERE site='target'").fetchone()[0]
        n_cls    = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        n_redir  = conn.execute("SELECT COUNT(*) FROM redirects").fetchone()[0]
        n_high   = conn.execute("SELECT COUNT(*) FROM redirects WHERE confidence='high'").fetchone()[0]
        n_medium = conn.execute("SELECT COUNT(*) FROM redirects WHERE confidence='medium'").fetchone()[0]
        n_low    = conn.execute("SELECT COUNT(*) FROM redirects WHERE confidence='low'").fetchone()[0]

    table = Table(title=f"DB stats — {db}")
    table.add_column("Métrique",           style="cyan")
    table.add_column("Valeur",             justify="right")
    table.add_row("Pages source crawlées", str(n_src))
    table.add_row("Pages cibles crawlées", str(n_tgt))
    table.add_row("Pages classifiées",     str(n_cls))
    table.add_row("Règles de redirection", str(n_redir))
    table.add_row("  ↳ confiance high",    f"[green]{n_high}[/green]")
    table.add_row("  ↳ confiance medium",  f"[yellow]{n_medium}[/yellow]")
    table.add_row("  ↳ confiance low",     f"[red]{n_low}[/red]")
    console.print(table)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _load_url_file(path: str) -> list[str]:
    """Charge les URLs depuis un CSV (colonne 'url') ou un TXT (une URL par ligne)."""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]Fichier introuvable : {path}[/red]")
        sys.exit(1)

    if p.suffix.lower() == ".csv":
        import pandas as pd
        try:
            df = pd.read_csv(p)
            for col in ("url", "URL", "Url", "address", "Address", "Adresse"):
                if col in df.columns:
                    return df[col].dropna().astype(str).tolist()
            return df.iloc[:, 0].dropna().astype(str).tolist()
        except Exception as e:
            console.print(f"[red]Erreur lecture {path}: {e}[/red]")
            sys.exit(1)
    else:
        return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
