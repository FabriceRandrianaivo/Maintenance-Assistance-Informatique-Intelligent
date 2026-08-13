"""Voie A : classification par regles.

Instantanee, entierement explicable et sans apprentissage. Elle ne remplace pas
les deux autres voies mais remplit trois roles qu'elles assurent mal :

  - elle ne rate jamais les formulations canoniques (« mot de passe oublie ») ;
  - elle reste disponible quand le modele de langage et le modele appris ne le
    sont pas, ce qui garantit un service degrade mais fonctionnel ;
  - elle porte les regles de securite, qui ne doivent dependre ni d'un
    apprentissage sur donnees bruitees ni d'un modele generatif faillible.

Chaque indice est pondere : un terme sans ambiguite pese davantage qu'un terme
partage par plusieurs categories.
"""

from __future__ import annotations

import re

from maii.ingest.texte import normaliser
from maii.models.schemas import Categorie, ResultatVoie

# Indices par categorie : (expression reguliere, poids).
# Les expressions travaillent sur du texte normalise : minuscules, sans accent.
INDICES: dict[Categorie, list[tuple[str, float]]] = {
    Categorie.COMPTES: [
        (r"mot de passe", 3.0), (r"\bmdp\b", 3.0), (r"oubli\w*", 1.2),
        (r"compte\w*\s+(verrouill|bloqu)\w*", 3.5), (r"deverrouill\w*", 3.0),
        (r"(ne\s+)?arrive\w*\s+pas\s+a\s+me\s+connecter", 2.5),
        (r"ouvrir\s+ma\s+session", 2.5), (r"identifiant\w*\s+refus\w*", 2.5),
        (r"double\s+(facteur|authentification)", 3.0), (r"\b2fa\b", 3.0),
        (r"code\w*\s+de\s+validation", 2.5), (r"authentificateur", 3.0),
        (r"reinitialis\w*\s+.{0,20}mot de passe", 3.5), (r"connexion refus\w*", 1.5),
    ],
    Categorie.RESEAU: [
        (r"\breseau\b", 2.0), (r"\bwifi\b", 3.0), (r"sans fil", 2.5),
        (r"(pas|plus)\s+de\s+connexion", 3.0), (r"deconnect\w*", 2.0),
        (r"\blent\w*\b", 1.8), (r"\brame\b", 1.8), (r"lenteur", 2.0),
        (r"temps de reponse", 2.0), (r"\bcable\b", 2.0), (r"ethernet", 3.0),
        (r"pas d\s*internet|pas de connexion internet", 3.0),
        (r"coupure\w*", 1.5), (r"debit", 2.0), (r"prise reseau", 3.0),
        (r"inaccessible", 1.5), (r"\bping\b", 2.5),
    ],
    Categorie.MATERIEL: [
        (r"(ne|plus)\s+(demarre|s\s*allume)", 3.5), (r"ecran noir", 3.0),
        (r"\bpanne\b", 2.0), (r"\bclavier\b", 3.0), (r"\bsouris\b", 3.0),
        (r"\becran\b", 2.0), (r"ventilateur", 3.0), (r"chauff\w*", 2.5),
        (r"\bbruyant\b", 2.5), (r"peripherique\w*\s+.{0,15}(reconnu|defectueux)", 3.0),
        (r"non reconnu", 2.5), (r"\bbatterie\b", 3.0), (r"\busb\b", 2.0),
        (r"\bfige\b|se fige", 2.0), (r"pc-\d+", 1.0),
    ],
    Categorie.LOGICIELS: [
        (r"application\w*", 1.8), (r"logiciel\w*", 2.0), (r"\blogicie\w*", 1.5),
        (r"(ne\s+)?(demarre|lance)\w*\s+plus", 2.0), (r"\bplante\b", 2.5),
        (r"se ferme", 2.5), (r"message d\s*erreur", 2.0), (r"\bbug\b", 1.5),
        (r"outlook|messagerie|courriel|\bmail\b", 2.5), (r"boite\s+(aux\s+lettres|d\s*envoi)", 3.0),
        (r"\berp\b|\bodoo\b|\bsage\b|navision|as400", 3.0),
        (r"fichier\w*\s+.{0,15}(corrompu|ouvrir|illisible)", 3.0),
        (r"mise a jour", 1.5), (r"\bteams\b|sharepoint", 2.5),
    ],
    Categorie.IMPRIMANTES: [
        (r"imprim\w*", 3.5), (r"\bimprimente\b", 3.5), (r"impression", 3.5),
        (r"bourrage", 3.5), (r"papier", 2.0), (r"\btoner\b|cartouche", 3.0),
        (r"scann?\w*|numeris\w*", 3.0), (r"copieur", 3.0),
        (r"file d\s*attente", 2.0), (r"imp-\d+", 3.0), (r"rien ne sort", 2.5),
    ],
    Categorie.DROITS: [
        (r"acces?\s+(refus|impossible|en ecriture|en lecture)", 3.0),
        (r"\bdroit\w*\b", 2.5), (r"habilitation\w*", 3.5), (r"\bprofil\b", 2.0),
        (r"dossier\s+(partage|commun)", 3.0), (r"\bpartage\b", 2.0),
        (r"autorisation\w*", 2.5), (r"\bdepart\b|fin de contrat", 3.0),
        (r"desactiv\w*\s+.{0,15}acces", 3.0), (r"\bajouter\b.{0,20}\bgroupe\b", 2.5),
    ],
    Categorie.CYBERSECURITE: [
        (r"phishing|hameconnage", 4.0), (r"courriel\s+(suspect|bizarre|frauduleux)", 4.0),
        (r"mail\s+(suspect|bizarre|louche)", 4.0), (r"\bsuspect\w*", 2.0),
        (r"\bvirus\b|malware|rancongiciel|ranson|rancon", 4.0),
        (r"compromis\w*|infect\w*", 3.5), (r"fichiers?\s+.{0,15}(chiffr|renomm)\w*", 3.5),
        (r"\barnaque\b|\bfraude\b|frauduleux", 3.0), (r"\blouche\b", 2.5),
        (r"demande\s+.{0,15}(virement|identifiants)", 3.0),
        (r"j\s*ai clique", 3.0), (r"fenetres?\s+.{0,15}(ouvre|surgiss)\w*", 2.5),
    ],
}

# Signaux imposant la categorie cybersecurite quoi qu'en disent les autres
# voies. Un faux positif coute une verification ; un faux negatif peut couter
# la compromission du systeme d'information.
SIGNAUX_SECURITE = [
    r"phishing", r"hameconnage", r"rancongiciel", r"rancon", r"ranson",
    r"\bvirus\b", r"malware", r"compromis", r"\binfecte\w*",
    r"courriel\s+(suspect|frauduleux)", r"mail\s+(suspect|louche)",
    r"fichiers?\s+.{0,15}chiffr\w*", r"j\s*ai clique.{0,40}(lien|courriel|mail)",
    r"saisi\s+mon\s+mot\s+de\s+passe",
]

# Signaux d'urgence, exploites pour la priorite.
SIGNAUX_URGENCE = [
    (r"tout\w*\s+(le\s+service|l\s*equipe|la\s+direction)", 2.0),
    (r"plus personne", 2.5), (r"toute l\s*equipe", 2.0),
    (r"cloture\s+(mensuelle|comptable)", 2.0), (r"\becheance\b", 1.5),
    (r"activite\s+.{0,20}(arret|bloqu)\w*", 2.5), (r"\bbloqu\w*", 1.0),
    (r"\burgent\w*\b", 1.5), (r"\bcritique\b", 1.5), (r"immediat\w*", 1.0),
    (r"direction generale", 1.5), (r"\breunion\b.{0,20}(heure|minute)", 1.0),
]

_COMPILE = {
    categorie: [(re.compile(motif), poids) for motif, poids in motifs]
    for categorie, motifs in INDICES.items()
}
_COMPILE_SECURITE = [re.compile(m) for m in SIGNAUX_SECURITE]
_COMPILE_URGENCE = [(re.compile(m), p) for m, p in SIGNAUX_URGENCE]


def signal_securite(texte: str) -> bool:
    """Indique la presence d'un signal de securite imposant la categorie."""
    normalise = normaliser(texte)
    return any(motif.search(normalise) for motif in _COMPILE_SECURITE)


def score_urgence(texte: str) -> float:
    """Somme ponderee des marqueurs d'urgence, utilisee pour la priorite."""
    normalise = normaliser(texte)
    return sum(poids for motif, poids in _COMPILE_URGENCE if motif.search(normalise))


def classer(texte: str) -> ResultatVoie:
    """Classe un ticket par regles et renvoie une distribution normalisee."""
    normalise = normaliser(texte)
    if not normalise:
        return ResultatVoie(voie="regles", disponible=False,
                            motif_indisponibilite="texte vide")

    bruts: dict[str, float] = {}
    for categorie, motifs in _COMPILE.items():
        total = sum(poids for motif, poids in motifs if motif.search(normalise))
        if total:
            bruts[categorie.value] = total

    if signal_securite(texte):
        # La regle de securite l'emporte : on lui donne un poids dominant plutot
        # que d'ecraser la distribution, afin de conserver la trace des autres
        # hypotheses pour l'analyse.
        bruts[Categorie.CYBERSECURITE.value] = max(bruts.values(), default=0.0) + 6.0

    if not bruts:
        return ResultatVoie(
            voie="regles", categorie=Categorie.INDETERMINE,
            distribution={Categorie.INDETERMINE.value: 1.0}, confiance=0.15,
        )

    total = sum(bruts.values())
    distribution = {c: round(v / total, 4) for c, v in bruts.items()}
    meilleure = max(distribution, key=distribution.get)

    # La confiance croit avec la masse d'indices et avec l'ecart au second.
    ordonnees = sorted(distribution.values(), reverse=True)
    marge = ordonnees[0] - (ordonnees[1] if len(ordonnees) > 1 else 0.0)
    confiance = min(0.95, 0.35 + 0.4 * marge + min(0.25, total / 40))

    return ResultatVoie(
        voie="regles", categorie=Categorie(meilleure),
        distribution=distribution, confiance=round(confiance, 4),
    )
