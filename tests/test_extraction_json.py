"""Tests de l'extraction JSON des reponses de modeles.

Les cas couverts proviennent d'observations reelles faites sur les providers
utilises : bloc de code, texte d'accompagnement, encapsulation dans un tableau
et troncature en cours d'ecriture.
"""

from maii.llm.provider import extraire_json, reparer_json_tronque


def test_json_direct():
    assert extraire_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_bloc_de_code_balise():
    assert extraire_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extraire_json('```\n{"a": 1}\n```') == {"a": 1}


def test_json_entoure_de_texte():
    assert extraire_json('Voici le resultat :\n{"a": 1}\nVoila.') == {"a": 1}


def test_objet_encapsule_dans_un_tableau():
    assert extraire_json('[{"a": 1}]') == {"a": 1}


def test_accolade_dans_une_chaine_ne_perturbe_pas_le_comptage():
    assert extraire_json('{"a": "valeur } piegeuse", "b": 2}') == {
        "a": "valeur } piegeuse", "b": 2
    }


def test_troncature_apres_une_valeur_complete():
    """Cas observe sur un modele atteignant sa limite de sortie."""
    tronque = '{\n  "categorie": "comptes_authentification",\n  "priorite": "haute"'
    assert extraire_json(tronque) == {
        "categorie": "comptes_authentification", "priorite": "haute"
    }


def test_troncature_au_milieu_d_une_chaine():
    tronque = '{"categorie": "reseau_connectivite", "resume": "perte de connexion sur le'
    resultat = extraire_json(tronque)
    assert resultat is not None
    assert resultat["categorie"] == "reseau_connectivite"


def test_troncature_sur_une_cle_sans_valeur():
    tronque = '{"categorie": "cybersecurite", "priorite":'
    assert extraire_json(tronque) == {"categorie": "cybersecurite"}


def test_troncature_dans_un_tableau_imbrique():
    tronque = '{"sources": ["KB-NET-04", "KB-NET-02"'
    resultat = extraire_json(tronque)
    assert resultat is not None
    assert resultat["sources"] == ["KB-NET-04", "KB-NET-02"]


def test_troncature_avec_virgule_finale():
    assert extraire_json('{"a": 1,') == {"a": 1}


def test_reparation_equilibre_les_delimiteurs():
    assert reparer_json_tronque('{"a": [1, 2').endswith("]}")


def test_absence_de_json():
    assert extraire_json("aucun objet ici") is None
    assert extraire_json("") is None
    assert extraire_json("   ") is None
