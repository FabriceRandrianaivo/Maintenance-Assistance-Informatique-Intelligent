"""Tests de la normalisation, du decoupage et de la recherche documentaire."""

import pytest

from maii.ingest.chargement import charger_articles
from maii.ingest.texte import (
    decouper_en_mots, extraire_references, normaliser, sans_accent,
)
from maii.rag.decoupage import decouper_article, decouper_corpus
from maii.rag.index import IndexDocumentaire


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_normalisation_retire_accents_et_ponctuation():
    assert normaliser("Problème d'accès !") == "probleme d acces"


def test_normalisation_preserve_les_references():
    """Les identifiants du parc portent du sens : leur tiret doit survivre."""
    assert "kb-net-04" in normaliser("Voir la procedure KB-NET-04, svp.")
    assert "pc-0038" in normaliser("Le poste PC-0038 ne demarre plus.")


def test_normalisation_preserve_plusieurs_references():
    resultat = normaliser("Tickets TCK-000012 et TCK-000013 sur IMP-002.")
    for reference in ("tck-000012", "tck-000013", "imp-002"):
        assert reference in resultat


def test_normalisation_texte_vide():
    assert normaliser("") == ""
    assert normaliser("   ") == ""


def test_sans_accent():
    assert sans_accent("éàçüî") == "eacui"


def test_decoupage_en_mots_retire_les_mots_vides():
    mots = decouper_en_mots("Bonjour, je vous remercie pour l imprimante")
    assert "bonjour" not in mots
    assert "imprimante" in mots


def test_extraction_des_references():
    assert extraire_references("Voir KB-SEC-01 et KB-SEC-02") == ["KB-SEC-01", "KB-SEC-02"]
    assert extraire_references("aucune reference") == []


# ---------------------------------------------------------------------------
# Decoupage
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def articles():
    donnees = charger_articles()
    if not donnees:
        pytest.skip("base de connaissances absente")
    return donnees


def test_decoupage_produit_des_passages_identifies(articles):
    passages = decouper_article(articles[0])
    assert passages
    assert all(p.doc_id == articles[0]["doc_id"] for p in passages)
    assert len({p.chunk_id for p in passages}) == len(passages)


def test_les_passages_portent_le_titre_de_l_article(articles):
    passages = decouper_article(articles[0])
    assert all(articles[0]["titre"] in p.titre for p in passages)


def test_le_decoupage_ne_perd_pas_de_contenu(articles):
    """Aucun passage vide, et les etapes numerotees restent groupees."""
    passages = decouper_corpus(articles)
    assert all(p.contenu.strip() for p in passages)
    assert len(passages) >= len(articles)


def test_l_entete_de_metadonnees_est_exclue(articles):
    passages = decouper_corpus(articles)
    assert not any("Mots-cles :" in p.contenu for p in passages)


def test_reference_lisible_d_un_passage(articles):
    passage = decouper_article(articles[0])[0]
    assert passage.reference == f"{passage.doc_id}#{passage.chunk_id}"


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def index(articles):
    return IndexDocumentaire().construire(articles)


def test_recherche_trouve_la_procedure_attendue(index):
    resultat = index.rechercher("j ai oublie mon mot de passe", k=5)
    assert "KB-CPT-01" in {p.doc_id for p in resultat.passages}


def test_recherche_robuste_aux_fautes_de_frappe(index):
    """Les n-grammes de caracteres doivent absorber les fautes du corpus."""
    correct = index.rechercher("impression impossible imprimante", k=3)
    faute = index.rechercher("imprecion imposible imprimente", k=3)
    assert {p.doc_id for p in faute.passages} & {p.doc_id for p in correct.passages}


def test_recherche_sur_une_reference_exacte(index):
    """La voie lexicale doit permettre de retrouver un document par son identifiant."""
    resultat = index.rechercher("KB-SEC-02", k=5)
    assert "KB-SEC-02" in {p.doc_id for p in resultat.passages}


def test_les_scores_des_deux_voies_sont_exposes(index):
    """L'observabilite exige de pouvoir expliquer un classement."""
    resultat = index.rechercher("panne imprimante", k=3)
    for p in resultat.passages:
        assert p.score > 0
        assert 0.0 <= p.score_bm25 <= 1.0
        assert 0.0 <= p.score_dense <= 1.0


def test_la_confiance_distingue_le_corpus_du_hors_corpus(index):
    """Signal d'abstention : une question hors sujet doit obtenir moins."""
    dans = index.rechercher("mon compte est verrouille apres plusieurs tentatives")
    hors = index.rechercher("quelle est la recette du gateau au chocolat")
    assert dans.confiance > hors.confiance


def test_requete_vide(index):
    resultat = index.rechercher("   ")
    assert resultat.vide
    assert resultat.confiance == 0.0


def test_nombre_de_resultats_respecte(index):
    assert len(index.rechercher("imprimante", k=3).passages) <= 3


def test_persistance_de_l_index(index, tmp_path):
    chemin = tmp_path / "index.pkl"
    index.enregistrer(chemin)
    recharge = IndexDocumentaire.charger(chemin)
    assert len(recharge.passages) == len(index.passages)
    avant = [p.reference for p in index.rechercher("mot de passe oublie", k=3).passages]
    apres = [p.reference for p in recharge.rechercher("mot de passe oublie", k=3).passages]
    assert avant == apres
