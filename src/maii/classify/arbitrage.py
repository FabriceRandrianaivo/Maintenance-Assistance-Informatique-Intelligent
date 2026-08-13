"""Arbitrage des trois voies de classification.

L'arbitrage est entierement deterministe et lisible : c'est un choix. Le jury
doit pouvoir rejouer une decision a la main, et une regle metier ne doit pas
dependre d'un modele generatif. Les modeles proposent, le code decide.

Trois etapes :
  1. fusion ponderee des distributions des voies disponibles ;
  2. application des regles imperatives, qui priment sur la fusion ;
  3. decision d'abstention si la confiance reste insuffisante.

Les poids sont volontairement modestes pour la voie « regles » : elle est tres
precise mais peu couvrante. Elle reprend en revanche la main entierement sur
les signaux de securite.
"""

from __future__ import annotations

from maii.classify import llm as voie_llm
from maii.classify import ml as voie_ml
from maii.classify import regles as voie_regles
from maii.classify.routage import equipe_pour, priorite_ajustee
from maii.models.schemas import (
    Categorie, ResultatClassification, ResultatVoie,
)

# Poids de fusion. La voie apprise domine : la mesure d'ablation lui donne
# nettement raison sur ce corpus (voir reports/classification.json).
POIDS = {"regles": 0.20, "ml": 0.55, "llm": 0.25}

# Seuil de declenchement de la voie generative.
#
# L'ablation a montre qu'une fusion systematique des trois voies degradait le
# resultat : le modele supervise atteint 0.88 de macro-F1 quand la voie
# generative plafonne a 0.69, et la faire voter sur chaque ticket faisait
# retomber l'ensemble a 0.80. Le modele de langage n'est donc plus un votant
# permanent mais un recours, sollicite uniquement quand le modele supervise
# doute, quand les voies se contredisent, ou quand le ticket ne ressemble a
# rien de connu. C'est precisement la ou il apporte quelque chose.
#
# Effet secondaire decisif en conditions d'examen : le nombre d'appels chute
# d'environ trois quarts, ce qui supprime le plafonnement de debit et divise
# d'autant la latence moyenne.
SEUIL_RECOURS_LLM = 0.60

# En deca de ce seuil, le systeme ne tranche pas et demande une validation.
SEUIL_ABSTENTION = 0.45

# Au-dela de cette distance au corpus, le ticket est signale hors distribution.
SEUIL_HORS_DISTRIBUTION = 0.88


def _fusionner(voies: list[ResultatVoie]) -> dict[str, float]:
    """Combine les distributions des voies disponibles, ponderees et renormalisees."""
    cumul: dict[str, float] = {}
    poids_total = 0.0
    for voie in voies:
        if not voie.disponible or not voie.distribution:
            continue
        poids = POIDS.get(voie.voie, 0.0)
        poids_total += poids
        for categorie, valeur in voie.distribution.items():
            cumul[categorie] = cumul.get(categorie, 0.0) + poids * valeur

    if not cumul or poids_total == 0:
        return {}
    # Renormalisation : sans elle, l'indisponibilite d'une voie ecraserait
    # mecaniquement la confiance de toutes les autres.
    return {c: round(v / poids_total, 4) for c, v in cumul.items()}


def classer(texte: str, contexte: dict | None = None) -> ResultatClassification:
    """Classe un ticket en combinant les trois voies.

    `contexte` peut porter des elements collectes par ailleurs : utilisateur
    VIP, nombre d'utilisateurs impactes, incident global rattache. Ils
    n'influencent que la priorite, jamais la categorie.
    """
    contexte = contexte or {}

    resultat_regles = voie_regles.classer(texte)
    modele = voie_ml.classifieur()
    resultat_ml = (
        modele.classer(texte) if modele
        else ResultatVoie(voie="ml", disponible=False,
                          motif_indisponibilite="modele non entraine")
    )
    # Cascade : la voie generative n'est sollicitee qu'en cas de doute.
    doute = (
        not resultat_ml.disponible
        or resultat_ml.confiance < SEUIL_RECOURS_LLM
        or (resultat_regles.disponible
            and resultat_regles.categorie is not resultat_ml.categorie)
    )
    if doute:
        resultat_llm = voie_llm.classer(texte)
    else:
        resultat_llm = ResultatVoie(
            voie="llm", disponible=False,
            motif_indisponibilite="non sollicitee : modele supervise confiant",
        )
    voies = [resultat_regles, resultat_ml, resultat_llm]

    distribution = _fusionner(voies)
    if not distribution:
        return ResultatClassification(
            categorie=Categorie.INDETERMINE, priorite="moyenne",
            equipe=equipe_pour(Categorie.INDETERMINE, "moyenne"),
            confiance=0.0, distribution={}, voies=voies, abstention=True,
        )

    categorie = Categorie(max(distribution, key=distribution.get))
    confiance = distribution[categorie.value]

    # --- Regle imperative : la securite prime sur la fusion -----------------
    # Elle est appliquee en code, apres les modeles. Un ticket manipulant le
    # modele de langage ne peut donc pas la desactiver.
    if voie_regles.signal_securite(texte):
        categorie = Categorie.CYBERSECURITE
        confiance = max(confiance, 0.90)

    # --- Desaccord entre voies ---------------------------------------------
    avis = {v.categorie for v in voies if v.disponible and v.categorie}
    desaccord = len(avis) > 1
    if desaccord:
        # Un desaccord est une information : la confiance affichee doit en tenir
        # compte, sous peine d'annoncer une certitude que le systeme n'a pas.
        confiance *= 0.85

    # --- Detection hors distribution (section 3.1) --------------------------
    hors_distribution = False
    if modele:
        distance = modele.distance_au_corpus(texte)
        hors_distribution = distance >= SEUIL_HORS_DISTRIBUTION
        if hors_distribution:
            confiance *= 0.7

    # --- Abstention ---------------------------------------------------------
    abstention = confiance < SEUIL_ABSTENTION
    if abstention and categorie is not Categorie.CYBERSECURITE:
        # On n'abstient jamais sur un signal de securite : mieux vaut escalader
        # a tort que laisser passer un incident.
        categorie = Categorie.INDETERMINE

    priorite = priorite_ajustee(
        categorie=categorie, texte=texte,
        proposition_ml=resultat_ml.priorite if resultat_ml.disponible else None,
        proposition_llm=resultat_llm.priorite if resultat_llm.disponible else None,
        contexte=contexte,
    )

    return ResultatClassification(
        categorie=categorie,
        priorite=priorite,
        equipe=equipe_pour(categorie, priorite),
        confiance=round(min(1.0, confiance), 4),
        distribution=distribution,
        voies=voies,
        desaccord=desaccord,
        abstention=abstention,
        hors_distribution=hors_distribution,
    )
