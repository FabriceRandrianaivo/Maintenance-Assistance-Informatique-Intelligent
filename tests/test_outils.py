"""Tests du registre d'outils (sections 3.4 et 5.2 du sujet)."""

import pytest

from maii.tools.registre import (
    MAX_APPELS, REGISTRE, SessionOutils, catalogue, executer,
)


@pytest.fixture
def session():
    return SessionOutils()


def test_les_huit_outils_du_sujet_sont_declares():
    consultation = {n for n, o in REGISTRE.items() if o.type_outil == "consultation"}
    action = {n for n, o in REGISTRE.items() if o.type_outil == "action"}
    assert consultation == {
        "rechercher_utilisateur", "consulter_equipement",
        "verifier_etat_service", "rechercher_incidents_actifs",
    }
    assert action == {
        "creer_ticket", "mettre_a_jour_ticket",
        "affecter_ticket", "escalader_vers_technicien",
    }


def test_chaque_outil_publie_le_schema_de_ses_parametres():
    for entree in catalogue():
        assert entree["parametres"]["type"] == "object"
        assert "properties" in entree["parametres"]


def test_appel_valide_reussit_et_est_journalise(session):
    appel = executer("rechercher_incidents_actifs", {}, session)
    assert appel.statut == "succes"
    assert isinstance(appel.resultat, list)
    assert session.appels == [appel]


def test_parametres_invalides_refuses_avant_execution(session):
    """Section 5.2 : validation des parametres."""
    appel = executer("consulter_equipement", {"equipement_id": "x"}, session)
    assert appel.statut == "erreur"
    assert "parametres invalides" in appel.erreur
    assert appel.resultat is None


def test_parametre_absent_refuse(session):
    appel = executer("rechercher_utilisateur", {}, session)
    assert appel.statut == "erreur"
    assert "identifiant" in appel.erreur


def test_outil_inconnu_ne_leve_pas(session):
    appel = executer("supprimer_toute_la_base", {}, session)
    assert appel.statut == "erreur"
    assert "inconnu" in appel.erreur


def test_erreur_metier_convertie_en_statut(session):
    """Section 5.2 : gestion des erreurs d'appel, sans interruption du traitement."""
    appel = executer("consulter_equipement", {"equipement_id": "PC-9999"}, session)
    assert appel.statut == "erreur"
    assert "absent de l'inventaire" in appel.erreur


def test_action_sensible_bloquee_sans_validation(session):
    """Section 6 : validation humaine sur les operations sensibles."""
    creation = executer(
        "creer_ticket",
        {"description": "poste hors service", "categorie": "materiel_informatique",
         "priorite": "haute", "equipe": "support_n2"},
        session,
    )
    identifiant = creation.resultat["ticket_id"]

    appel = executer(
        "escalader_vers_technicien",
        {"ticket_id": identifiant, "equipe": "support_n2", "motif": "panne materielle"},
        session,
    )
    assert appel.statut == "en_attente_validation"
    assert appel.sensible
    assert session.en_attente == [appel]


def test_action_sensible_executee_apres_validation(session):
    creation = executer(
        "creer_ticket",
        {"description": "poste hors service", "categorie": "materiel_informatique",
         "priorite": "haute", "equipe": "support_n2"},
        session,
    )
    identifiant = creation.resultat["ticket_id"]

    session.approuver("escalader_vers_technicien")
    appel = executer(
        "escalader_vers_technicien",
        {"ticket_id": identifiant, "equipe": "support_n2", "motif": "panne materielle"},
        session,
    )
    assert appel.statut == "succes"
    assert appel.resultat["statut"] == "escalade"


def test_plafond_d_appels_respecte(session):
    """Section 5.2 : controle du nombre d'actions."""
    for _ in range(MAX_APPELS + 3):
        appel = executer("rechercher_incidents_actifs", {}, session)
    assert appel.statut == "refuse"
    assert "plafond" in appel.erreur


def test_equipe_inconnue_refusee(session):
    creation = executer(
        "creer_ticket",
        {"description": "perte de connexion", "categorie": "reseau_connectivite",
         "priorite": "moyenne", "equipe": "infrastructure"},
        session,
    )
    appel = executer(
        "affecter_ticket",
        {"ticket_id": creation.resultat["ticket_id"], "equipe": "equipe_fantome"},
        session,
    )
    assert appel.statut == "erreur"
    assert "inconnue du referentiel" in appel.erreur


def test_le_telephone_n_est_pas_remonte(session):
    """Minimisation : le diagnostic n'a pas besoin des coordonnees personnelles."""
    from maii.ingest.chargement import charger_utilisateurs

    utilisateur = charger_utilisateurs()[0]
    appel = executer(
        "rechercher_utilisateur", {"identifiant": utilisateur["identifiant"]}, session
    )
    assert appel.statut == "succes"
    assert "telephone" not in appel.resultat
