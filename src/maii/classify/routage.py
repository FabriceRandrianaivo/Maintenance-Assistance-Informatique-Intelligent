"""Determination de la priorite et de l'equipe destinataire.

Aucun modele n'intervient ici. Le routage est une regle metier : il doit etre
auditable, modifiable sans reapprentissage, et rendre exactement la meme
decision pour deux tickets identiques. Les modeles proposent une priorite,
cette couche l'arbitre et la corrige a partir du contexte.
"""

from __future__ import annotations

from maii.classify.regles import score_urgence
from maii.ingest.chargement import index_services
from maii.models.schemas import Categorie

PRIORITES = ["basse", "moyenne", "haute", "critique"]

# Equipe par defaut de chaque categorie.
ROUTAGE = {
    Categorie.COMPTES: "support_n1",
    Categorie.RESEAU: "infrastructure",
    Categorie.MATERIEL: "logistique_it",
    Categorie.LOGICIELS: "support_n2",
    Categorie.IMPRIMANTES: "support_n1",
    Categorie.DROITS: "securite",
    Categorie.CYBERSECURITE: "securite",
    Categorie.INDETERMINE: "support_n1",
}

# Une priorite elevee change le destinataire : un incident critique ne part pas
# au niveau 1, quelle que soit sa categorie.
ESCALADE_PAR_PRIORITE = {
    Categorie.COMPTES: {"critique": "securite", "haute": "support_n2"},
    Categorie.RESEAU: {"critique": "infrastructure"},
    Categorie.MATERIEL: {"critique": "support_n2", "haute": "support_n2"},
    Categorie.LOGICIELS: {"critique": "applications", "haute": "applications"},
    Categorie.IMPRIMANTES: {"critique": "support_n2", "haute": "support_n2"},
    Categorie.INDETERMINE: {"critique": "support_n2", "haute": "support_n2"},
}

# Priorite plancher par categorie : un incident de securite n'est jamais traite
# en priorite basse, meme si sa formulation parait anodine.
PLANCHER = {
    Categorie.CYBERSECURITE: "haute",
    Categorie.DROITS: "moyenne",
}


def _rang(priorite: str) -> int:
    return PRIORITES.index(priorite) if priorite in PRIORITES else 1


def equipe_pour(categorie: Categorie, priorite: str) -> str:
    """Equipe destinataire d'un ticket."""
    surcharge = ESCALADE_PAR_PRIORITE.get(categorie, {}).get(priorite)
    return surcharge or ROUTAGE.get(categorie, "support_n1")


def sla_minutes(equipe: str) -> int:
    """Delai de prise en charge contractuel de l'equipe destinataire."""
    service = index_services().get(equipe)
    return service["sla_minutes"] if service else 480


def priorite_ajustee(
    categorie: Categorie,
    texte: str,
    proposition_ml: str | None = None,
    proposition_llm: str | None = None,
    contexte: dict | None = None,
) -> str:
    """Arbitre la priorite entre propositions des modeles, indices et contexte.

    On retient la plus elevee des propositions plutot que leur moyenne : sous-
    estimer l'urgence d'un incident coute plus cher que de la surestimer.
    """
    contexte = contexte or {}
    candidats = [p for p in (proposition_ml, proposition_llm) if p in PRIORITES]
    priorite = max(candidats, key=_rang) if candidats else "moyenne"

    # Marqueurs d'urgence releves dans le texte.
    urgence = score_urgence(texte)
    if urgence >= 4.0:
        priorite = max(priorite, "critique", key=_rang)
    elif urgence >= 2.0:
        priorite = max(priorite, "haute", key=_rang)

    # Contexte collecte par les outils de consultation.
    if contexte.get("incident_global"):
        # Un ticket rattache a un incident global herite de sa gravite : le
        # perimetre reel depasse la demande individuelle.
        priorite = max(priorite, "haute", key=_rang)
    if contexte.get("utilisateur_vip"):
        priorite = max(priorite, "haute", key=_rang)
    if int(contexte.get("utilisateurs_impactes") or 0) >= 5:
        priorite = max(priorite, "critique", key=_rang)

    plancher = PLANCHER.get(categorie)
    if plancher:
        priorite = max(priorite, plancher, key=_rang)

    return priorite
