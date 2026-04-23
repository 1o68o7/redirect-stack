@echo off
setlocal EnableDelayedExpansion

:: -----------------------------------------------------------------------------
:: redirectmap -- Windows uninstall script
:: Supprime le venv local (.venv) et les fichiers generes (output/, redirect.db)
:: Le code source n'est PAS supprime.
:: -----------------------------------------------------------------------------

echo.
echo  ================================================
echo    REDIRECTMAP  ^|  Desinstallation
echo  ================================================
echo.

set /p CONFIRM=Supprimer .venv, output\ et redirect.db ? [O/N] :
if /i "!CONFIRM!" neq "O" (
    echo Annule.
    pause
    exit /b 0
)

:: -- Supprimer le venv --------------------------------------------------------
if exist .venv (
    echo.
    echo =^> Suppression de .venv ...
    rmdir /s /q .venv
    echo [OK] .venv supprime.
) else (
    echo [INFO] Pas de .venv trouve.
)

:: -- Supprimer la base de donnees ---------------------------------------------
if exist redirect.db (
    echo.
    echo =^> Suppression de redirect.db ...
    del /f /q redirect.db
    echo [OK] redirect.db supprime.
)

:: -- Supprimer les exports ----------------------------------------------------
if exist output (
    echo.
    echo =^> Suppression du dossier output\ ...
    rmdir /s /q output
    echo [OK] output\ supprime.
)

echo.
echo =============================================================================
echo  Desinstallation terminee.
echo  Pour reinstaller : double-cliquer sur install.bat
echo =============================================================================
echo.
pause
