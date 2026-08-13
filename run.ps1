# Lancement du prototype mAIntenance & Assistance (Windows).
#
#   .\run.ps1              installe, prepare les donnees et lance l'interface
#   .\run.ps1 -Scenarios   rejoue les quatre scenarios obligatoires
#   .\run.ps1 -Evaluer     entraine le classifieur et publie les mesures

param(
    [switch]$Scenarios,
    [switch]$Evaluer,
    [switch]$SansInstallation
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $SansInstallation) {
    Write-Host "Installation des dependances..." -ForegroundColor Cyan
    python -m pip install --quiet --disable-pip-version-check -r requirements.txt
}

if (-not (Test-Path "data/raw/tickets_historiques.jsonl")) {
    Write-Host "Generation du jeu de donnees..." -ForegroundColor Cyan
    python data/synthetic/generer.py --graine 1789 --tickets 420
}

if (-not (Test-Path "data/index/documentaire.pkl")) {
    Write-Host "Construction de l'index documentaire..." -ForegroundColor Cyan
    python scripts/construire_index.py
}

if (-not (Test-Path "data/index/classifieur.pkl")) {
    Write-Host "Entrainement du classifieur..." -ForegroundColor Cyan
    python scripts/entrainer_classifieur.py
}

if ($Scenarios) {
    python scripts/demo_scenarios.py
    exit $LASTEXITCODE
}

if ($Evaluer) {
    python scripts/entrainer_classifieur.py
    python scripts/construire_index.py
    python scripts/demo_scenarios.py
    exit $LASTEXITCODE
}

Write-Host "Lancement de l'interface sur http://localhost:8501" -ForegroundColor Green
python -m streamlit run ui/app.py
