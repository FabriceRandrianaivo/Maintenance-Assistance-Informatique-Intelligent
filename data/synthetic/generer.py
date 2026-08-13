"""Generation du jeu de donnees du prototype.

Le sujet annonce a la section 7 un ensemble de ressources sans le fournir. Ce
script le reconstitue integralement : historique de tickets, base de
connaissances, inventaire des utilisateurs et des equipements, liste des
services et liste des incidents actifs.

La section 7 precise egalement les defauts que les donnees pourront contenir.
Ils sont ici injectes volontairement, avec des taux parametres et journalises,
ce qui permet de mesurer la robustesse du systeme defaut par defaut plutot que
de la supposer.

Utilisation :
    python data/synthetic/generer.py [--graine 1789] [--tickets 420]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import (  # noqa: E402
    APPLICATIONS, BASE_CONNAISSANCES, DIRECTIONS, GABARITS, HORS_DISTRIBUTION,
    INCIDENTS_ACTIFS, MODELES_PERIPH, MODELES_POSTE, NOMS, PRENOMS, ROUTAGE,
    SERVICES, SITES, TICKETS_MALVEILLANTS,
)

RACINE = Path(__file__).resolve().parents[2]
SORTIE = RACINE / "data" / "raw"

# --- Taux des defauts injectes (section 7 du sujet) ---------------------------
TAUX_FAUTES = 0.22           # fautes d orthographe et de frappe
TAUX_VAGUE = 0.10            # formulations vagues ou incompletes
TAUX_ETIQUETTE_BRUITEE = 0.05  # etiquettes imparfaites
TAUX_CHAMPS_MANQUANTS = 0.15  # valeurs manquantes dans les metadonnees
TAUX_PRIORITE_INCOHERENTE = 0.08  # tickets similaires, priorites differentes
PART_HORS_DISTRIBUTION = 0.03
PART_MALVEILLANTS = 0.02

# Desequilibre volontaire des categories (section 7).
POIDS_CATEGORIES = {
    "comptes_authentification": 0.24,
    "reseau_connectivite": 0.19,
    "logiciels_applications": 0.17,
    "materiel_informatique": 0.12,
    "imprimantes_peripheriques": 0.11,
    "droits_acces": 0.08,
    "cybersecurite": 0.06,
    "autre_indetermine": 0.03,
}

PRIORITES = ["critique", "haute", "moyenne", "basse"]


# -----------------------------------------------------------------------------
# Alteration du texte
# -----------------------------------------------------------------------------


def sans_accent(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )


def introduire_fautes(texte: str, rng: random.Random, intensite: float = 0.04) -> str:
    """Applique des alterations de frappe realistes a un texte.

    Quatre familles : inversion de deux lettres voisines, lettre omise, lettre
    doublee, et confusion phonetique frequente en francais.
    """
    confusions = [
        ("ss", "s"), ("mm", "m"), ("tt", "t"), ("er", "e"), ("ez", "e"),
        ("ais", "ai"), ("ent", "ant"), ("c", "ss"), ("qu", "k"),
    ]
    mots = texte.split(" ")
    for i, mot in enumerate(mots):
        if len(mot) < 4 or rng.random() > intensite * 4:
            continue
        choix = rng.random()
        if choix < 0.30:  # inversion
            j = rng.randrange(1, len(mot) - 1)
            mots[i] = mot[:j] + mot[j + 1] + mot[j] + mot[j + 2:]
        elif choix < 0.55:  # omission
            j = rng.randrange(1, len(mot))
            mots[i] = mot[:j] + mot[j + 1:]
        elif choix < 0.75:  # doublement
            j = rng.randrange(1, len(mot))
            mots[i] = mot[:j] + mot[j] + mot[j:]
        else:  # confusion
            avant, apres = rng.choice(confusions)
            if avant in mot:
                mots[i] = mot.replace(avant, apres, 1)
    return " ".join(mots)


def rendre_vague(texte: str, rng: random.Random) -> str:
    """Tronque et affadit une demande pour simuler une description incomplete."""
    debuts = ["bonjour ", "slt ", "svp ", ""]
    corps = [
        "j ai un souci", "ca ne marche pas", "probleme depuis ce matin",
        "rien ne fonctionne", "il y a un bug", "c est bloque",
    ]
    fins = [", merci", " svp", "", ". Pouvez vous voir ?", " urgent"]
    if rng.random() < 0.5:
        return rng.choice(debuts) + rng.choice(corps) + rng.choice(fins)
    mots = texte.split()
    return " ".join(mots[: max(3, len(mots) // 3)]) + rng.choice(fins)


# -----------------------------------------------------------------------------
# Referentiels
# -----------------------------------------------------------------------------


def generer_utilisateurs(rng: random.Random, nombre: int = 60) -> list[dict]:
    utilisateurs = []
    vus: set[str] = set()
    for i in range(nombre):
        prenom, nom = rng.choice(PRENOMS), rng.choice(NOMS)
        base = f"{prenom.lower()}.{sans_accent(nom).lower()}"
        identifiant = base
        suffixe = 2
        while identifiant in vus:
            identifiant = f"{base}{suffixe}"
            suffixe += 1
        vus.add(identifiant)
        direction, vip_direction = rng.choice(DIRECTIONS)
        utilisateurs.append({
            "utilisateur_id": f"USR-{i + 1:04d}",
            "identifiant": identifiant,
            "nom_complet": f"{prenom} {nom}",
            "courriel": f"{identifiant}@organisation.mg",
            "direction": direction,
            "site": rng.choice(SITES),
            "telephone": f"+261 34 {rng.randrange(10, 99)} {rng.randrange(100, 999)} {rng.randrange(10, 99)}",
            "vip": vip_direction or rng.random() < 0.05,
            "statut": "actif" if rng.random() > 0.06 else "inactif",
        })
    return utilisateurs


def generer_equipements(rng: random.Random, utilisateurs: list[dict]) -> list[dict]:
    equipements = []
    compteur = 1
    for u in utilisateurs:
        type_court, modele = rng.choice(MODELES_POSTE)
        anciennete = rng.randrange(0, 8)
        equipements.append({
            "equipement_id": f"{type_court}-{compteur:04d}",
            "type": "poste_de_travail",
            "modele": modele,
            "utilisateur_id": u["utilisateur_id"],
            "site": u["site"],
            "date_mise_en_service": (
                datetime(2026, 8, 13) - timedelta(days=anciennete * 365 + rng.randrange(0, 364))
            ).date().isoformat(),
            "garantie_active": anciennete < 3,
            "criticite": "haute" if u["vip"] else rng.choice(["moyenne", "basse", "moyenne"]),
        })
        compteur += 1

    # Peripheriques partages, rattaches a un site et non a une personne.
    for i in range(14):
        type_court, modele = rng.choice(MODELES_PERIPH)
        equipements.append({
            "equipement_id": f"{type_court}-{i + 1:03d}",
            "type": "imprimante" if type_court == "IMP" else "scanner",
            "modele": modele,
            "utilisateur_id": "",
            "site": rng.choice(SITES),
            "date_mise_en_service": (
                datetime(2026, 8, 13) - timedelta(days=rng.randrange(200, 2400))
            ).date().isoformat(),
            "garantie_active": rng.random() < 0.4,
            "criticite": "moyenne",
        })
    return equipements


# -----------------------------------------------------------------------------
# Tickets
# -----------------------------------------------------------------------------


def choisir_gabarit(categorie: str, rng: random.Random):
    candidats = [g for g in GABARITS if g[0] == categorie]
    return rng.choice(candidats)


def generer_tickets(
    rng: random.Random, utilisateurs: list[dict], equipements: list[dict], nombre: int
) -> tuple[list[dict], dict]:
    postes = [e for e in equipements if e["type"] == "poste_de_travail"]
    imprimantes = [e for e in equipements if e["type"] == "imprimante"]
    categories = list(POIDS_CATEGORIES)
    poids = [POIDS_CATEGORIES[c] for c in categories]

    nb_ood = int(nombre * PART_HORS_DISTRIBUTION)
    nb_mal = int(nombre * PART_MALVEILLANTS)
    nb_normaux = nombre - nb_ood - nb_mal

    compteurs = {
        "fautes": 0, "vagues": 0, "etiquettes_bruitees": 0,
        "champs_manquants": 0, "priorites_incoherentes": 0,
        "hors_distribution": nb_ood, "malveillants": nb_mal,
    }
    tickets: list[dict] = []
    debut_periode = datetime(2026, 2, 1)

    def enveloppe(idx: int, texte: str, categorie: str, priorite: str,
                  docs: list[str], nature: str) -> dict:
        utilisateur = rng.choice(utilisateurs)
        poste = rng.choice(postes)
        soumission = debut_periode + timedelta(
            days=rng.randrange(0, 193), hours=rng.randrange(7, 19), minutes=rng.randrange(0, 60)
        )
        ticket = {
            "ticket_id": f"TCK-{idx:06d}",
            "description": texte,
            "auteur": utilisateur["identifiant"],
            "auteur_id": utilisateur["utilisateur_id"],
            "equipement_id": poste["equipement_id"],
            "date_soumission": soumission.isoformat(timespec="seconds"),
            "canal": rng.choice(["portail", "courriel", "telephone", "guichet"]),
            "categorie_reelle": categorie,
            "priorite_reelle": priorite,
            "equipe_reelle": ROUTAGE[categorie],
            "documents_pertinents": docs,
            "nature": nature,
        }
        # Valeurs manquantes (section 7).
        if rng.random() < TAUX_CHAMPS_MANQUANTS:
            champ = rng.choice(["equipement_id", "canal", "auteur_id"])
            ticket[champ] = ""
            compteurs["champs_manquants"] += 1
        return ticket

    idx = 1

    # --- tickets ordinaires ---
    for _ in range(nb_normaux):
        categorie = rng.choices(categories, weights=poids, k=1)[0]
        _, priorite_ref, docs, modeles = choisir_gabarit(categorie, rng)
        texte = rng.choice(modeles)

        texte = texte.format(
            poste=rng.choice(postes)["equipement_id"],
            imprimante=rng.choice(imprimantes)["equipement_id"] if imprimantes else "IMP-001",
            application=rng.choice(APPLICATIONS),
            direction=rng.choice(DIRECTIONS)[0],
            site=rng.choice(SITES),
            utilisateur=rng.choice(utilisateurs)["identifiant"],
        )

        # Formulations vagues (section 7).
        if rng.random() < TAUX_VAGUE:
            texte = rendre_vague(texte, rng)
            compteurs["vagues"] += 1
        # Fautes d orthographe (section 7).
        if rng.random() < TAUX_FAUTES:
            texte = introduire_fautes(texte, rng)
            compteurs["fautes"] += 1

        priorite = priorite_ref
        # Tickets similaires associes a des priorites differentes (section 7).
        if rng.random() < TAUX_PRIORITE_INCOHERENTE:
            voisines = [p for p in PRIORITES if p != priorite_ref]
            priorite = rng.choice(voisines)
            compteurs["priorites_incoherentes"] += 1

        categorie_etiquetee = categorie
        # Etiquettes imparfaites (section 7).
        if rng.random() < TAUX_ETIQUETTE_BRUITEE:
            autres = [c for c in categories if c != categorie]
            categorie_etiquetee = rng.choice(autres)
            compteurs["etiquettes_bruitees"] += 1

        t = enveloppe(idx, texte, categorie_etiquetee, priorite, docs, "ordinaire")
        t["categorie_vraie_sans_bruit"] = categorie
        tickets.append(t)
        idx += 1

    # --- exemples inhabituels (section 7) ---
    for _ in range(nb_ood):
        texte = rng.choice(HORS_DISTRIBUTION)
        t = enveloppe(idx, texte, "autre_indetermine", "basse", [], "hors_distribution")
        t["categorie_vraie_sans_bruit"] = "autre_indetermine"
        tickets.append(t)
        idx += 1

    # --- instructions malveillantes (sections 6 et 7) ---
    for _ in range(nb_mal):
        texte = rng.choice(TICKETS_MALVEILLANTS).format(
            utilisateur=rng.choice(utilisateurs)["identifiant"]
        )
        t = enveloppe(idx, texte, "cybersecurite", "critique", ["KB-SEC-03"], "malveillant")
        t["categorie_vraie_sans_bruit"] = "cybersecurite"
        tickets.append(t)
        idx += 1

    rng.shuffle(tickets)
    return tickets, compteurs


# -----------------------------------------------------------------------------
# Ecriture
# -----------------------------------------------------------------------------


def ecrire_csv(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(lignes[0]))
        writer.writeheader()
        writer.writerows(lignes)


def ecrire_json(chemin: Path, donnees) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ecrire_jsonl(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8") as f:
        for ligne in lignes:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


def ecrire_base_connaissances() -> None:
    dossier = SORTIE / "base_connaissances"
    dossier.mkdir(parents=True, exist_ok=True)
    index = []
    for article in BASE_CONNAISSANCES:
        entete = (
            f"# {article['titre']}\n\n"
            f"Identifiant : {article['doc_id']}\n"
            f"Categorie : {article['categorie']}\n"
            f"Type : {article['type']}\n"
            f"Mots-cles : {', '.join(article['mots_cles'])}\n\n"
        )
        (dossier / f"{article['doc_id']}.md").write_text(
            entete + article["contenu"] + "\n", encoding="utf-8"
        )
        index.append({k: v for k, v in article.items() if k != "contenu"})
    ecrire_json(dossier / "index.json", index)


def ecrire_metadonnees(compteurs: dict, tickets: list[dict], graine: int) -> None:
    repartition: dict[str, int] = {}
    for t in tickets:
        repartition[t["categorie_reelle"]] = repartition.get(t["categorie_reelle"], 0) + 1

    lignes = [
        "# Jeu de donnees du prototype",
        "",
        "La section 7 du sujet annonce un ensemble de ressources sans le fournir.",
        "Ce jeu de donnees le reconstitue et reproduit volontairement les defauts que",
        "cette meme section annonce, avec des taux connus. Disposer de la verite",
        "terrain sur le bruit permet de mesurer la robustesse defaut par defaut.",
        "",
        f"Genere par `data/synthetic/generer.py`, graine {graine} : la generation est",
        "reproductible a l identique.",
        "",
        "## Contenu",
        "",
        "| Fichier | Description |",
        "|---|---|",
        "| `tickets_historiques.jsonl` | historique de tickets etiquetes |",
        "| `base_connaissances/` | articles de la base de connaissances au format Markdown |",
        "| `base_connaissances/index.json` | index des articles avec leurs metadonnees |",
        "| `utilisateurs.csv` | inventaire fictif des utilisateurs |",
        "| `equipements.csv` | inventaire fictif du parc |",
        "| `services.csv` | liste des services informatiques et leurs delais |",
        "| `incidents_actifs.json` | incidents globaux en cours |",
        "",
        "## Defauts injectes volontairement",
        "",
        "| Defaut annonce par la section 7 | Taux vise | Occurrences |",
        "|---|---|---|",
        f"| Fautes d orthographe | {TAUX_FAUTES:.0%} | {compteurs['fautes']} |",
        f"| Formulations vagues ou informelles | {TAUX_VAGUE:.0%} | {compteurs['vagues']} |",
        f"| Valeurs manquantes | {TAUX_CHAMPS_MANQUANTS:.0%} | {compteurs['champs_manquants']} |",
        f"| Etiquettes imparfaites | {TAUX_ETIQUETTE_BRUITEE:.0%} | {compteurs['etiquettes_bruitees']} |",
        f"| Tickets similaires, priorites differentes | {TAUX_PRIORITE_INCOHERENTE:.0%} | {compteurs['priorites_incoherentes']} |",
        f"| Exemples inhabituels | {PART_HORS_DISTRIBUTION:.0%} | {compteurs['hors_distribution']} |",
        f"| Instructions malveillantes | {PART_MALVEILLANTS:.0%} | {compteurs['malveillants']} |",
        "| Categories desequilibrees | voir ci-dessous | - |",
        "",
        "Le champ `categorie_vraie_sans_bruit` conserve l etiquette exacte avant",
        "injection du bruit d etiquetage. Il sert a mesurer le plafond de performance",
        "atteignable, mais n est jamais utilise a l entrainement.",
        "",
        "## Repartition des categories",
        "",
        "| Categorie | Tickets | Part |",
        "|---|---|---|",
    ]
    total = len(tickets)
    for categorie, n in sorted(repartition.items(), key=lambda x: -x[1]):
        lignes.append(f"| {categorie} | {n} | {n / total:.1%} |")
    lignes += [
        f"| **Total** | **{total}** | 100 % |",
        "",
        "## Regeneration",
        "",
        "```bash",
        "python data/synthetic/generer.py --graine 1789 --tickets 420",
        "```",
    ]
    (SORTIE / "METADONNEES.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")


# -----------------------------------------------------------------------------


def main() -> None:
    parseur = argparse.ArgumentParser(description="Genere le jeu de donnees du prototype")
    parseur.add_argument("--graine", type=int, default=1789)
    parseur.add_argument("--tickets", type=int, default=420)
    arguments = parseur.parse_args()

    rng = random.Random(arguments.graine)
    SORTIE.mkdir(parents=True, exist_ok=True)

    utilisateurs = generer_utilisateurs(rng)
    equipements = generer_equipements(rng, utilisateurs)
    tickets, compteurs = generer_tickets(rng, utilisateurs, equipements, arguments.tickets)

    ecrire_csv(SORTIE / "utilisateurs.csv", utilisateurs)
    ecrire_csv(SORTIE / "equipements.csv", equipements)
    ecrire_csv(SORTIE / "services.csv", [
        {"service_id": i, "equipe": e, "libelle": lib, "sla_minutes": sla}
        for i, e, lib, sla in SERVICES
    ])
    ecrire_json(SORTIE / "incidents_actifs.json", INCIDENTS_ACTIFS)
    ecrire_jsonl(SORTIE / "tickets_historiques.jsonl", tickets)
    ecrire_base_connaissances()
    ecrire_metadonnees(compteurs, tickets, arguments.graine)

    print(f"Jeu de donnees genere dans {SORTIE}")
    print(f"  {len(utilisateurs):>4} utilisateurs")
    print(f"  {len(equipements):>4} equipements")
    print(f"  {len(SERVICES):>4} services informatiques")
    print(f"  {len(INCIDENTS_ACTIFS):>4} incidents actifs")
    print(f"  {len(BASE_CONNAISSANCES):>4} articles de base de connaissances")
    print(f"  {len(tickets):>4} tickets historiques")
    print("  defauts injectes :")
    for nom, valeur in compteurs.items():
        print(f"     {nom:<24} {valeur:>4}")


if __name__ == "__main__":
    main()
