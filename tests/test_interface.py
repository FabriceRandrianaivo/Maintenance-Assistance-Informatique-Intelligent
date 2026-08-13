"""Tests d'execution de l'interface.

Une erreur de rendu ne se voit pas a la compilation : elle survient lorsque le
composant recoit ses donnees. Ces tests executent reellement l'application via
le harnais officiel de Streamlit et echouent sur toute exception levee.

Ils ont ete ajoutes apres qu'un graphe mal alimente soit passe au travers d'une
verification manuelle : la page se chargeait, et seul l'onglet concerne cassait.
"""

import pytest

pytest.importorskip("streamlit")

from pathlib import Path  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
APPLICATION = RACINE / "ui" / "app.py"


@pytest.fixture(scope="module")
def application() -> AppTest:
    if not APPLICATION.exists():
        pytest.skip("interface absente")
    at = AppTest.from_file(str(APPLICATION), default_timeout=180)
    at.run()
    return at


def test_l_interface_demarre_sans_exception(application):
    assert not application.exception, [str(e) for e in application.exception]


def test_les_quatre_onglets_sont_presents(application):
    intitules = [o.label for o in application.tabs]
    assert "Traitement d'un ticket" in intitules
    assert "Observabilite" in intitules
    assert "Base de connaissances" in intitules
    assert "Evaluation" in intitules


def test_les_quatre_scenarios_sont_proposes(application):
    options = application.selectbox[0].options
    for attendu in ("1. Incident courant", "2. Incident urgent",
                    "3. Demande incomplete", "4. Demande malveillante"):
        assert any(attendu in o for o in options), f"{attendu} absent du menu"


def test_le_traitement_d_un_ticket_rend_sans_exception():
    """Le chemin critique : soumettre un ticket et afficher la decision.

    C'est ce parcours qui alimente le verdict, les sources, les appels d'outils
    et le graphe de latence — donc celui ou une erreur de rendu se manifeste.
    """
    at = AppTest.from_file(str(APPLICATION), default_timeout=300)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    at.text_area[0].set_value(
        "Je n arrive plus a imprimer sur l imprimante IMP-002 depuis ce matin."
    )
    at.button[0].click().run()

    assert not at.exception, [str(e) for e in at.exception]
    # La decision doit etre affichee : au moins les quatre indicateurs de tete.
    assert len(at.metric) >= 4


def test_l_onglet_observabilite_rend_le_graphe_de_latence():
    """Regression : un graphe alimente par un dictionnaire de scalaires echouait."""
    at = AppTest.from_file(str(APPLICATION), default_timeout=300)
    at.run()
    at.text_area[0].set_value("mon compte est verrouille")
    at.button[0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
