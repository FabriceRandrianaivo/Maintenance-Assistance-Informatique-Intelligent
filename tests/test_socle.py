"""Tests de fumee du socle : contrats, tracage et acces aux modeles."""

from maii.llm.provider import client, extraire_json
from maii.models.schemas import Categorie, DecisionTicket, EntitesTicket
from maii.observability.tracer import Tracer


def test_decision_respecte_le_schema_impose():
    d = DecisionTicket(
        categorie=Categorie.IMPRIMANTES,
        priorite="moyenne",
        equipe="support_n1",
        confiance=0.82,
        action="resolution",
        sources=["KB-IMP-02"],
    )
    impose = {
        "categorie", "priorite", "equipe", "confiance", "informations_manquantes",
        "action", "sources", "validation_humaine_requise",
    }
    assert impose <= set(d.model_dump().keys())
    assert d.categorie.value == "imprimantes_peripheriques"


def test_confiance_bornee():
    import pytest

    with pytest.raises(Exception):
        DecisionTicket(
            categorie=Categorie.RESEAU, priorite="haute", equipe="infra",
            confiance=1.5, action="escalade",
        )


def test_entites_detecte_les_champs_absents():
    e = EntitesTicket(utilisateur="rakoto", symptomes=["lenteur"])
    absents = e.champs_absents()
    assert "equipement" in absents
    assert "utilisateur" not in absents
    assert "symptomes" not in absents


def test_tracage_produit_des_spans_horodates():
    t = Tracer.instance()
    with t.trace("tk-test-socle") as tr:
        with tr.span("classification", entree={"texte": "imprimante en panne"}) as s:
            s.sortie = {"categorie": "imprimantes_peripheriques"}
            s.tokens_entree = 120
        with tr.span("rag", entree={"q": "imprimante"}) as s:
            s.sortie = ["KB-IMP-02#c1"]

    spans = t.spans_de("tk-test-socle")
    assert {s["nom"] for s in spans} == {"classification", "rag"}
    assert all(s["horodatage"] for s in spans)
    assert all(s["statut"] == "ok" for s in spans)


def test_tracage_capture_les_erreurs_sans_les_avaler():
    import pytest

    t = Tracer.instance()
    with pytest.raises(ValueError):
        with t.trace("tk-test-erreur") as tr:
            with tr.span("etape_qui_echoue"):
                raise ValueError("panne simulee")

    span = t.spans_de("tk-test-erreur")[0]
    assert span["statut"] == "erreur"
    assert "panne simulee" in span["erreur"]


def test_extraction_json_tolerante():
    assert extraire_json('{"a": 1}') == {"a": 1}
    assert extraire_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extraire_json('Voici le resultat : {"a": 1} voila.') == {"a": 1}
    assert extraire_json("aucun json ici") is None


def test_client_llm_expose_toujours_un_mode():
    c = client()
    assert c.mode
    assert len(c.diagnostic()) == 3
