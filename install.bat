@echo off
setlocal EnableDelayedExpansion

:: ─────────────────────────────────────────────────────────────────────────────
:: redirectmap — Windows install script
:: Usage : double-cliquer ou lancer depuis PowerShell
::   install.bat           -> mode HTTP uniquement
::   install.bat --browser -> avec camoufox (Firefox stealth, e-commerce)
:: ─────────────────────────────────────────────────────────────────────────────

set INSTALL_BROWSER=false
for %%A in (%*) do (
    if "%%A"=="--browser" set INSTALL_BROWSER=true
)

echo.
echo  ██████╗ ███████╗██████╗ ██╗██████╗ ███████╗ ██████╗████████╗
echo  ██╔══██╗██╔════╝██╔══██╗██║██╔══██╗██╔════╝██╔════╝╚══██╔══╝
echo  ██████╔╝█████╗  ██║  ██║██║██████╔╝█████╗  ██║        ██║
echo  ██╔══██╗██╔══╝  ██║  ██║██║██╔══██╗██╔══╝  ██║        ██║
echo  ██║  ██║███████╗██████╔╝██║██║  ██║███████╗╚██████╗   ██║
echo  ╚═╝  ╚═╝╚══════╝╚═════╝ ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝   ╚═╝
echo.
echo  Outil de migration d'URLs — generation de plans de redirections 301
echo  ─────────────────────────────────────────────────────────────────────
echo.

:: ── 1. Trouver Python ────────────────────────────────────────────────────────

set PYTHON_CMD=

:: Essayer le Python Launcher (recommande sur Windows)
where py >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%V in ('py -3 --version 2^>^&1') do set PY_VER=%%V
    echo [OK] Python Launcher detecte : !PY_VER!
    set PYTHON_CMD=py -3
    goto :python_found
)

:: Essayer python directement
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%V in ('python --version 2^>^&1') do set PY_VER=%%V
    echo [OK] Python detecte : !PY_VER!
    set PYTHON_CMD=python
    goto :python_found
)

:: Essayer python3
where python3 >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%V in ('python3 --version 2^>^&1') do set PY_VER=%%V
    echo [OK] Python detecte : !PY_VER!
    set PYTHON_CMD=python3
    goto :python_found
)

echo.
echo [ERREUR] Python non trouve sur ce systeme.
echo.
echo  Installez Python 3.11 ou superieur depuis :
echo  https://www.python.org/downloads/
echo  Cochez bien "Add Python to PATH" pendant l'installation.
echo.
pause
exit /b 1

:python_found

:: ── 2. Verifier la version (>= 3.10) ─────────────────────────────────────────

for /f "tokens=2 delims= " %%V in ('!PYTHON_CMD! --version 2^>^&1') do set RAW_VER=%%V
for /f "tokens=1,2 delims=." %%A in ("!RAW_VER!") do (
    set MAJOR=%%A
    set MINOR=%%B
)

if !MAJOR! LSS 3 (
    echo [ERREUR] Python !RAW_VER! trop ancien. Version 3.10 minimum requise.
    pause
    exit /b 1
)
if !MAJOR! EQU 3 if !MINOR! LSS 10 (
    echo [ERREUR] Python !RAW_VER! trop ancien. Version 3.10 minimum requise.
    pause
    exit /b 1
)

echo [OK] Version Python compatible : !RAW_VER!

:: ── 3. Creer le venv ─────────────────────────────────────────────────────────

echo.
echo =^> Creation de l'environnement virtuel .venv ...
if exist .venv (
    echo     .venv existant detecte, reutilisation.
) else (
    !PYTHON_CMD! -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERREUR] Impossible de creer le venv. Verifiez votre installation Python.
        pause
        exit /b 1
    )
)

:: ── 4. Installer redirectmap ──────────────────────────────────────────────────

echo.
if "!INSTALL_BROWSER!"=="true" (
    echo =^> Installation avec support navigateur [camoufox / Firefox stealth] ...
    echo     ^(recommande pour e-commerce, sites JS, protection anti-bot^)
    echo.
    .venv\Scripts\pip install --upgrade pip -q
    .venv\Scripts\pip install -e ".[browser]"
    if %errorlevel% neq 0 (
        echo [ERREUR] Echec de l'installation. Verifiez votre connexion Internet.
        pause
        exit /b 1
    )
    echo.
    echo =^> Telechargement de Firefox stealth [camoufox, ~100MB, une seule fois] ...
    .venv\Scripts\python -m camoufox fetch
) else (
    echo =^> Installation mode HTTP [rapide, sans navigateur] ...
    .venv\Scripts\pip install --upgrade pip -q
    .venv\Scripts\pip install -e .
    if %errorlevel% neq 0 (
        echo [ERREUR] Echec de l'installation. Verifiez votre connexion Internet.
        pause
        exit /b 1
    )
)

:: ── 5. Verifier l'installation ────────────────────────────────────────────────

echo.
echo =^> Verification ...
.venv\Scripts\redirectmap --version
if %errorlevel% neq 0 (
    echo [ERREUR] redirectmap introuvable apres installation.
    pause
    exit /b 1
)

:: ── 6. Instructions finales ───────────────────────────────────────────────────

echo.
echo ─────────────────────────────────────────────────────────────────────────────
echo  INSTALLATION TERMINEE
echo ─────────────────────────────────────────────────────────────────────────────
echo.
echo  OPTION A — via Claude Cowork [recommande, sans terminal]
echo  ─────────────────────────────────────────────────────────
echo  1. Ouvrez Claude Cowork
echo  2. Cliquez "Selectionner un dossier" et choisissez ce dossier
echo  3. Double-cliquez sur skill\redirectmap.skill pour l'installer
echo  4. Dites a Claude : "genere un plan de redirections"
echo.
echo  OPTION B — via terminal PowerShell
echo  ─────────────────────────────────
echo  Activez le venv :
echo    .venv\Scripts\activate
echo.
echo  Pipeline complet (HTTP, sites classiques) :
echo    redirectmap run ^
echo      --source-urls source.csv ^
echo      --target-urls target.csv ^
echo      --source-domain https://ancien-site.com ^
echo      --target-domain https://nouveau-site.com ^
echo      --fallback https://nouveau-site.com ^
echo      --formats csv,htaccess ^
echo      --output .\output

if "!INSTALL_BROWSER!"=="true" (
    echo.
    echo  Pipeline e-commerce [avec navigateur] :
    echo    redirectmap run ^
    echo      --source-urls source.csv ^
    echo      --target-urls target.csv ^
    echo      --browser ^
    echo      --source-domain https://ancien-site.com ^
    echo      --target-domain https://nouveau-site.com ^
    echo      --fallback https://nouveau-site.com ^
    echo      --formats csv,htaccess ^
    echo      --output .\output
)

echo.
echo  Option --vhost [staging/prod sans domaine code en dur] :
echo    Ajoutez --vhost a la commande ci-dessus.
echo    Exemple : RewriteRule ^old$ https://%%{HTTP_HOST}/new [R=301,L]
echo.
echo ─────────────────────────────────────────────────────────────────────────────
echo.
pause
