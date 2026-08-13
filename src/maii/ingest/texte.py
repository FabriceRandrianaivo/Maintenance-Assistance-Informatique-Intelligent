"""Normalisation et decoupage du texte.

Mutualise entre la recherche documentaire et la classification, afin que les
deux composants voient exactement le meme texte normalise.

Le corpus contient volontairement des fautes de frappe et des formulations
informelles. La normalisation retire les accents et la ponctuation plutot que
de tenter de corriger : une correction orthographique automatique introduirait
ses propres erreurs, alors que la robustesse aux fautes est obtenue en aval par
les n-grammes de caracteres du vectoriseur.
"""

from __future__ import annotations

import re
import unicodedata

# Mots vides du francais, completes des formules de politesse et du vocabulaire
# de support omnipresent dans les tickets, qui n'apporte aucun pouvoir
# discriminant entre categories.
MOTS_VIDES = {
    "a", "au", "aux", "avec", "ce", "ces", "cet", "cette", "dans", "de", "des",
    "du", "elle", "en", "et", "eux", "il", "ils", "je", "la", "le", "les", "leur",
    "lui", "ma", "mais", "me", "meme", "mes", "moi", "mon", "ne", "nos", "notre",
    "nous", "on", "ou", "par", "pas", "pour", "qu", "que", "qui", "sa", "se",
    "ses", "son", "sur", "ta", "te", "tes", "toi", "ton", "tu", "un", "une",
    "vos", "votre", "vous", "c", "d", "j", "l", "m", "n", "s", "t", "y", "ete",
    "etee", "etees", "etes", "etant", "suis", "es", "est", "sommes", "sont",
    "sera", "serai", "seras", "serons", "serez", "seront", "ai", "as", "avons",
    "avez", "ont", "aura", "auras", "avait", "avais", "avaient", "eu", "cela",
    "ca", "sans", "sous", "entre", "aussi", "tres", "plus", "moins", "tout",
    "tous", "toute", "toutes", "autre", "autres", "meme", "encore", "deja",
    "depuis", "quand", "comme", "si", "alors", "donc", "or", "ni", "car",
    # formules et vocabulaire de support
    "bonjour", "bonsoir", "merci", "svp", "cordialement", "salutations",
    "madame", "monsieur", "slt", "urgent", "probleme", "souci", "aide",
}

_PONCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_ESPACES = re.compile(r"\s+")
# Identifiants du parc et references documentaires, a preserver intacts.
_REFERENCES = re.compile(r"\b(?:KB|PC|IMP|SCN|USR|TCK|INC)-[A-Z0-9-]+\b", re.IGNORECASE)


def sans_accent(texte: str) -> str:
    """Retire les signes diacritiques sans toucher au reste."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )


def normaliser(texte: str) -> str:
    """Met un texte en forme canonique : minuscules, sans accent ni ponctuation.

    Les identifiants du parc et les references documentaires sont preserves :
    leur ponctuation interne porte du sens et ils constituent des indices forts
    pour la recherche lexicale.
    """
    if not texte:
        return ""

    references: list[str] = []

    def mettre_de_cote(correspondance: re.Match) -> str:
        references.append(correspondance.group(0).lower())
        # Le marqueur n'est compose que de caracteres de mot : il traverse sans
        # dommage la suppression de la ponctuation et le passage en minuscules.
        return f" xrefx{len(references) - 1}xrefx "

    texte = _REFERENCES.sub(mettre_de_cote, texte)
    texte = sans_accent(texte).lower()
    texte = _PONCTUATION.sub(" ", texte)
    texte = _ESPACES.sub(" ", texte).strip()

    for i, reference in enumerate(references):
        texte = texte.replace(f"xrefx{i}xrefx", reference)
    return _ESPACES.sub(" ", texte).strip()


def decouper_en_mots(texte: str, retirer_mots_vides: bool = True) -> list[str]:
    """Produit la liste de mots utilisee par la recherche lexicale.

    Les mots d'une seule lettre sont ecartes, sauf s'ils font partie d'une
    reference conservee par la normalisation.
    """
    mots = normaliser(texte).split()
    if retirer_mots_vides:
        mots = [m for m in mots if m not in MOTS_VIDES]
    return [m for m in mots if len(m) > 1 or m.isdigit()]


def extraire_references(texte: str) -> list[str]:
    """Renvoie les identifiants du parc et de la base cites dans un texte."""
    vues: list[str] = []
    for correspondance in _REFERENCES.finditer(texte or ""):
        reference = correspondance.group(0).upper()
        if reference not in vues:
            vues.append(reference)
    return vues


def tronquer(texte: str, longueur: int = 240) -> str:
    """Raccourcit un texte pour l'affichage et le traçage."""
    texte = (texte or "").strip()
    return texte if len(texte) <= longueur else texte[: longueur - 1].rstrip() + "…"
