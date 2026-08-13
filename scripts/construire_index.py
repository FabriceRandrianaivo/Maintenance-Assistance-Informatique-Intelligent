"""Construit l'index documentaire et mesure sa qualite de rappel.

La verite terrain provient du jeu de donnees : chaque ticket ordinaire reference
les articles censes y repondre. On mesure donc le rappel sur les tickets reels,
et non sur des requetes ecrites apres coup pour flatter l'index.

    python scripts/construire_index.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import maii  # noqa: F401,E402
from maii.ingest.chargement import charger_articles, charger_tickets  # noqa: E402
from maii.rag.index import IndexDocumentaire  # noqa: E402


def evaluer_rappel(index: IndexDocumentaire, tickets: list[dict], k_max: int = 5) -> dict:
    """Rappel@k et rang reciproque moyen sur les tickets a verite terrain."""
    evaluables = [
        t for t in tickets
        if t.get("documents_pertinents") and t["nature"] == "ordinaire"
    ]
    if not evaluables:
        return {}

    rappels = {k: 0 for k in (1, 3, 5)}
    somme_rr = 0.0
    par_categorie: dict[str, list[int]] = defaultdict(list)

    for ticket in evaluables:
        attendus = set(ticket["documents_pertinents"])
        resultat = index.rechercher(ticket["description"], k=k_max)
        trouves = [p.doc_id for p in resultat.passages]

        for k in rappels:
            if attendus & set(trouves[:k]):
                rappels[k] += 1

        rang = next((i + 1 for i, d in enumerate(trouves) if d in attendus), 0)
        somme_rr += 1.0 / rang if rang else 0.0
        par_categorie[ticket["categorie_reelle"]].append(1 if rang and rang <= 5 else 0)

    total = len(evaluables)
    return {
        "tickets_evalues": total,
        "rappel": {k: round(v / total, 4) for k, v in rappels.items()},
        "mrr": round(somme_rr / total, 4),
        "par_categorie": {
            c: round(sum(v) / len(v), 4) for c, v in sorted(par_categorie.items())
        },
    }


def main() -> int:
    articles = charger_articles()
    if not articles:
        print("Base de connaissances absente : lancer data/synthetic/generer.py")
        return 1

    print("Construction de l'index...")
    index = IndexDocumentaire().construire(articles)
    chemin = index.enregistrer()

    print(f"  {len(articles):>4} articles")
    print(f"  {len(index.passages):>4} passages indexes")
    longueurs = [len(p.contenu) for p in index.passages]
    print(f"  {sum(longueurs) // len(longueurs):>4} caracteres par passage en moyenne")
    print(f"  index enregistre : {chemin.relative_to(maii.RACINE)}")

    print("\nQualite du rappel (verite terrain des tickets)")
    print("-" * 68)
    mesures = evaluer_rappel(index, charger_tickets())
    if not mesures:
        print("  aucun ticket evaluable")
        return 0

    print(f"  tickets evalues : {mesures['tickets_evalues']}")
    for k, valeur in mesures["rappel"].items():
        print(f"  Rappel@{k}        : {valeur:.1%}")
    print(f"  MRR             : {mesures['mrr']:.4f}")

    print("\n  Rappel@5 par categorie")
    for categorie, valeur in mesures["par_categorie"].items():
        alerte = "  <-- a surveiller" if valeur < 0.8 else ""
        print(f"    {categorie:<30} {valeur:.1%}{alerte}")

    print("\nExemples de recherche")
    print("-" * 68)
    for requete in [
        "jarive pas a imprimer depuis ce matin",
        "mon compte est verrouille apres plusieurs tentatives",
        "jai recu un mail qui demande mes identifiants, sa parait louche",
        "quelle est la recette du gateau au chocolat",
    ]:
        resultat = index.rechercher(requete, k=3)
        print(f"\n  « {requete} »")
        print(f"    confiance : {resultat.confiance:.3f}")
        for p in resultat.passages:
            print(
                f"    {p.reference:<16} cos={p.score_dense:.3f} bm25={p.score_bm25:.3f}"
                f"  {p.titre[:52]}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
