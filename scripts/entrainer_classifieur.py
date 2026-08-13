"""Entraine le classifieur et mesure les trois voies separement.

L'ablation est le point central de ce script : mesurer chaque voie isolement
puis leur combinaison est la seule facon de savoir si l'approche hybride
apporte reellement quelque chose, plutot que de le supposer.

La voie generative est evaluee sur un echantillon plus restreint : chaque
prediction coute un appel reseau, et un echantillon stratifie de quelques
dizaines de tickets suffit a situer son niveau.

    python scripts/entrainer_classifieur.py [--echantillon-llm 60]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sklearn.metrics import classification_report, confusion_matrix, f1_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

import maii  # noqa: F401,E402
from maii.classify import arbitrage, llm as voie_llm, regles as voie_regles  # noqa: E402
from maii.classify.ml import ClassifieurAppris  # noqa: E402
from maii.ingest.chargement import charger_tickets  # noqa: E402

RAPPORTS = maii.RACINE / "reports"


def separer(tickets: list[dict], part_test: float = 0.25, graine: int = 1789):
    """Separation stratifiee : chaque categorie garde sa proportion des deux cotes."""
    etiquettes = [t["categorie_reelle"] for t in tickets]
    # Une classe a un seul exemple ne peut pas etre stratifiee.
    rares = {c for c, n in Counter(etiquettes).items() if n < 2}
    utilisables = [t for t in tickets if t["categorie_reelle"] not in rares]
    etiquettes = [t["categorie_reelle"] for t in utilisables]
    return train_test_split(
        utilisables, test_size=part_test, random_state=graine, stratify=etiquettes
    )


def mesurer(vrais: list[str], predits: list[str], intitule: str) -> dict:
    macro = f1_score(vrais, predits, average="macro", zero_division=0)
    pondere = f1_score(vrais, predits, average="weighted", zero_division=0)
    exactitude = sum(v == p for v, p in zip(vrais, predits)) / len(vrais)
    print(f"  {intitule:<28} macro-F1 {macro:.4f}   F1 pondere {pondere:.4f}   "
          f"exactitude {exactitude:.4f}")
    return {
        "voie": intitule, "macro_f1": round(macro, 4),
        "f1_pondere": round(pondere, 4), "exactitude": round(exactitude, 4),
        "effectif": len(vrais),
    }


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--echantillon-llm", type=int, default=60)
    arguments = parseur.parse_args()

    tickets = charger_tickets()
    if not tickets:
        print("Historique absent : lancer data/synthetic/generer.py")
        return 1

    apprentissage, test = separer(tickets)
    print(f"Apprentissage : {len(apprentissage)} tickets")
    print(f"Test          : {len(test)} tickets")

    print("\nEntrainement du modele supervise...")
    modele = ClassifieurAppris().entrainer(apprentissage)
    chemin = modele.enregistrer()
    print(f"  {modele.nb_exemples} exemples, modele enregistre : "
          f"{chemin.relative_to(maii.RACINE)}")

    vrais = [t["categorie_reelle"] for t in test]
    textes = [t["description"] for t in test]

    print("\nAblation des voies (jeu de test complet)")
    print("-" * 78)
    resultats = []

    predits_regles = [
        (voie_regles.classer(t).categorie or "autre_indetermine") for t in textes
    ]
    predits_regles = [c.value if hasattr(c, "value") else c for c in predits_regles]
    resultats.append(mesurer(vrais, predits_regles, "A - regles seules"))

    predits_ml = [modele.classer(t).categorie.value for t in textes]
    resultats.append(mesurer(vrais, predits_ml, "B - modele supervise"))

    # --- voie generative et arbitrage, sur echantillon stratifie ------------
    taille = min(arguments.echantillon_llm, len(test))
    echantillon, _ = (test, None) if taille >= len(test) else separer(
        test, part_test=1 - taille / len(test)
    )
    vrais_e = [t["categorie_reelle"] for t in echantillon]
    textes_e = [t["description"] for t in echantillon]

    print(f"\nVoie generative et arbitrage (echantillon de {len(echantillon)} tickets)")
    print("-" * 78)

    voie_llm.selecteur().preparer(apprentissage)
    predits_llm, indisponibles = [], 0
    for t in textes_e:
        r = voie_llm.classer(t)
        if r.disponible and r.categorie:
            predits_llm.append(r.categorie.value)
        else:
            predits_llm.append("autre_indetermine")
            indisponibles += 1
    if indisponibles:
        print(f"  ({indisponibles} appels non exploitables sur {len(textes_e)})")
    resultats.append(mesurer(vrais_e, predits_llm, "C - modele de langage"))

    predits_fusion = [arbitrage.classer(t).categorie.value for t in textes_e]
    resultats.append(mesurer(vrais_e, predits_fusion, "A+B+C - arbitrage"))

    # Reference : les memes voies mesurees sur le seul echantillon, pour que la
    # comparaison avec l'arbitrage porte sur des effectifs identiques.
    indices = [textes.index(t) for t in textes_e]
    mesurer(vrais_e, [predits_regles[i] for i in indices], "  (rappel A sur echantillon)")
    mesurer(vrais_e, [predits_ml[i] for i in indices], "  (rappel B sur echantillon)")

    print("\nDetail par categorie - modele supervise")
    print("-" * 78)
    print(classification_report(vrais, predits_ml, zero_division=0))

    print("Matrice de confusion - modele supervise")
    print("-" * 78)
    classes = sorted(set(vrais) | set(predits_ml))
    matrice = confusion_matrix(vrais, predits_ml, labels=classes)
    largeur = max(len(c) for c in classes)
    print(" " * (largeur + 2) + " ".join(f"{c[:6]:>7}" for c in classes))
    for nom, ligne in zip(classes, matrice):
        print(f"{nom:<{largeur}}  " + " ".join(f"{v:>7}" for v in ligne))

    # --- plafond impose par le bruit d'etiquetage --------------------------
    bruites = [
        t for t in test
        if t.get("categorie_vraie_sans_bruit")
        and t["categorie_vraie_sans_bruit"] != t["categorie_reelle"]
    ]
    plafond = 1 - len(bruites) / len(test)
    print(f"\nBruit d'etiquetage sur le jeu de test : {len(bruites)}/{len(test)} "
          f"tickets ({len(bruites) / len(test):.1%})")
    print(f"Exactitude maximale atteignable        : {plafond:.1%}")

    RAPPORTS.mkdir(parents=True, exist_ok=True)
    sortie = RAPPORTS / "classification.json"
    sortie.write_text(json.dumps({
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "apprentissage": len(apprentissage), "test": len(test),
        "echantillon_llm": len(echantillon),
        "voies": resultats,
        "plafond_etiquetage": round(plafond, 4),
        "repartition_test": dict(Counter(vrais)),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapport enregistre : {sortie.relative_to(maii.RACINE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
