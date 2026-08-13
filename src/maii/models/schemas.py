"""Contrats de donnees du systeme.

Source de verite unique : toute frontiere entre deux composants passe par un
modele defini ici. Les noms de champs de `DecisionTicket` imposes par le sujet
sont conserves a l'identique et ne doivent jamais etre renommes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Enumerations metier
# --------------------------------------------------------------------------


class Categorie(str, Enum):
    """Les huit categories d'incident definies par le sujet (section 3.1)."""

    COMPTES = "comptes_authentification"
    RESEAU = "reseau_connectivite"
    MATERIEL = "materiel_informatique"
    LOGICIELS = "logiciels_applications"
    IMPRIMANTES = "imprimantes_peripheriques"
    DROITS = "droits_acces"
    CYBERSECURITE = "cybersecurite"
    INDETERMINE = "autre_indetermine"


Priorite = Literal["critique", "haute", "moyenne", "basse"]
ActionFinale = Literal["resolution", "demande_information", "escalade"]
StatutAppel = Literal["succes", "erreur", "refuse", "en_attente_validation"]


# --------------------------------------------------------------------------
# Entree
# --------------------------------------------------------------------------


class Ticket(BaseModel):
    """Un ticket tel qu'il entre dans le systeme."""

    ticket_id: str
    description: str
    auteur: str | None = None
    date_soumission: datetime | None = None
    canal: str | None = None
    # Etiquettes de reference, presentes uniquement dans les jeux d'evaluation.
    categorie_reelle: Categorie | None = None
    priorite_reelle: Priorite | None = None


# --------------------------------------------------------------------------
# Diagnostic (section 3.2)
# --------------------------------------------------------------------------


class EntitesTicket(BaseModel):
    """Les sept informations utiles que l'assistant doit tenter d'extraire."""

    utilisateur: str | None = None
    equipement: str | None = None
    application_service: str | None = None
    symptomes: list[str] = Field(default_factory=list)
    moment_apparition: str | None = None
    impact_activite: str | None = None
    manipulations_effectuees: list[str] = Field(default_factory=list)

    def champs_absents(self) -> list[str]:
        """Liste les champs non renseignes, pour piloter les questions ciblees."""
        absents = []
        for nom, valeur in self.model_dump().items():
            if valeur is None or (isinstance(valeur, list) and not valeur):
                absents.append(nom)
        return absents


# --------------------------------------------------------------------------
# Recherche documentaire (section 3.3)
# --------------------------------------------------------------------------


class PassageSource(BaseModel):
    """Un passage de la base de connaissances retenu par la recherche."""

    doc_id: str
    chunk_id: str
    titre: str
    contenu: str
    score: float
    score_bm25: float = 0.0
    score_dense: float = 0.0

    @property
    def reference(self) -> str:
        """Identifiant cite dans la reponse, par exemple `KB-NET-04#c2`."""
        return f"{self.doc_id}#{self.chunk_id}"


# --------------------------------------------------------------------------
# Outils (section 3.4)
# --------------------------------------------------------------------------


class AppelOutil(BaseModel):
    """Trace d'un appel d'outil : parametres, resultat et statut (section 3.4)."""

    nom: str
    parametres: dict[str, Any] = Field(default_factory=dict)
    resultat: Any = None
    statut: StatutAppel = "succes"
    erreur: str | None = None
    latence_ms: int = 0
    justification: str | None = None
    sensible: bool = False


# --------------------------------------------------------------------------
# Sortie structuree (section 3.5 et 5.3)
# --------------------------------------------------------------------------


class EtapeResolution(BaseModel):
    ordre: int
    instruction: str
    source: str | None = None


class DecisionTicket(BaseModel):
    """Decision finale produite pour un ticket.

    Les huit premiers champs reprennent exactement le schema impose par la
    section 5.3 du sujet. Les suivants couvrent les elements demandes par les
    sections 3.1, 3.2 et 3.5.
    """

    # --- schema impose, noms conserves a l'identique ---
    categorie: Categorie
    priorite: Priorite
    equipe: str
    confiance: float = Field(ge=0.0, le=1.0)
    informations_manquantes: list[str] = Field(default_factory=list)
    action: ActionFinale
    sources: list[str] = Field(default_factory=list)
    validation_humaine_requise: bool = False

    # --- section 3.5 : contenu de la reponse ---
    resume_probleme: str = ""
    diagnostic: str = ""
    etapes_resolution: list[EtapeResolution] = Field(default_factory=list)
    outils_utilises: list[AppelOutil] = Field(default_factory=list)

    # --- section 3.2 : diagnostic ---
    entites_extraites: EntitesTicket = Field(default_factory=EntitesTicket)
    questions_ciblees: list[str] = Field(default_factory=list)

    # --- section 3.1 : analyses complementaires ---
    incertain: bool = False
    hors_distribution: bool = False
    risque_escalade: float = Field(default=0.0, ge=0.0, le=1.0)
    probabilite_depassement_sla: float = Field(default=0.0, ge=0.0, le=1.0)
    duree_estimee_resolution_min: int = 0

    # --- section 6 : securite ---
    motif_securite: str | None = None

    # --- observabilite ---
    trace_id: str = ""
    mode_execution: str = ""  # provider LLM effectif, ou "regles_seules"


# --------------------------------------------------------------------------
# Classification (section 3.1)
# --------------------------------------------------------------------------


class ResultatVoie(BaseModel):
    """Sortie d'une des trois voies de classification, avant arbitrage."""

    voie: Literal["regles", "ml", "llm"]
    categorie: Categorie | None = None
    distribution: dict[str, float] = Field(default_factory=dict)
    priorite: Priorite | None = None
    confiance: float = 0.0
    disponible: bool = True
    motif_indisponibilite: str | None = None


class ResultatClassification(BaseModel):
    """Decision de classification apres arbitrage des trois voies."""

    categorie: Categorie
    priorite: Priorite
    equipe: str
    confiance: float
    distribution: dict[str, float] = Field(default_factory=dict)
    voies: list[ResultatVoie] = Field(default_factory=list)
    desaccord: bool = False
    abstention: bool = False
    hors_distribution: bool = False


# --------------------------------------------------------------------------
# Securite (section 6)
# --------------------------------------------------------------------------


class VerdictSecurite(BaseModel):
    """Resultat de l'analyse de securite d'un texte entrant."""

    injection_detectee: bool = False
    patterns_detectes: list[str] = Field(default_factory=list)
    score_risque: float = Field(default=0.0, ge=0.0, le=1.0)
    pii_detectees: list[str] = Field(default_factory=list)
    texte_assaini: str = ""
    bloquer: bool = False
    motif: str | None = None


# --------------------------------------------------------------------------
# Observabilite (section 5.4)
# --------------------------------------------------------------------------


class Span(BaseModel):
    """Unite elementaire de trace : une etape du traitement d'un ticket."""

    trace_id: str
    span_id: str
    nom: str
    parent: str | None = None
    entree: Any = None
    sortie: Any = None
    latence_ms: int = 0
    tokens_entree: int = 0
    tokens_sortie: int = 0
    cout_usd: float = 0.0
    statut: Literal["ok", "erreur"] = "ok"
    erreur: str | None = None
    horodatage: str = ""
