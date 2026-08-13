"""Preparation des artefacts au demarrage.

L'index documentaire et le classifieur supervise sont des artefacts derives :
ils se reconstruisent a partir du corpus versionne et ne sont donc pas suivis
par Git. Une machine qui recupere le depot ne les possede pas.

Sans cette preparation, le systeme demarre quand meme — l'index se reconstruit
tout seul — mais la voie supervisee reste absente et la classification retombe
au niveau des regles seules, soit environ vingt points de macro-F1 en moins.
Le prototype paraitrait alors bien plus faible qu'il ne l'est.

Ce module rend le demarrage autonome : il detecte ce qui manque, le construit,
et rend compte de ce qu'il a fait. Il est appele par l'interface comme par les
scripts de lancement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from maii import RACINE


@dataclass
class EtatPreparation:
    """Compte rendu de la preparation, affichable a l'utilisateur."""

    corpus_present: bool = False
    index_construit: bool = False
    index_recharge: bool = False
    modele_entraine: bool = False
    modele_recharge: bool = False
    messages: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)

    @property
    def operationnel(self) -> bool:
        return self.corpus_present and not self.erreurs


def preparer(forcer: bool = False) -> EtatPreparation:
    """Construit les artefacts manquants et renvoie l'etat obtenu.

    `forcer` reconstruit meme si les fichiers existent, ce qui sert apres une
    modification du corpus.
    """
    etat = EtatPreparation()

    # --- corpus ---------------------------------------------------------
    from maii.ingest.chargement import donnees_disponibles

    if not donnees_disponibles():
        # Le corpus est versionne : son absence signale un depot incomplet.
        etat.erreurs.append(
            "corpus absent — lancer : python data/synthetic/generer.py"
        )
        return etat
    etat.corpus_present = True

    # --- index documentaire ---------------------------------------------
    from maii.rag.index import CHEMIN_INDEX, IndexDocumentaire

    try:
        if forcer or not CHEMIN_INDEX.exists():
            IndexDocumentaire().construire().enregistrer()
            etat.index_construit = True
            etat.messages.append("index documentaire construit")
        else:
            etat.index_recharge = True
    except Exception as exc:
        etat.erreurs.append(f"index documentaire : {exc}")

    # --- classifieur supervise ------------------------------------------
    from maii.classify.ml import CHEMIN_MODELE, ClassifieurAppris
    from maii.ingest.chargement import charger_tickets

    try:
        if forcer or not CHEMIN_MODELE.exists():
            ClassifieurAppris().entrainer(charger_tickets()).enregistrer()
            etat.modele_entraine = True
            etat.messages.append("classifieur supervise entraine")
        else:
            etat.modele_recharge = True
    except Exception as exc:
        # L'absence de modele n'empeche pas le systeme de fonctionner :
        # l'arbitrage se replie sur les regles et le modele de langage.
        etat.erreurs.append(f"classifieur : {exc}")

    if not etat.messages:
        etat.messages.append("artefacts deja presents")

    return etat


def chemin_relatif(chemin) -> str:
    """Chemin affichable, relatif a la racine du projet."""
    try:
        return str(chemin.relative_to(RACINE))
    except ValueError:
        return str(chemin)
