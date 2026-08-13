"""Garde-fous de securite (section 6 du sujet).

Principe directeur : les protections sont appliquees **en code**, avant et
apres l'appel au modele de langage, jamais confiees a une consigne de prompt.
Un ticket qui manipule le modele ne peut donc pas les desactiver, puisque le
modele n'a aucune prise dessus.

Trois protections :
  - detection et pseudonymisation des donnees personnelles avant tout envoi
    a un service externe ;
  - detection des tentatives d'injection de consignes, dans le ticket comme
    dans les documents retrouves ;
  - verrouillage des actions sensibles, qui exigent une validation humaine.
"""

from __future__ import annotations

import re

from maii.models.schemas import Categorie, VerdictSecurite

# --- Donnees personnelles ---------------------------------------------------
# L'ordre compte : les motifs les plus specifiques passent en premier.
MOTIFS_PII: list[tuple[str, str]] = [
    ("courriel", r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    ("telephone", r"(?:\+261|0)\s?3\d(?:[\s.-]?\d{2}){3,4}\b"),
    ("adresse_ip", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("adresse_mac", r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    ("iban", r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),
    ("mot_de_passe", r"(?i)\b(?:mot de passe|mdp|password)\s*(?:est|:|=)\s*\S+"),
]

# --- Tentatives d'injection -------------------------------------------------
MOTIFS_INJECTION: list[tuple[str, str, float]] = [
    ("consigne_ignorer", r"(?i)ignore[rz]?\s+(?:tou(?:tes|s)\s+)?(?:tes|les|vos)\s+"
                         r"(?:instructions|consignes|regles)", 1.0),
    ("consigne_oublier", r"(?i)oublie[rz]?\s+(?:tou(?:tes|s)\s+)?(?:tes|les|la)\s+"
                         r"(?:instructions|consignes|procedure|regles)", 1.0),
    ("changement_role", r"(?i)tu\s+es\s+(?:maintenant|desormais)\b", 0.9),
    ("mode_admin", r"(?i)mode\s+(?:administrateur|admin|developpeur|sans\s+restriction)", 0.9),
    ("fausse_balise", r"(?i)(?:^|\n)\s*(?:###\s*)?(?:system|systeme|assistant)\s*:", 0.9),
    ("fin_de_ticket", r"(?i)#{2,}\s*fin\s+du\s+ticket\s*#{2,}", 1.0),
    ("desactiver_controle", r"(?i)(?:validation|verification|controle)\s+"
                            r"(?:humaine\s+)?(?:est\s+)?desactive", 1.0),
    ("sans_validation", r"(?i)(?:sans|ne\s+demande\s+pas\s+de)\s+"
                        r"(?:validation|verification|confirmation)", 0.8),
    ("exfiltration", r"(?i)(?:liste|donne|affiche)[rz]?[- ]?(?:moi\s+)?"
                     r"(?:tous?\s+les|toutes?\s+les)\s+"
                     r"(?:utilisateurs|comptes|mots\s+de\s+passe|identifiants)", 0.9),
    ("mot_de_passe_tiers", r"(?i)(?:donne|communique|affiche|envoie)[rz]?[- ]?(?:moi\s+)?"
                           r".{0,30}mot\s+de\s+passe\s+d[eu]", 1.0),
    ("effacer_trace", r"(?i)(?:ne\s+laisse|sans)\s+(?:aucune\s+)?trace", 0.9),
    ("autorite_invoquee", r"(?i)je\s+suis\s+(?:le\s+)?(?:nouveau\s+)?"
                          r"(?:directeur|administrateur|responsable|dsi)", 0.7),
]

SEUIL_BLOCAGE = 0.9

# --- Actions sensibles ------------------------------------------------------
# Enumerees par la section 6 : elles exigent toujours une validation humaine.
ACTIONS_SENSIBLES = {
    "reinitialiser_mot_de_passe", "modifier_droits", "escalader_vers_technicien",
    "supprimer_ticket", "revoquer_second_facteur", "desactiver_compte",
}

CATEGORIES_SENSIBLES = {Categorie.CYBERSECURITE, Categorie.DROITS}

_PII = [(nom, re.compile(motif)) for nom, motif in MOTIFS_PII]
_INJECTION = [(nom, re.compile(motif), poids) for nom, motif, poids in MOTIFS_INJECTION]


def detecter_pii(texte: str) -> list[str]:
    """Types de donnees personnelles presentes dans un texte."""
    return [nom for nom, motif in _PII if motif.search(texte or "")]


def pseudonymiser(texte: str) -> tuple[str, dict[str, str]]:
    """Remplace les donnees personnelles par des jetons reversibles.

    La correspondance est conservee afin de restituer les valeurs a l'affichage :
    l'utilisateur voit son ticket intact, seul le service externe ne recoit que
    les jetons.
    """
    correspondances: dict[str, str] = {}
    resultat = texte or ""
    compteurs: dict[str, int] = {}

    for nom, motif in _PII:
        def remplacer(correspondance: re.Match) -> str:
            valeur = correspondance.group(0)
            for jeton, origine in correspondances.items():
                if origine == valeur:
                    return jeton
            compteurs[nom] = compteurs.get(nom, 0) + 1
            jeton = f"[{nom.upper()}_{compteurs[nom]}]"
            correspondances[jeton] = valeur
            return jeton

        resultat = motif.sub(remplacer, resultat)

    return resultat, correspondances


def restituer(texte: str, correspondances: dict[str, str]) -> str:
    """Operation inverse de la pseudonymisation, pour l'affichage."""
    for jeton, valeur in correspondances.items():
        texte = texte.replace(jeton, valeur)
    return texte


def analyser(texte: str) -> VerdictSecurite:
    """Analyse de securite d'un texte entrant : injection et donnees personnelles."""
    detectes = [nom for nom, motif, _ in _INJECTION if motif.search(texte or "")]
    score = max(
        (poids for nom, motif, poids in _INJECTION if motif.search(texte or "")),
        default=0.0,
    )
    assaini, _ = pseudonymiser(texte)

    return VerdictSecurite(
        injection_detectee=bool(detectes),
        patterns_detectes=detectes,
        score_risque=round(score, 2),
        pii_detectees=detecter_pii(texte),
        texte_assaini=assaini,
        bloquer=score >= SEUIL_BLOCAGE,
        motif=(
            "tentative de manipulation de l'assistant detectee : "
            + ", ".join(detectes)
        ) if detectes else None,
    )


def encadrer_document(reference: str, contenu: str) -> str:
    """Encadre un passage retrouve avant de l'inserer dans un prompt.

    Le contenu de la base de connaissances est une donnee non fiable : une
    consigne malveillante peut y avoir ete deposee. Le delimitage explicite est
    ce qui permet au modele de distinguer ce qu'il doit lire de ce qu'il doit
    executer.
    """
    return (
        f"<<<DOCUMENT {reference}\n"
        f"{contenu}\n"
        f"DOCUMENT {reference}>>>"
    )


def validation_requise(categorie: Categorie, action: str,
                       verdict: VerdictSecurite | None = None) -> bool:
    """Determine si une decision exige une validation humaine.

    Applique apres la generation, en code : c'est ce qui rend la regle
    incontournable par un ticket malveillant.
    """
    if action in ACTIONS_SENSIBLES:
        return True
    if categorie in CATEGORIES_SENSIBLES:
        return True
    if verdict and (verdict.injection_detectee or verdict.pii_detectees):
        return True
    return False
