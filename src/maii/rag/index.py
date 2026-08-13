"""Index documentaire hybride : recherche lexicale et recherche vectorielle.

Deux voies de recherche complementaires, fusionnees par rang :

  - **BM25** excelle sur les termes exacts : identifiants d'equipement,
    references de procedure, sigles, codes d'erreur. Il ignore en revanche
    toute reformulation.
  - **TF-IDF sur n-grammes de mots et de caracteres**, compare par cosinus,
    rattrape les reformulations et surtout les fautes de frappe : les
    n-grammes de caracteres de « imprimente » et « imprimante » se recouvrent
    tres largement, la robustesse est obtenue sans correction orthographique.

Le choix d'un vectoriseur TF-IDF plutot que d'un modele d'embeddings est
assume : le corpus compte quelques centaines de passages, le vocabulaire est
ferme et technique, et l'installation d'un modele de plusieurs centaines de
megaoctets serait un point de defaillance sans gain mesure a cette echelle.
La recherche reste ainsi entierement hors ligne et deterministe.

Les deux classements sont combines par fusion de rangs reciproques (RRF), qui
ne demande aucune normalisation prealable des scores : c'est precisement son
interet quand on melange une mesure BM25 non bornee et un cosinus dans [0, 1].
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion

from maii import RACINE
from maii.ingest.chargement import charger_articles
from maii.ingest.texte import decouper_en_mots, normaliser
from maii.models.schemas import PassageSource
from maii.rag.decoupage import decouper_corpus, texte_indexable

CHEMIN_INDEX = RACINE / "data" / "index" / "documentaire.pkl"

# Constante de la fusion de rangs reciproques. La valeur usuelle de 60 attenue
# la domination des tout premiers rangs et laisse une chance a un passage bien
# classe par une seule des deux voies.
K_RRF = 60


@dataclass
class ResultatRecherche:
    """Passages retrouves et indicateurs permettant de decider d'une abstention."""

    passages: list[PassageSource]
    confiance: float
    requete_normalisee: str

    @property
    def vide(self) -> bool:
        return not self.passages


class IndexDocumentaire:
    """Index hybride sur les passages de la base de connaissances."""

    def __init__(self) -> None:
        self.passages: list[PassageSource] = []
        self._bm25: BM25Okapi | None = None
        self._vectoriseur: FeatureUnion | None = None
        self._matrice = None
        self._normes = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def construire(self, articles: list[dict] | None = None) -> "IndexDocumentaire":
        articles = articles if articles is not None else charger_articles()
        if not articles:
            raise RuntimeError(
                "base de connaissances vide : lancer data/synthetic/generer.py"
            )

        self.passages = decouper_corpus(articles)
        par_document = {a["doc_id"]: a for a in articles}
        textes = [
            texte_indexable(p, par_document.get(p.doc_id)) for p in self.passages
        ]

        # Voie lexicale.
        self._bm25 = BM25Okapi([decouper_en_mots(t) for t in textes])

        # Voie vectorielle : mots pour le sens, caracteres pour les fautes.
        self._vectoriseur = FeatureUnion([
            ("mots", TfidfVectorizer(
                analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True,
                preprocessor=normaliser,
            )),
            ("caracteres", TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
                preprocessor=normaliser,
            )),
        ])
        self._matrice = self._vectoriseur.fit_transform(textes)
        # Normes precalculees : la similarite cosinus se ramene alors a un
        # produit matriciel, negligeable a cette echelle.
        self._normes = np.sqrt(self._matrice.multiply(self._matrice).sum(axis=1)).A1
        self._normes[self._normes == 0] = 1e-12
        return self

    # ------------------------------------------------------------------
    # Persistance
    # ------------------------------------------------------------------

    def enregistrer(self, chemin: Path = CHEMIN_INDEX) -> Path:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("wb") as f:
            pickle.dump({
                "passages": [p.model_dump() for p in self.passages],
                "bm25": self._bm25,
                "vectoriseur": self._vectoriseur,
                "matrice": self._matrice,
                "normes": self._normes,
            }, f)
        return chemin

    @classmethod
    def charger(cls, chemin: Path = CHEMIN_INDEX) -> "IndexDocumentaire":
        """Charge l'index depuis le disque, ou le reconstruit s'il est absent."""
        index = cls()
        if not chemin.exists():
            return index.construire()
        try:
            with chemin.open("rb") as f:
                donnees = pickle.load(f)
            index.passages = [PassageSource(**p) for p in donnees["passages"]]
            index._bm25 = donnees["bm25"]
            index._vectoriseur = donnees["vectoriseur"]
            index._matrice = donnees["matrice"]
            index._normes = donnees["normes"]
        except Exception:
            # Un index illisible ou produit par une version anterieure est
            # reconstruit plutot que de faire echouer le demarrage.
            return index.construire()
        return index

    # ------------------------------------------------------------------
    # Recherche
    # ------------------------------------------------------------------

    def _rangs_bm25(self, requete: str) -> tuple[np.ndarray, np.ndarray]:
        scores = np.asarray(self._bm25.get_scores(decouper_en_mots(requete)))
        return scores, np.argsort(-scores)

    def _rangs_vectoriels(self, requete: str) -> tuple[np.ndarray, np.ndarray]:
        vecteur = self._vectoriseur.transform([requete])
        norme = float(np.sqrt(vecteur.multiply(vecteur).sum())) or 1e-12
        scores = np.asarray((self._matrice @ vecteur.T).todense()).ravel()
        scores = scores / (self._normes * norme)
        return scores, np.argsort(-scores)

    def rechercher(self, requete: str, k: int = 5, profondeur: int = 25) -> ResultatRecherche:
        """Retourne les k passages les plus pertinents, fusionnes par rang.

        `profondeur` fixe le nombre de candidats retenus par voie avant fusion :
        un passage absent des deux listes de tete ne peut pas remonter.
        """
        if not self.passages or not requete.strip():
            return ResultatRecherche([], 0.0, normaliser(requete))

        scores_bm25, ordre_bm25 = self._rangs_bm25(requete)
        scores_cos, ordre_cos = self._rangs_vectoriels(requete)

        profondeur = min(profondeur, len(self.passages))
        fusion: dict[int, float] = {}

        # Une voie sans signal ne vote pas. Sur une requete truffee de fautes,
        # aucun terme ne correspond exactement et tous les scores BM25 sont
        # nuls : l'ordre renvoye est alors arbitraire, et le crediter revient a
        # injecter du bruit qui noie le classement vectoriel, seul pertinent.
        for scores, ordre in ((scores_bm25, ordre_bm25), (scores_cos, ordre_cos)):
            if float(scores.max()) <= 1e-9:
                continue
            for rang, i in enumerate(ordre[:profondeur]):
                if scores[i] <= 1e-9:
                    break
                fusion[i] = fusion.get(i, 0.0) + 1.0 / (K_RRF + rang + 1)

        if not fusion:
            return ResultatRecherche([], 0.0, normaliser(requete))

        meilleurs = sorted(fusion, key=lambda i: -fusion[i])[:k]

        # Normalisation de BM25 par son maximum sur la requete : la mesure n'est
        # pas bornee, seule sa valeur relative est interpretable.
        bm25_max = float(scores_bm25.max()) or 1e-12

        passages = []
        for i in meilleurs:
            passage = self.passages[i].model_copy()
            passage.score = round(float(fusion[i]), 6)
            passage.score_bm25 = round(float(scores_bm25[i]) / bm25_max, 4)
            passage.score_dense = round(float(scores_cos[i]), 4)
            passages.append(passage)

        return ResultatRecherche(
            passages=passages,
            confiance=self._confiance(scores_bm25, scores_cos, meilleurs),
            requete_normalisee=normaliser(requete),
        )

    @staticmethod
    def _confiance(scores_bm25: np.ndarray, scores_cos: np.ndarray,
                   retenus: list[int]) -> float:
        """Estime la fiabilite de la recherche, dans [0, 1].

        Sert a decider d'une abstention. Deux signaux sont combines :
        la similarite cosinus du meilleur passage, bornee et directement
        interpretable, et l'accord entre les deux voies. Deux methodes de
        recherche independantes qui designent le meme passage constituent un
        indice de pertinence bien plus fort qu'un score eleve sur une seule.
        """
        if not retenus:
            return 0.0

        cosinus_max = float(max(scores_cos[i] for i in retenus))

        tete_bm25 = set(np.argsort(-scores_bm25)[:5].tolist())
        tete_cos = set(np.argsort(-scores_cos)[:5].tolist())
        accord = len(tete_bm25 & tete_cos) / 5.0

        # Le cosinus reste le signal dominant ; l'accord le module.
        return round(min(1.0, 0.7 * cosinus_max + 0.3 * accord), 4)


_index: IndexDocumentaire | None = None


def index() -> IndexDocumentaire:
    """Index partage, construit une seule fois par processus."""
    global _index
    if _index is None:
        _index = IndexDocumentaire.charger()
    return _index
