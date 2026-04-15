#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# redirectmap — VPS install script (Ubuntu 22.04 / Python 3.11+)
# Usage: chmod +x install.sh && ./install.sh [--browser]
#
# --browser : installe aussi camoufox (Firefox stealth, recommandé e-commerce)
# ─────────────────────────────────────────────────────────────────────────────
set -e

INSTALL_BROWSER=false
for arg in "$@"; do
    [[ "$arg" == "--browser" ]] && INSTALL_BROWSER=true
done

echo "==> Installation des dépendances système..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip \
    gcc libxml2-dev libxslt-dev git

if $INSTALL_BROWSER; then
    echo "==> Dépendances système pour camoufox (Firefox)..."
    sudo apt-get install -y --no-install-recommends \
        libgtk-3-0 libdbus-glib-1-2 libxt6 \
        libx11-xcb1 libxcb-shm0 libxcb-dri3-0 \
        libasound2 libpulse0 libdrm2 \
        libgbm1 libgl1
fi

echo "==> Création de l'environnement virtuel..."
python3.11 -m venv .venv
source .venv/bin/activate

echo "==> Installation de redirectmap..."
pip install --upgrade pip

if $INSTALL_BROWSER; then
    echo "==> Installation avec support navigateur (camoufox)..."
    pip install -e ".[browser]"
    echo "==> Téléchargement de Firefox stealth (camoufox, ~100MB, une seule fois)..."
    python -m camoufox fetch
else
    echo "==> Installation mode HTTP uniquement..."
    pip install -e .
fi

echo ""
echo "✅  Installation terminée !"
echo ""
echo "Activez le venv :  source .venv/bin/activate"
echo ""
echo "Démarrage rapide :"
echo "  cp config.example.yaml config.yaml"
echo "  # Éditez config.yaml (domaines, seuils, formats)"
echo ""
echo "  # Pipeline complet (mode navigateur, e-commerce) :"
echo "  redirectmap run \\"
echo "    --source-urls source.csv \\"
echo "    --target-urls target.csv \\"
echo "    --browser \\"
echo "    --fallback https://new-site.com \\"
echo "    --source-domain https://old-site.com \\"
echo "    --target-domain https://new-site.com \\"
echo "    --formats csv,htaccess \\"
echo "    --output ./output"
echo ""
echo "  # Pipeline sans navigateur (HTTP rapide) :"
echo "  redirectmap run \\"
echo "    --source-urls source.csv \\"
echo "    --target-urls target.csv \\"
echo "    --formats csv,htaccess \\"
echo "    --output ./output"
