# Jeu de donnees du prototype

La section 7 du sujet annonce un ensemble de ressources sans le fournir.
Ce jeu de donnees le reconstitue et reproduit volontairement les defauts que
cette meme section annonce, avec des taux connus. Disposer de la verite
terrain sur le bruit permet de mesurer la robustesse defaut par defaut.

Genere par `data/synthetic/generer.py`, graine 1789 : la generation est
reproductible a l identique.

## Contenu

| Fichier | Description |
|---|---|
| `tickets_historiques.jsonl` | historique de tickets etiquetes |
| `base_connaissances/` | articles de la base de connaissances au format Markdown |
| `base_connaissances/index.json` | index des articles avec leurs metadonnees |
| `utilisateurs.csv` | inventaire fictif des utilisateurs |
| `equipements.csv` | inventaire fictif du parc |
| `services.csv` | liste des services informatiques et leurs delais |
| `incidents_actifs.json` | incidents globaux en cours |

## Defauts injectes volontairement

| Defaut annonce par la section 7 | Taux vise | Occurrences |
|---|---|---|
| Fautes d orthographe | 22% | 102 |
| Formulations vagues ou informelles | 10% | 42 |
| Valeurs manquantes | 15% | 58 |
| Etiquettes imparfaites | 5% | 19 |
| Tickets similaires, priorites differentes | 8% | 31 |
| Exemples inhabituels | 3% | 12 |
| Instructions malveillantes | 2% | 8 |
| Categories desequilibrees | voir ci-dessous | - |

Le champ `categorie_vraie_sans_bruit` conserve l etiquette exacte avant
injection du bruit d etiquetage. Il sert a mesurer le plafond de performance
atteignable, mais n est jamais utilise a l entrainement.

## Repartition des categories

| Categorie | Tickets | Part |
|---|---|---|
| comptes_authentification | 93 | 22.1% |
| reseau_connectivite | 68 | 16.2% |
| logiciels_applications | 66 | 15.7% |
| imprimantes_peripheriques | 64 | 15.2% |
| materiel_informatique | 53 | 12.6% |
| cybersecurite | 36 | 8.6% |
| autre_indetermine | 21 | 5.0% |
| droits_acces | 19 | 4.5% |
| **Total** | **420** | 100 % |

## Regeneration

```bash
python data/synthetic/generer.py --graine 1789 --tickets 420
```
