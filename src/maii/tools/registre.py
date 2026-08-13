"""Registre des outils accessibles a l'agent (section 3.4 du sujet).

Quatre outils de consultation et quatre outils d'action, adosses aux
referentiels du projet.

Trois principes gouvernent ce registre :

  - **Les parametres sont valides avant execution.** Chaque outil declare un
    modele Pydantic ; un argument invalide n'atteint jamais le backend et
    produit une erreur exploitable, reinjectable au modele.

  - **Les actions sensibles ne s'executent pas seules.** Elles sont refusees
    tant qu'une validation humaine n'a pas ete accordee, et ce refus est
    prononce par le registre, pas par une consigne de prompt.

  - **Tout appel est trace.** Nom, parametres, resultat, statut, latence et
    justification, conformement a l'exigence de la section 3.4.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from maii.ingest.chargement import (
    charger_incidents_actifs, index_equipements, index_services,
    index_utilisateurs,
)
from maii.models.schemas import AppelOutil

# Plafond d'appels par ticket : un agent qui boucle est un agent hors controle.
MAX_APPELS = 8


# ---------------------------------------------------------------------------
# Schemas de parametres
# ---------------------------------------------------------------------------


class ParamsRechercherUtilisateur(BaseModel):
    identifiant: str = Field(min_length=2, description="identifiant, courriel ou USR-xxxx")


class ParamsConsulterEquipement(BaseModel):
    equipement_id: str = Field(min_length=3, description="par exemple PC-0012 ou IMP-003")


class ParamsVerifierEtatService(BaseModel):
    service: str = Field(min_length=2, description="nom du service ou de l'application")


class ParamsRechercherIncidents(BaseModel):
    perimetre: str | None = Field(default=None, description="site ou service, facultatif")


class ParamsCreerTicket(BaseModel):
    description: str = Field(min_length=5)
    categorie: str
    priorite: str
    equipe: str


class ParamsMettreAJourTicket(BaseModel):
    ticket_id: str = Field(min_length=3)
    statut: str | None = None
    commentaire: str | None = None


class ParamsAffecterTicket(BaseModel):
    ticket_id: str = Field(min_length=3)
    equipe: str = Field(min_length=2)


class ParamsEscalader(BaseModel):
    ticket_id: str = Field(min_length=3)
    equipe: str = Field(min_length=2)
    motif: str = Field(min_length=5)


# ---------------------------------------------------------------------------
# Base ITSM simulee
# ---------------------------------------------------------------------------

# Tickets crees pendant la session. Volontairement en memoire : la
# demonstration doit pouvoir etre rejouee depuis un etat propre.
_TICKETS: dict[str, dict] = {}


def _rechercher_utilisateur(p: ParamsRechercherUtilisateur) -> dict:
    utilisateur = index_utilisateurs().get(p.identifiant.strip().lower())
    if not utilisateur:
        raise LookupError(f"aucun utilisateur pour l'identifiant {p.identifiant!r}")
    # Le telephone n'est pas remonte : il n'est pas necessaire au diagnostic.
    return {c: v for c, v in utilisateur.items() if c != "telephone"}


def _consulter_equipement(p: ParamsConsulterEquipement) -> dict:
    equipement = index_equipements().get(p.equipement_id.strip().lower())
    if not equipement:
        raise LookupError(f"equipement {p.equipement_id!r} absent de l'inventaire")
    return equipement


def _verifier_etat_service(p: ParamsVerifierEtatService) -> dict:
    recherche = p.service.strip().lower()
    for incident in charger_incidents_actifs():
        if recherche in (incident.get("service_impacte") or "").lower():
            return {
                "service": incident["service_impacte"], "etat": "degrade",
                "incident_id": incident["incident_id"], "severite": incident["severite"],
                "perimetre": incident["perimetre"], "depuis": incident["debut"],
            }
    return {"service": p.service, "etat": "operationnel", "incident_id": None}


def _rechercher_incidents_actifs(p: ParamsRechercherIncidents) -> list[dict]:
    incidents = charger_incidents_actifs()
    if p.perimetre:
        recherche = p.perimetre.strip().lower()
        incidents = [
            i for i in incidents
            if recherche in i["perimetre"].lower()
            or recherche in i["service_impacte"].lower()
        ]
    return [
        {c: i[c] for c in ("incident_id", "titre", "severite", "perimetre", "equipe")}
        for i in incidents
    ]


def _creer_ticket(p: ParamsCreerTicket) -> dict:
    ticket_id = f"TCK-{uuid.uuid4().hex[:6].upper()}"
    _TICKETS[ticket_id] = {
        "ticket_id": ticket_id, "description": p.description,
        "categorie": p.categorie, "priorite": p.priorite, "equipe": p.equipe,
        "statut": "ouvert", "journal": [],
    }
    return _TICKETS[ticket_id]


def _mettre_a_jour_ticket(p: ParamsMettreAJourTicket) -> dict:
    ticket = _TICKETS.get(p.ticket_id)
    if not ticket:
        raise LookupError(f"ticket {p.ticket_id!r} introuvable")
    if p.statut:
        ticket["statut"] = p.statut
    if p.commentaire:
        ticket["journal"].append(p.commentaire)
    return ticket


def _affecter_ticket(p: ParamsAffecterTicket) -> dict:
    ticket = _TICKETS.get(p.ticket_id)
    if not ticket:
        raise LookupError(f"ticket {p.ticket_id!r} introuvable")
    if p.equipe not in index_services():
        raise ValueError(f"equipe {p.equipe!r} inconnue du referentiel des services")
    ticket["equipe"] = p.equipe
    ticket["statut"] = "affecte"
    return ticket


def _escalader(p: ParamsEscalader) -> dict:
    ticket = _TICKETS.get(p.ticket_id)
    if not ticket:
        raise LookupError(f"ticket {p.ticket_id!r} introuvable")
    service = index_services().get(p.equipe)
    ticket.update({"statut": "escalade", "equipe": p.equipe, "motif_escalade": p.motif})
    return {**ticket, "sla_minutes": service["sla_minutes"] if service else None}


# ---------------------------------------------------------------------------
# Registre
# ---------------------------------------------------------------------------


@dataclass
class SpecificationOutil:
    nom: str
    description: str
    parametres: type[BaseModel]
    fonction: Callable[[Any], Any]
    type_outil: str          # "consultation" ou "action"
    sensible: bool = False   # exige une validation humaine
    idempotent: bool = True

    def schema_json(self) -> dict:
        return self.parametres.model_json_schema()


REGISTRE: dict[str, SpecificationOutil] = {
    o.nom: o for o in [
        SpecificationOutil(
            "rechercher_utilisateur",
            "Retrouve un utilisateur dans l'annuaire a partir de son identifiant.",
            ParamsRechercherUtilisateur, _rechercher_utilisateur, "consultation",
        ),
        SpecificationOutil(
            "consulter_equipement",
            "Consulte la fiche d'inventaire d'un poste ou d'un peripherique.",
            ParamsConsulterEquipement, _consulter_equipement, "consultation",
        ),
        SpecificationOutil(
            "verifier_etat_service",
            "Indique si un service est operationnel ou degrade.",
            ParamsVerifierEtatService, _verifier_etat_service, "consultation",
        ),
        SpecificationOutil(
            "rechercher_incidents_actifs",
            "Liste les incidents globaux en cours, filtres par perimetre.",
            ParamsRechercherIncidents, _rechercher_incidents_actifs, "consultation",
        ),
        SpecificationOutil(
            "creer_ticket", "Cree un ticket dans l'outil de gestion.",
            ParamsCreerTicket, _creer_ticket, "action", idempotent=False,
        ),
        SpecificationOutil(
            "mettre_a_jour_ticket", "Met a jour le statut ou le journal d'un ticket.",
            ParamsMettreAJourTicket, _mettre_a_jour_ticket, "action",
        ),
        SpecificationOutil(
            "affecter_ticket", "Affecte un ticket a une equipe.",
            ParamsAffecterTicket, _affecter_ticket, "action",
        ),
        SpecificationOutil(
            "escalader_vers_technicien",
            "Transmet un ticket a un technicien avec le motif d'escalade.",
            ParamsEscalader, _escalader, "action", sensible=True, idempotent=False,
        ),
    ]
}


@dataclass
class SessionOutils:
    """Suit les appels d'un ticket : plafond, journal et demandes d'approbation."""

    appels: list[AppelOutil] = field(default_factory=list)
    en_attente: list[AppelOutil] = field(default_factory=list)
    approbations: set[str] = field(default_factory=set)

    @property
    def budget_epuise(self) -> bool:
        return len(self.appels) >= MAX_APPELS

    def approuver(self, nom: str) -> None:
        """Enregistre une validation humaine pour un outil donne."""
        self.approbations.add(nom)


def catalogue() -> list[dict]:
    """Description des outils, telle qu'elle serait presentee a un modele."""
    return [
        {"nom": o.nom, "description": o.description, "type": o.type_outil,
         "sensible": o.sensible, "parametres": o.schema_json()}
        for o in REGISTRE.values()
    ]


def executer(
    nom: str,
    parametres: dict[str, Any],
    session: SessionOutils,
    justification: str | None = None,
) -> AppelOutil:
    """Execute un outil apres validation, et journalise l'appel.

    Ne leve jamais : toute erreur est convertie en appel au statut `erreur`,
    dont le message est exploitable par l'agent pour se corriger.
    """
    debut = time.perf_counter()

    def terminer(appel: AppelOutil) -> AppelOutil:
        appel.latence_ms = int((time.perf_counter() - debut) * 1000)
        session.appels.append(appel)
        return appel

    specification = REGISTRE.get(nom)
    if specification is None:
        return terminer(AppelOutil(
            nom=nom, parametres=parametres, statut="erreur",
            erreur=f"outil inconnu : {nom!r}", justification=justification,
        ))

    if session.budget_epuise:
        return terminer(AppelOutil(
            nom=nom, parametres=parametres, statut="refuse",
            erreur=f"plafond de {MAX_APPELS} appels atteint pour ce ticket",
            justification=justification, sensible=specification.sensible,
        ))

    # Validation des parametres avant toute execution.
    try:
        valides = specification.parametres(**parametres)
    except ValidationError as erreur:
        details = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in erreur.errors()
        )
        return terminer(AppelOutil(
            nom=nom, parametres=parametres, statut="erreur",
            erreur=f"parametres invalides — {details}",
            justification=justification, sensible=specification.sensible,
        ))

    # Verrou des actions sensibles : refus tant que la validation humaine
    # n'a pas ete accordee. Prononce ici, hors de portee du modele.
    if specification.sensible and nom not in session.approbations:
        appel = AppelOutil(
            nom=nom, parametres=valides.model_dump(),
            statut="en_attente_validation",
            erreur="operation sensible : validation humaine requise",
            justification=justification, sensible=True,
        )
        session.en_attente.append(appel)
        return terminer(appel)

    try:
        resultat = specification.fonction(valides)
    except (LookupError, ValueError) as erreur:
        return terminer(AppelOutil(
            nom=nom, parametres=valides.model_dump(), statut="erreur",
            erreur=str(erreur), justification=justification,
            sensible=specification.sensible,
        ))

    return terminer(AppelOutil(
        nom=nom, parametres=valides.model_dump(), resultat=resultat,
        statut="succes", justification=justification,
        sensible=specification.sensible,
    ))
