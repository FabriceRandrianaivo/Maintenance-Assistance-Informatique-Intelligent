"""Tests du jeu de donnees.

Verifie que les ressources annoncees par la section 7 du sujet sont presentes,
coherentes, et qu'elles contiennent effectivement les defauts que cette meme
section annonce. Un jeu de donnees trop propre invaliderait l'evaluation de la
robustesse.
"""

import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
BRUT = RACINE / "data" / "raw"

CATEGORIES_ATTENDUES = {
    "comptes_authentification", "reseau_connectivite", "materiel_informatique",
    "logiciels_applications", "imprimantes_peripheriques", "droits_acces",
    "cybersecurite", "autre_indetermine",
}


@pytest.fixture(scope="module")
def tickets() -> list[dict]:
    chemin = BRUT / "tickets_historiques.jsonl"
    if not chemin.exists():
        pytest.skip("jeu de donnees absent : lancer data/synthetic/generer.py")
    return [json.loads(l) for l in chemin.read_text(encoding="utf-8").splitlines() if l]


@pytest.fixture(scope="module")
def articles() -> list[dict]:
    chemin = BRUT / "base_connaissances" / "index.json"
    if not chemin.exists():
        pytest.skip("base de connaissances absente")
    return json.loads(chemin.read_text(encoding="utf-8"))


def test_les_ressources_de_la_section_7_sont_toutes_presentes():
    attendues = [
        "tickets_historiques.jsonl", "utilisateurs.csv", "equipements.csv",
        "services.csv", "incidents_actifs.json", "base_connaissances/index.json",
    ]
    manquantes = [f for f in attendues if not (BRUT / f).exists()]
    assert not manquantes, f"ressources manquantes : {manquantes}"


def test_les_huit_categories_du_sujet_sont_representees(tickets):
    presentes = {t["categorie_reelle"] for t in tickets}
    assert presentes == CATEGORIES_ATTENDUES


def test_les_categories_sont_desequilibrees(tickets):
    """Section 7 : les categories peuvent etre desequilibrees."""
    comptes: dict[str, int] = {}
    for t in tickets:
        comptes[t["categorie_reelle"]] = comptes.get(t["categorie_reelle"], 0) + 1
    parts = sorted(comptes.values())
    # La categorie la plus frequente doit peser au moins quatre fois la plus rare.
    assert parts[-1] >= 4 * parts[0]


def test_des_valeurs_manquantes_sont_presentes(tickets):
    """Section 7 : des valeurs manquantes."""
    incomplets = [t for t in tickets if not t.get("equipement_id") or not t.get("canal")]
    assert len(incomplets) >= 20


def test_des_tickets_sont_hors_distribution(tickets):
    """Section 7 : des exemples inhabituels."""
    assert sum(1 for t in tickets if t["nature"] == "hors_distribution") >= 5


def test_des_instructions_malveillantes_sont_presentes(tickets):
    """Sections 6 et 7 : des instructions malveillantes."""
    malveillants = [t for t in tickets if t["nature"] == "malveillant"]
    assert len(malveillants) >= 5
    corpus = " ".join(t["description"].lower() for t in malveillants)
    assert "ignore" in corpus or "instructions precedentes" in corpus


def test_le_bruit_d_etiquetage_est_trace(tickets):
    """Section 7 : des etiquettes imparfaites, dont on garde la verite terrain."""
    bruites = [
        t for t in tickets
        if t.get("categorie_vraie_sans_bruit")
        and t["categorie_vraie_sans_bruit"] != t["categorie_reelle"]
    ]
    assert 5 <= len(bruites) <= len(tickets) * 0.12


def test_des_tickets_similaires_ont_des_priorites_differentes(tickets):
    """Section 7 : des tickets similaires associes a des priorites differentes."""
    par_categorie: dict[str, set[str]] = {}
    for t in tickets:
        par_categorie.setdefault(t["categorie_reelle"], set()).add(t["priorite_reelle"])
    multi = [c for c, p in par_categorie.items() if len(p) > 1]
    assert len(multi) >= 5


def test_chaque_ticket_ordinaire_reference_une_procedure_existante(tickets, articles):
    """La verite terrain de la recherche documentaire doit pointer sur du reel."""
    connus = {a["doc_id"] for a in articles}
    for t in tickets:
        for doc in t.get("documents_pertinents", []):
            assert doc in connus, f"{t['ticket_id']} reference {doc}, absent de la base"


def test_les_articles_couvrent_toutes_les_categories(articles):
    couvertes = {a["categorie"] for a in articles}
    assert CATEGORIES_ATTENDUES <= couvertes | {"autre_indetermine"}
    assert len(articles) >= 20


def test_les_regles_de_securite_sont_documentees(articles):
    types = {a["type"] for a in articles}
    assert "regle_securite" in types
    assert "procedure_escalade" in types


def test_la_generation_est_reproductible():
    """Meme graine, meme jeu de donnees : condition d'une evaluation comparable."""
    import subprocess
    import sys

    avant = (BRUT / "tickets_historiques.jsonl").read_bytes()
    subprocess.run(
        [sys.executable, "data/synthetic/generer.py", "--graine", "1789", "--tickets", "420"],
        cwd=RACINE, check=True, capture_output=True,
    )
    assert (BRUT / "tickets_historiques.jsonl").read_bytes() == avant
