"""Verifie l'acces effectif aux modeles de langage.

Interroge chaque provider configure avec une requete minimale et rend compte de
sa disponibilite reelle, de sa latence et de sa capacite a produire du JSON
valide. A lancer avant toute demonstration : une cle presente dans `.env` ne
garantit pas qu'elle fonctionne.

    python scripts/diagnostic_llm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import maii  # noqa: F401,E402  charge le fichier .env
from maii.llm.provider import LLMClient, extraire_json  # noqa: E402

SYSTEME = (
    "Tu es un assistant de support informatique. "
    "Tu reponds uniquement par un objet JSON valide, sans texte autour."
)
DEMANDE = (
    'Classe ce ticket et reponds au format {"categorie": ..., "priorite": ...}. '
    "Categories possibles : comptes_authentification, reseau_connectivite, "
    "materiel_informatique, logiciels_applications, imprimantes_peripheriques, "
    "droits_acces, cybersecurite, autre_indetermine. "
    "Priorites possibles : critique, haute, moyenne, basse.\n\n"
    "Ticket : « Mon compte est verrouille apres plusieurs tentatives, "
    "je suis bloque et j ai une reunion dans une heure. »"
)


def main() -> int:
    client = LLMClient()

    print("Configuration detectee")
    print("-" * 68)
    for p in client.diagnostic():
        etat = "configure" if p["disponible"] else f"indisponible ({p['motif']})"
        print(f"  {p['provider']:<10} {p['modele']:<28} {etat}")

    print("\nTest d'appel reel")
    print("-" * 68)

    resultats = []
    for provider in client.providers:
        if not provider.disponible:
            print(f"  {provider.nom:<10} ignore")
            continue

        isole = LLMClient()
        for autre in isole.providers:
            autre.disponible = autre.nom == provider.nom and provider.disponible

        reponse = isole.generer(SYSTEME, DEMANDE, json_attendu=True)
        if not reponse.ok:
            print(f"  {provider.nom:<10} ECHEC   {reponse.erreur}")
            continue

        charge = extraire_json(reponse.texte)
        json_ok = isinstance(charge, dict) and "categorie" in charge
        print(
            f"  {provider.nom:<10} OK      {reponse.latence_ms:>5} ms  "
            f"{reponse.tokens_entree + reponse.tokens_sortie:>4} jetons  "
            f"JSON {'valide' if json_ok else 'invalide'}"
        )
        if charge:
            print(f"             -> {charge}")
        resultats.append((provider.nom, json_ok))

    print("-" * 68)
    if not resultats:
        print("Aucun provider joignable : le systeme fonctionnera en mode regles seules.")
        return 1

    operationnels = [nom for nom, ok in resultats if ok]
    print(f"Providers operationnels : {', '.join(operationnels) or 'aucun'}")
    print(f"Mode retenu par defaut  : {LLMClient().mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
