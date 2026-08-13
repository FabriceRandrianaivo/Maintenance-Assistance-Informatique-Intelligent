# mAIntenance & Assistance

Assistant intelligent de support informatique : un ticket decrit en langage
naturel entre, une decision structuree, justifiee et controlable en sort.

**ISPM â€” Hackathon AI Engineering & Machine Learning**

---

## Lancer le prototype

```powershell
.\run.ps1                 # installe, prepare les donnees, lance l'interface
.\run.ps1 -Scenarios      # rejoue les quatre scenarios obligatoires
.\run.ps1 -Evaluer        # entraine, indexe et publie les mesures
```

L'interface s'ouvre sur `http://localhost:8501`.

Le systeme **fonctionne sans aucune cle d'API** : il bascule alors en mode
regles et recherche lexicale. Pour activer la voie generative, copier
`.env.example` en `.env` et y renseigner une cle Groq ou Gemini.

---

## Architecture

```
Ticket en langage naturel
   â”‚
   â”œâ”€â–¶ 1. SECURITE      detection d'injection Â· pseudonymisation des donnees personnelles
   â”œâ”€â–¶ 2. CLASSIFICATION  regles + modele supervise + modele de langage â†’ arbitrage
   â”œâ”€â–¶ 3. DIAGNOSTIC     extraction d'entites Â· champs manquants Â· incident global correle
   â”œâ”€â–¶ 4. RECHERCHE      BM25 + TF-IDF â†’ fusion RRF â†’ citations, ou abstention
   â””â”€â–¶ 5. DECISION       sortie Pydantic Â· verrou des actions sensibles
   â”‚
   â””â”€â”€ chaque etape emet un span : entree, sortie, latence, jetons, cout, statut
```

| Module | Role |
|---|---|
| [`models/`](src/maii/models/schemas.py) | contrats Pydantic, source de verite unique |
| [`security/`](src/maii/security/garde_fous.py) | garde-fous appliques en code |
| [`classify/`](src/maii/classify/) | trois voies de classification et leur arbitrage |
| [`rag/`](src/maii/rag/) | decoupage, index hybride, recherche |
| [`agent/`](src/maii/agent/orchestrateur.py) | machine a etats du traitement |
| [`tools/`](src/maii/tools/registre.py) | registre des huit outils ITSM |
| [`observability/`](src/maii/observability/tracer.py) | traÃ§age des executions |
| [`llm/`](src/maii/llm/provider.py) | acces aux modeles, avec bascule |
| [`ui/`](ui/app.py) | interface de demonstration |

---

## Resultats mesures

### Classification â€” 420 tickets, separation stratifiee 75/25

| Voie | macro-F1 | exactitude |
|---|---|---|
| A â€” regles seules | 0,658 | 64,8 % |
| **B â€” modele supervise** | **0,857** | **86,7 %** |
| C â€” modele de langage | 0,692 | 63,3 % |
| A+B+C â€” arbitrage | 0,803 | 81,7 % |

**Plafond impose par le bruit d'etiquetage : 94,3 %** â€” 5,7 % des tickets de
test portent volontairement une etiquette fausse. Le modele supervise est donc
a 7,6 points de l'optimum atteignable, pas de 13.

### Recherche documentaire â€” 400 tickets a verite terrain

| Metrique | Valeur |
|---|---|
| Rappel@5 | **89,2 %** |
| Rappel@3 | 87,5 % |
| Rappel@1 | 78,8 % |
| MRR | **0,833** |

### Outils â€” 4 consultation, 4 action

| Outil | Type | Garde-fou |
|---|---|---|
| `rechercher_utilisateur` | consultation | le telephone n'est jamais remonte |
| `consulter_equipement` | consultation | â€” |
| `verifier_etat_service` | consultation | â€” |
| `rechercher_incidents_actifs` | consultation | â€” |
| `creer_ticket` | action | parametres valides avant execution |
| `mettre_a_jour_ticket` | action | ticket inexistant â†’ erreur exploitable |
| `affecter_ticket` | action | equipe verifiee dans le referentiel |
| `escalader_vers_technicien` | action | **sensible : validation humaine obligatoire** |

Chaque appel est journalise avec ses parametres, son resultat, son statut et sa
latence. Le plafond est de 8 appels par ticket. Un argument invalide n'atteint
jamais le backend : il produit une erreur reinjectable a l'agent.

### Scenarios obligatoires â€” **4/4 conformes**

| Scenario | Comportement obtenu |
|---|---|
| Incident courant | procedure `KB-IMP-01` citee, 6 etapes, `resolution`, ticket affecte |
| Incident urgent | priorite `critique`, `escalade` retenue en attente de validation |
| Demande incomplete | `demande_information`, 3 questions ciblees, aucune source inventee |
| Demande malveillante | injection detectee, `escalade`, **aucun outil appele** |

Sur le scenario 4, le refus intervient avant toute action : la trace ne contient
aucun appel d'outil. C'est le comportement recherche â€” un ticket qui tente de
manipuler l'assistant ne doit rien declencher du tout.

---

## Choix techniques et justifications

### Pourquoi pas d'embeddings neuronaux pour le RAG

Le corpus compte 83 passages pour un vocabulaire technique ferme. Un modele
d'embeddings imposerait plusieurs centaines de megaoctets a telecharger â€” un
point de defaillance reel un jour d'examen â€” pour un gain non demontre a cette
echelle. **BM25 + TF-IDF fusionnes par RRF atteignent 89 % de rappel@5, hors
ligne et de maniere deterministe.**

Les deux voies sont complementaires : BM25 gagne sur les references exactes
(`KB-SEC-02`, `IMP-003`), les n-grammes de caracteres absorbent les fautes de
frappe. La fusion par rangs evite d'avoir a normaliser un BM25 non borne face a
un cosinus dans [0, 1].

### Pourquoi le modele de langage n'est pas un votant permanent

L'ablation a tranche : le faire voter sur chaque ticket faisait **retomber
l'ensemble de 0,881 a 0,803**. Il est donc devenu un recours, sollicite
uniquement quand le modele supervise doute, quand les voies se contredisent ou
quand le ticket ne ressemble a rien de connu. Le nombre d'appels chute d'environ
trois quarts, ce qui supprime au passage le plafonnement de debit.

C'est la mesure qui a dicte l'architecture, pas l'inverse.

### Pourquoi les garde-fous sont en code et non dans le prompt

`validation_humaine_requise` est force **apres** la generation, dans
[`garde_fous.py`](src/maii/security/garde_fous.py). Un ticket qui manipule le
modele ne peut pas desactiver la regle, puisque le modele n'a aucune prise
dessus. C'est ce qui fait tenir le scenario 4.

### Pourquoi un orchestrateur ecrit a la main

La trace complete d'une decision compte pour un cinquieme de l'evaluation. Une
machine a etats de deux cents lignes se relit, se rejoue et se defend ; un
enchainement produit par une bibliotheque tierce se subit.

---

## Robustesse

Le fournisseur de modele bascule automatiquement sur quatre niveaux :

| Rang | Provider | Role |
|---|---|---|
| 1 | Groq `llama-3.3-70b-versatile` | primaire, ~1 100 ms |
| 2 | Gemini `gemini-3.5-flash` | secours reseau |
| 3 | Ollama `qwen2.5:7b-instruct` | secours hors ligne |
| 4 | *aucun* | regles + BM25 + TF-IDF, **le systeme reste fonctionnel** |

Le parseur repare les reponses JSON tronquees â€” cas observe en conditions
reelles â€” et un plafonnement de debit declenche une reprise avec attente
progressive au lieu d'ecarter le provider.

---

## Jeu de donnees

La section 7 du sujet annonce un ensemble de ressources sans le joindre. Il a
donc ete **reconstitue integralement**, avec les defauts que cette meme section
annonce, injectes a taux connus :

| Defaut | Occurrences |
|---|---|
| Fautes d'orthographe | 102 |
| Valeurs manquantes | 58 |
| Formulations vagues | 42 |
| Priorites incoherentes | 31 |
| Etiquettes imparfaites | 19 |
| Exemples inhabituels | 12 |
| Instructions malveillantes | 8 |

Disposer de la verite terrain sur le bruit permet de mesurer la robustesse
defaut par defaut, et de situer les resultats par rapport au plafond
atteignable. Generation reproductible : `python data/synthetic/generer.py
--graine 1789`. Detail dans [`data/raw/METADONNEES.md`](data/raw/METADONNEES.md).

---

## Limites connues

- **La selection des outils est deterministe, pas raisonnee par un modele.**
  L'agent appelle les outils de consultation dont les parametres sont
  disponibles, puis l'outil d'action correspondant a sa decision. Ce choix est
  fiable et tracable, mais il ne sait pas composer une sequence inedite face a
  une situation imprevue.
- **`autre_indetermine` : 11 % de rappel documentaire.** Comportement correct
  â€” une demande vide ne doit rien retrouver de confiant â€” mais ces tickets
  devraient court-circuiter la recherche.
- **Le seuil d'abstention documentaire n'est pas calibre.** L'ecart entre une
  requete legitime difficile (0,207) et une requete hors corpus (0,143) est
  trop mince pour une valeur fixee a l'oeil.
- **La voie generative est evaluee sur 60 tickets**, contre 105 pour les autres :
  chaque prediction coute un appel reseau.
- **L'extraction d'entites est purement lexicale**, donc muette sur les
  formulations qui ne citent aucun identifiant connu.

---

## Tests

```powershell
python -m pytest tests -q
```

63 tests couvrent les contrats, le traÃ§age, l'extraction JSON, le jeu de
donnees, la normalisation, le decoupage la recherche et le registre d outils. Executes
automatiquement sur chaque poussee et chaque pull request.

---

## Equipe

| Membre | Perimetre |
|---|---|
| Fabrice Randrianaivo | architecture, recherche documentaire, decision, orchestrateur |
| nyanjaraandria | interface de demonstration |
