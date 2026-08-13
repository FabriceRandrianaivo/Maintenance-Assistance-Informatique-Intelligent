"""Decoupage des articles de la base de connaissances en passages indexables.

Le decoupage suit la structure des documents plutot qu'un nombre fixe de
caracteres : dans une base de procedures, un titre de section delimite une unite
de sens complete. Couper une procedure au milieu de ses etapes produirait des
passages inexploitables, et donc des reponses incompletes.

Un passage trop long est ensuite subdivise sur les frontieres de paragraphes,
et les fragments trop courts sont rattaches au passage precedent.
"""

from __future__ import annotations

import re

from maii.models.schemas import PassageSource

TAILLE_MAX = 1200      # caracteres, au-dela desquels un passage est subdivise
TAILLE_MIN = 120       # en deca, un fragment est fusionne avec le precedent

_TITRE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_ENTETE = re.compile(
    r"^#\s+(?P<titre>.+?)\n+"
    r"Identifiant\s*:\s*(?P<doc_id>\S+)\n"
    r"Categorie\s*:\s*(?P<categorie>\S+)\n"
    r"Type\s*:\s*(?P<type>\S+)\n"
    r"Mots-cles\s*:\s*(?P<mots_cles>.+)$",
    re.MULTILINE,
)


def _subdiviser(texte: str) -> list[str]:
    """Coupe un passage trop long sur les frontieres de paragraphes."""
    if len(texte) <= TAILLE_MAX:
        return [texte]

    morceaux: list[str] = []
    courant = ""
    for paragraphe in texte.split("\n\n"):
        if courant and len(courant) + len(paragraphe) + 2 > TAILLE_MAX:
            morceaux.append(courant.strip())
            courant = paragraphe
        else:
            courant = f"{courant}\n\n{paragraphe}" if courant else paragraphe
    if courant.strip():
        morceaux.append(courant.strip())
    return morceaux


def decouper_article(article: dict) -> list[PassageSource]:
    """Transforme un article en une liste de passages indexables.

    Chaque passage porte le titre de l'article et celui de sa section : cette
    redondance volontaire ameliore nettement la recherche, un passage isole
    perdant sinon tout contexte sur le probleme qu'il traite.
    """
    contenu = article.get("contenu", "")
    doc_id = article["doc_id"]
    titre_article = article.get("titre", doc_id)

    # Le corps utile commence apres l'en-tete de metadonnees.
    entete = _ENTETE.search(contenu)
    corps = contenu[entete.end():] if entete else contenu

    titres = list(_TITRE.finditer(corps))
    sections: list[tuple[str, str]] = []

    if not titres:
        sections.append(("", corps.strip()))
    else:
        # Texte precedant la premiere section, le cas echeant.
        preambule = corps[: titres[0].start()].strip()
        if len(preambule) >= TAILLE_MIN:
            sections.append(("", preambule))
        for i, titre in enumerate(titres):
            fin = titres[i + 1].start() if i + 1 < len(titres) else len(corps)
            sections.append((titre.group(1).strip(), corps[titre.end():fin].strip()))

    passages: list[PassageSource] = []
    for intitule, texte in sections:
        if not texte:
            continue
        for morceau in _subdiviser(texte):
            if not morceau.strip():
                continue
            # Un fragment residuel est rattache au passage precedent plutot que
            # de produire un passage sans contenu exploitable.
            if len(morceau) < TAILLE_MIN and passages:
                passages[-1].contenu += "\n\n" + morceau
                continue
            passages.append(
                PassageSource(
                    doc_id=doc_id,
                    chunk_id=f"c{len(passages) + 1}",
                    titre=f"{titre_article} — {intitule}" if intitule else titre_article,
                    contenu=morceau,
                    score=0.0,
                )
            )

    return passages


def decouper_corpus(articles: list[dict]) -> list[PassageSource]:
    """Decoupe l'ensemble de la base de connaissances."""
    passages: list[PassageSource] = []
    for article in articles:
        passages.extend(decouper_article(article))
    return passages


def texte_indexable(passage: PassageSource, article: dict | None = None) -> str:
    """Compose le texte reellement indexe pour un passage.

    Le titre et les mots-cles de l'article sont ajoutes au contenu : ils portent
    le vocabulaire de l'utilisateur, souvent absent du corps de la procedure,
    redige lui dans un registre technique.
    """
    # L'identifiant est indexe explicitement : un utilisateur citant une
    # procedure par sa reference doit pouvoir la retrouver, alors que l'en-tete
    # de metadonnees a ete retiree au decoupage.
    morceaux = [passage.doc_id, passage.titre, passage.contenu]
    if article:
        mots_cles = article.get("mots_cles") or []
        if isinstance(mots_cles, str):
            mots_cles = [mots_cles]
        morceaux.append(" ".join(mots_cles))
        morceaux.append(article.get("categorie", ""))
    return "\n".join(m for m in morceaux if m)
