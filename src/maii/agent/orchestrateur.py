"""Orchestrateur : machine a etats du traitement d'un ticket.

    ENTREE -> SECURITE -> CLASSIFICATION -> DIAGNOSTIC
           -> [QUESTIONS] -> RECHERCHE -> DECISION

Chaque transition emet un span d'observabilite. L'enchainement est deterministe
et lisible de bout en bout : une decision peut etre rejouee et expliquee ligne
a ligne, ce qui est indispensable pour la defendre.

Les garde-fous encadrent la chaine aux deux extremites : analyse de securite
avant tout traitement, verrouillage des actions sensibles apres la decision.
"""

from __future__ import annotations

import uuid

from maii.classify import arbitrage
from maii.classify.routage import sla_minutes
from maii.ingest.chargement import charger_incidents_actifs, index_utilisateurs
from maii.ingest.texte import extraire_references, tronquer
from maii.llm.provider import client
from maii.models.schemas import (
    Categorie, DecisionTicket, EntitesTicket, EtapeResolution, Ticket,
)
from maii.observability.tracer import Tracer
from maii.rag.index import index
from maii.security import garde_fous

# Champs juges indispensables pour poser un diagnostic fiable, par categorie.
CHAMPS_REQUIS = {
    Categorie.RESEAU: ["equipement", "moment_apparition", "impact_activite"],
    Categorie.MATERIEL: ["equipement", "symptomes"],
    Categorie.LOGICIELS: ["application_service", "symptomes"],
    Categorie.IMPRIMANTES: ["equipement"],
    Categorie.COMPTES: ["utilisateur"],
    Categorie.DROITS: ["utilisateur", "application_service"],
    Categorie.CYBERSECURITE: ["moment_apparition", "symptomes"],
    Categorie.INDETERMINE: ["symptomes", "equipement", "impact_activite"],
}

QUESTIONS = {
    "utilisateur": "Quel est l'identifiant du compte concerne ?",
    "equipement": "Quel est le numero du poste ou du peripherique concerne ?",
    "application_service": "Quelle application ou quel service est concerne ?",
    "symptomes": "Que se passe-t-il exactement, et quel message d'erreur s'affiche ?",
    "moment_apparition": "Depuis quand le probleme se produit-il ?",
    "impact_activite": "Combien de personnes sont touchees, et etes-vous bloque ?",
    "manipulations_effectuees": "Qu'avez-vous deja tente de votre cote ?",
}

# En deca, la recherche documentaire est jugee trop incertaine pour fonder une
# reponse : le systeme s'abstient plutot que d'inventer une procedure.
SEUIL_ABSTENTION_RAG = 0.30

MAX_ETAPES = 8


def _extraire_entites(texte: str) -> EntitesTicket:
    """Extraction par motifs : identifiants du parc, applications, symptomes.

    Volontairement deterministe. Les identifiants suivent un format connu, et
    les faire extraire par un modele generatif reviendrait a introduire du
    risque d'invention la ou une expression reguliere est exacte.
    """
    entites = EntitesTicket()
    minuscule = texte.lower()

    for reference in extraire_references(texte):
        if reference.startswith(("PC-", "IMP-", "SCN-")):
            entites.equipement = entites.equipement or reference
        elif reference.startswith("USR-"):
            entites.utilisateur = entites.utilisateur or reference

    for identifiant, utilisateur in index_utilisateurs().items():
        if identifiant and len(identifiant) > 5 and identifiant in minuscule:
            entites.utilisateur = entites.utilisateur or utilisateur["identifiant"]
            break

    for application in ("odoo", "sage", "outlook", "teams", "sharepoint",
                        "navision", "as400", "glpi", "erp", "messagerie"):
        if application in minuscule:
            entites.application_service = application
            break

    for marqueur, valeur in (
        ("ce matin", "ce matin"), ("hier", "hier"), ("depuis", "cite dans le ticket"),
        ("ce week-end", "ce week-end"), ("aujourd", "aujourd'hui"),
    ):
        if marqueur in minuscule:
            entites.moment_apparition = valeur
            break

    for marqueur in ("bloque", "arrete", "impossible de travailler", "plus personne",
                     "toute l equipe", "toute l'equipe"):
        if marqueur in minuscule:
            entites.impact_activite = "activite genee ou bloquee"
            break

    for marqueur in ("j ai deja", "j'ai deja", "deja essaye", "jai essaye",
                     "j ai rebranche", "deja change"):
        if marqueur in minuscule:
            entites.manipulations_effectuees = ["manipulations citees dans le ticket"]
            break

    if len(texte.split()) >= 5:
        entites.symptomes = [tronquer(texte, 160)]

    return entites


def _incident_correle(texte: str, categorie: Categorie) -> dict | None:
    """Rattache un ticket a un incident global en cours, s'il en existe un."""
    minuscule = texte.lower()
    for incident in charger_incidents_actifs():
        service = (incident.get("service_impacte") or "").lower()
        mots = [m for m in service.replace("-", " ").split() if len(m) > 3]
        if any(m in minuscule for m in mots):
            return incident
        if categorie is Categorie.CYBERSECURITE and incident["equipe"] == "securite":
            return incident
    return None


def traiter(ticket: Ticket) -> DecisionTicket:
    """Traite un ticket de bout en bout et produit une decision structuree."""
    tracer = Tracer.instance()
    trace_id = ticket.ticket_id or f"tk-{uuid.uuid4().hex[:8]}"

    with tracer.trace(trace_id) as trace:

        # --- 1. Securite, avant tout traitement ---------------------------
        with trace.span("securite", entree={"description": ticket.description}) as span:
            verdict = garde_fous.analyser(ticket.description)
            span.sortie = verdict

        texte = ticket.description

        # --- 2. Classification --------------------------------------------
        with trace.span("classification", entree={"texte": tronquer(texte)}) as span:
            # Le modele ne voit jamais les donnees personnelles en clair.
            classification = arbitrage.classer(verdict.texte_assaini)
            span.sortie = classification

        # --- 3. Diagnostic --------------------------------------------------
        with trace.span("diagnostic", entree={"texte": tronquer(texte)}) as span:
            entites = _extraire_entites(texte)
            requis = CHAMPS_REQUIS.get(classification.categorie, [])
            absents = [c for c in requis if c in entites.champs_absents()]
            incident = _incident_correle(texte, classification.categorie)
            span.sortie = {
                "entites": entites, "informations_manquantes": absents,
                "incident_correle": incident["incident_id"] if incident else None,
            }

        # --- 4. Blocage immediat si manipulation averee ---------------------
        if verdict.bloquer:
            return _decision_refus(ticket, classification, entites, verdict, trace_id)

        # --- 5. Recherche documentaire --------------------------------------
        with trace.span("recherche", entree={"requete": tronquer(texte)}) as span:
            recherche = index().rechercher(verdict.texte_assaini, k=5)
            span.sortie = {
                "confiance": recherche.confiance,
                "passages": [p.reference for p in recherche.passages],
            }

        fonde = recherche.confiance >= SEUIL_ABSTENTION_RAG and not recherche.vide

        # --- 6. Decision -----------------------------------------------------
        with trace.span("decision") as span:
            decision = _composer(
                ticket, classification, entites, absents, recherche, fonde,
                incident, verdict, trace_id,
            )
            span.sortie = decision

    return decision


def _decision_refus(ticket, classification, entites, verdict, trace_id) -> DecisionTicket:
    """Decision produite face a une tentative de manipulation (scenario 4)."""
    return DecisionTicket(
        categorie=Categorie.CYBERSECURITE,
        priorite="haute",
        equipe="securite",
        confiance=0.95,
        action="escalade",
        sources=["KB-SEC-03"],
        validation_humaine_requise=True,
        resume_probleme="Demande contenant une tentative de manipulation de l'assistant.",
        diagnostic=(
            "Le ticket contient des consignes visant a detourner le comportement "
            "de l'assistant ou a obtenir une action non autorisee. Aucune action "
            "n'a ete executee. Le contenu est transmis au service securite."
        ),
        etapes_resolution=[
            EtapeResolution(
                ordre=1,
                instruction="Verifier l'identite du demandeur par un canal distinct "
                            "de celui de la demande.",
                source="KB-SEC-03",
            ),
            EtapeResolution(
                ordre=2,
                instruction="Ne communiquer aucun identifiant ni mot de passe, "
                            "quel que soit le motif invoque.",
                source="KB-SEC-03",
            ),
        ],
        entites_extraites=entites,
        incertain=False,
        motif_securite=verdict.motif,
        risque_escalade=1.0,
        duree_estimee_resolution_min=60,
        trace_id=trace_id,
        mode_execution=client().mode,
    )


def _composer(ticket, classification, entites, absents, recherche, fonde,
              incident, verdict, trace_id) -> DecisionTicket:
    """Assemble la decision finale et applique le verrouillage des actions sensibles."""
    passages = recherche.passages if fonde else []
    sources = list(dict.fromkeys(p.doc_id for p in passages))

    # --- action ---
    # L'ordre de ces regles porte une decision metier. La securite et l'urgence
    # priment sur la completude du dossier : un incident critique s'escalade
    # meme si le ticket ne precise pas tout, et attendre une reponse de
    # l'utilisateur pendant qu'un service est a l'arret serait une faute.
    # La demande d'information n'intervient donc que sur les tickets non urgents.
    if classification.categorie in (Categorie.CYBERSECURITE, Categorie.DROITS):
        action = "escalade"
    elif classification.priorite in ("critique", "haute"):
        action = "escalade"
    elif absents and (
        classification.categorie is Categorie.INDETERMINE
        or classification.confiance < 0.75
    ):
        # Cas d'une demande trop vague : on questionne plutot que de deviner.
        action = "demande_information"
    elif not fonde:
        action = "escalade"
    else:
        action = "resolution"

    # --- etapes, uniquement si elles reposent sur une source ---
    etapes: list[EtapeResolution] = []
    for passage in passages[:3]:
        for ligne in passage.contenu.splitlines():
            ligne = ligne.strip()
            if ligne[:2].rstrip(".").isdigit() and len(ligne) > 12:
                etapes.append(EtapeResolution(
                    ordre=len(etapes) + 1,
                    instruction=ligne.lstrip("0123456789. ").strip(),
                    source=passage.reference,
                ))
            if len(etapes) >= MAX_ETAPES:
                break
        if len(etapes) >= MAX_ETAPES:
            break

    if incident:
        diagnostic = (
            f"Ticket rattache a l'incident global {incident['incident_id']} — "
            f"{incident['titre']}. Perimetre : {incident['perimetre']}. "
            "Aucun diagnostic individuel n'est engage tant que l'incident est ouvert."
        )
    elif not fonde:
        diagnostic = (
            "Aucune procedure suffisamment proche n'a ete trouvee dans la base de "
            "connaissances. Le dossier est transmis a un technicien plutot que de "
            "proposer une resolution non fondee."
        )
    elif absents:
        diagnostic = (
            "Les elements fournis ne permettent pas d'etablir un diagnostic fiable. "
            "Les informations manquantes sont demandees avant toute proposition."
        )
    else:
        diagnostic = (
            f"Incident rattache a la categorie « {classification.categorie.value} ». "
            f"Procedure applicable : {passages[0].titre}."
        )

    validation = garde_fous.validation_requise(
        classification.categorie, action, verdict
    )

    return DecisionTicket(
        categorie=classification.categorie,
        priorite=classification.priorite,
        equipe=classification.equipe,
        confiance=round(classification.confiance, 4),
        informations_manquantes=absents,
        action=action,
        sources=sources,
        validation_humaine_requise=validation,
        resume_probleme=tronquer(ticket.description, 200),
        diagnostic=diagnostic,
        etapes_resolution=etapes,
        entites_extraites=entites,
        questions_ciblees=[QUESTIONS[c] for c in absents if c in QUESTIONS][:4],
        incertain=not fonde,
        hors_distribution=classification.hors_distribution,
        risque_escalade=1.0 if action == "escalade" else 0.2,
        probabilite_depassement_sla=(
            0.7 if classification.priorite in ("critique", "haute") else 0.2
        ),
        duree_estimee_resolution_min=sla_minutes(classification.equipe),
        motif_securite=verdict.motif,
        trace_id=trace_id,
        mode_execution=client().mode,
    )
