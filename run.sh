#!/usr/bin/env bash
# Lancement du prototype mAIntenance & Assistance (Linux / macOS).
#
#   ./run.sh              installe, prepare les donnees et lance l'interface
#   ./run.sh scenarios    rejoue les quatre scenarios obligatoires
#   ./run.sh evaluer      entraine le classifieur et publie les mesures
#   ./run.sh tests        execute la suite de tests

set -euo pipefail
cd "$(dirname "$0")"

if [ "${SANS_INSTALLATION:-0}" != "1" ]; then
    echo "Installation des dependances..."
    python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

if [ ! -f "data/raw/tickets_historiques.jsonl" ]; then
    echo "Generation du jeu de donnees..."
    python3 data/synthetic/generer.py --graine 1789 --tickets 420
fi

# L'index et le classifieur sont des artefacts derives, non versionnes :
# ils sont reconstruits s'ils manquent.
python3 -c "
import sys; sys.path.insert(0, 'src')
from maii.bootstrap import preparer
etat = preparer()
for m in etat.messages: print(' ', m)
for e in etat.erreurs:  print('  ERREUR:', e)
"

case "${1:-interface}" in
    scenarios)
        exec python3 scripts/demo_scenarios.py
        ;;
    evaluer)
        python3 scripts/entrainer_classifieur.py
        python3 scripts/construire_index.py
        exec python3 scripts/demo_scenarios.py
        ;;
    tests)
        exec python3 -m pytest tests -q
        ;;
    *)
        echo "Lancement de l'interface sur http://localhost:8501"
        exec python3 -m streamlit run ui/app.py
        ;;
esac
