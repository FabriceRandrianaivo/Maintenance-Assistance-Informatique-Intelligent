"""Chargement des ressources du projet.

Point d'entree unique vers les donnees. Tout le reste du code passe par ici, ce
qui permet de changer de source sans toucher aux composants : si un jeu de
donnees officiel devait remplacer le notre, seule cette couche serait a adapter.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

from maii import RACINE

BRUT = RACINE / "data" / "raw"


def _lire_csv(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _lire_jsonl(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    return [
        json.loads(ligne)
        for ligne in chemin.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]


def _lire_json(chemin: Path):
    if not chemin.exists():
        return []
    return json.loads(chemin.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def charger_tickets() -> list[dict]:
    """Historique de tickets etiquetes, utilise pour l'apprentissage et l'evaluation."""
    return _lire_jsonl(BRUT / "tickets_historiques.jsonl")


@lru_cache(maxsize=1)
def charger_utilisateurs() -> list[dict]:
    lignes = _lire_csv(BRUT / "utilisateurs.csv")
    for ligne in lignes:
        ligne["vip"] = str(ligne.get("vip", "")).strip().lower() in {"true", "1", "oui"}
    return lignes


@lru_cache(maxsize=1)
def charger_equipements() -> list[dict]:
    lignes = _lire_csv(BRUT / "equipements.csv")
    for ligne in lignes:
        ligne["garantie_active"] = (
            str(ligne.get("garantie_active", "")).strip().lower() in {"true", "1", "oui"}
        )
    return lignes


@lru_cache(maxsize=1)
def charger_services() -> list[dict]:
    lignes = _lire_csv(BRUT / "services.csv")
    for ligne in lignes:
        ligne["sla_minutes"] = int(ligne.get("sla_minutes") or 0)
    return lignes


@lru_cache(maxsize=1)
def charger_incidents_actifs() -> list[dict]:
    return _lire_json(BRUT / "incidents_actifs.json")


@lru_cache(maxsize=1)
def charger_articles() -> list[dict]:
    """Articles de la base de connaissances, contenu Markdown inclus."""
    dossier = BRUT / "base_connaissances"
    index = _lire_json(dossier / "index.json")
    articles = []
    for entree in index:
        chemin = dossier / f"{entree['doc_id']}.md"
        if not chemin.exists():
            continue
        articles.append({**entree, "contenu": chemin.read_text(encoding="utf-8")})
    return articles


def index_utilisateurs() -> dict[str, dict]:
    """Utilisateurs accessibles par identifiant, par courriel et par identifiant technique."""
    index: dict[str, dict] = {}
    for u in charger_utilisateurs():
        for cle in (u["utilisateur_id"], u["identifiant"], u["courriel"]):
            if cle:
                index[cle.lower()] = u
    return index


def index_equipements() -> dict[str, dict]:
    return {e["equipement_id"].lower(): e for e in charger_equipements()}


def index_services() -> dict[str, dict]:
    return {s["equipe"]: s for s in charger_services()}


def donnees_disponibles() -> bool:
    """Indique si les ressources ont ete generees."""
    return bool(charger_tickets()) and bool(charger_articles())


def resume_corpus() -> dict[str, int]:
    """Compte des ressources chargees, affiche au demarrage de l'interface."""
    return {
        "tickets": len(charger_tickets()),
        "articles": len(charger_articles()),
        "utilisateurs": len(charger_utilisateurs()),
        "equipements": len(charger_equipements()),
        "services": len(charger_services()),
        "incidents_actifs": len(charger_incidents_actifs()),
    }
