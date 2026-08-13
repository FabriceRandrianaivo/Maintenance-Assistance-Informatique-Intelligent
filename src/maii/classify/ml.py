"""Voie B : classification supervisee.

Deux modeles distincts sont appris : la categorie et la priorite. Les separer
est un choix delibere — le sujet annonce que des tickets similaires portent des
priorites differentes, ce qui signifie que la priorite depend du contexte
(perimetre, echeance, statut de l'utilisateur) et non du seul symptome. Un
modele unique predisant un couple les confondrait.

Representation du texte : union de n-grammes de mots et de n-grammes de
caracteres. Les seconds sont indispensables ici — le corpus contient des fautes
de frappe volontaires, et « imprimente » ne partage aucun mot avec
« imprimante » mais partage l'essentiel de ses n-grammes de caracteres.

Les probabilites sont calibrees : sans calibration, les scores d'un modele
lineaire ne sont pas des probabilites exploitables, et le seuil d'abstention de
l'arbitrage n'aurait alors aucun sens.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from maii import RACINE
from maii.ingest.texte import normaliser
from maii.models.schemas import Categorie, ResultatVoie

CHEMIN_MODELE = RACINE / "data" / "index" / "classifieur.pkl"

# En deca de ce nombre d'exemples pour une classe, la calibration croisee n'est
# pas fiable et le modele est appris sans elle.
MIN_EXEMPLES_CALIBRATION = 15


def _vectoriseur() -> FeatureUnion:
    return FeatureUnion([
        ("mots", TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True,
            preprocessor=normaliser,
        )),
        ("caracteres", TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True,
            preprocessor=normaliser,
        )),
    ])


def _modele(calibrer: bool) -> Pipeline:
    base = LogisticRegression(
        max_iter=2000,
        # Le corpus est volontairement desequilibre : sans reponderation, les
        # classes rares seraient purement et simplement ignorees.
        class_weight="balanced",
        C=2.0,
    )
    estimateur = (
        CalibratedClassifierCV(base, method="sigmoid", cv=3) if calibrer else base
    )
    return Pipeline([("vecteur", _vectoriseur()), ("modele", estimateur)])


class ClassifieurAppris:
    """Modeles de categorie et de priorite appris sur l'historique."""

    def __init__(self) -> None:
        self.modele_categorie: Pipeline | None = None
        self.modele_priorite: Pipeline | None = None
        self.classes_categorie: list[str] = []
        self.classes_priorite: list[str] = []
        self.nb_exemples = 0
        # Centroides par classe, utilises pour la detection hors distribution.
        self._centroides: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------

    def entrainer(self, tickets: list[dict]) -> "ClassifieurAppris":
        textes = [t["description"] for t in tickets if t.get("description")]
        categories = [t["categorie_reelle"] for t in tickets if t.get("description")]
        priorites = [t["priorite_reelle"] for t in tickets if t.get("description")]
        if len(textes) < 30:
            raise RuntimeError("historique insuffisant pour un apprentissage")

        rares = min(categories.count(c) for c in set(categories))
        self.modele_categorie = _modele(calibrer=rares >= MIN_EXEMPLES_CALIBRATION)
        self.modele_categorie.fit(textes, categories)
        self.classes_categorie = list(self.modele_categorie.named_steps["modele"].classes_)

        rares_p = min(priorites.count(p) for p in set(priorites))
        self.modele_priorite = _modele(calibrer=rares_p >= MIN_EXEMPLES_CALIBRATION)
        self.modele_priorite.fit(textes, priorites)
        self.classes_priorite = list(self.modele_priorite.named_steps["modele"].classes_)

        self.nb_exemples = len(textes)
        self._calculer_centroides(textes, categories)
        return self

    def _calculer_centroides(self, textes: list[str], categories: list[str]) -> None:
        """Centre de gravite de chaque classe, pour mesurer l'atypicite d'un ticket."""
        vecteurs = self.modele_categorie.named_steps["vecteur"].transform(textes)
        normes = np.sqrt(vecteurs.multiply(vecteurs).sum(axis=1)).A1
        normes[normes == 0] = 1e-12
        for classe in set(categories):
            lignes = [i for i, c in enumerate(categories) if c == classe]
            moyenne = np.asarray(vecteurs[lignes].mean(axis=0)).ravel()
            norme = np.linalg.norm(moyenne) or 1e-12
            self._centroides[classe] = moyenne / norme

    # ------------------------------------------------------------------

    def distance_au_corpus(self, texte: str) -> float:
        """Distance cosinus au centroide de classe le plus proche, dans [0, 1].

        Une valeur elevee signale un ticket ne ressemblant a aucune categorie
        connue : c'est le signal de detection hors distribution demande par la
        section 3.1 du sujet.
        """
        if not self._centroides or self.modele_categorie is None:
            return 0.0
        vecteur = self.modele_categorie.named_steps["vecteur"].transform([texte])
        dense = np.asarray(vecteur.todense()).ravel()
        norme = np.linalg.norm(dense) or 1e-12
        dense = dense / norme
        similarite = max(float(dense @ centroide) for centroide in self._centroides.values())
        return round(float(1.0 - max(0.0, min(1.0, similarite))), 4)

    def classer(self, texte: str) -> ResultatVoie:
        if self.modele_categorie is None:
            return ResultatVoie(voie="ml", disponible=False,
                                motif_indisponibilite="modele non entraine")
        if not texte or not texte.strip():
            return ResultatVoie(voie="ml", disponible=False,
                                motif_indisponibilite="texte vide")

        probabilites = self.modele_categorie.predict_proba([texte])[0]
        distribution = {
            classe: round(float(p), 4)
            for classe, p in zip(self.classes_categorie, probabilites)
        }
        meilleure = max(distribution, key=distribution.get)

        priorite = None
        if self.modele_priorite is not None:
            priorite = str(self.modele_priorite.predict([texte])[0])

        return ResultatVoie(
            voie="ml",
            categorie=Categorie(meilleure),
            distribution=distribution,
            priorite=priorite,
            confiance=round(float(max(probabilites)), 4),
        )

    # ------------------------------------------------------------------

    def enregistrer(self, chemin: Path = CHEMIN_MODELE) -> Path:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("wb") as f:
            pickle.dump(self, f)
        return chemin

    @classmethod
    def charger(cls, chemin: Path = CHEMIN_MODELE) -> "ClassifieurAppris | None":
        """Charge le modele appris, ou None s'il est absent ou illisible.

        L'absence de modele n'est pas une erreur : l'arbitrage se replie alors
        sur les regles et le modele de langage.
        """
        if not chemin.exists():
            return None
        try:
            with chemin.open("rb") as f:
                modele = pickle.load(f)
            return modele if isinstance(modele, cls) else None
        except Exception:
            return None


_classifieur: ClassifieurAppris | None = None
_charge = False


def classifieur() -> ClassifieurAppris | None:
    """Modele partage, charge une seule fois par processus."""
    global _classifieur, _charge
    if not _charge:
        _classifieur = ClassifieurAppris.charger()
        _charge = True
    return _classifieur
