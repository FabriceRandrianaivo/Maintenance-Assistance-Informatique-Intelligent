# Rapport technique

**mAIntenance & Assistance** — assistant intelligent de support informatique
ISPM — Hackathon AI Engineering & Machine Learning

Ce rapport répond aux six points exigés par la section 9 du sujet : approche de
routage, fonctionnement du RAG, outils accessibles à l'agent, stratégie
d'évaluation, mécanismes de sécurité, limites connues.

---

## Démonstration en ligne

**https://maintenance-assistance-informatique-intelligent.streamlit.app**

Le prototype est déployé et accessible sans installation. Les quatre scénarios
de la section 8 y sont pré-remplis.

---

## NB préliminaires

> **NB — Les ressources de la section 7 n'étaient pas jointes au sujet.**
> L'énoncé annonce un historique de tickets, une base de connaissances, un
> inventaire, une liste de services et une liste d'incidents actifs. Aucun de
> ces fichiers n'accompagnait le sujet, et aucun lien n'y figure. Le corpus a
> donc été reconstitué (§7 de ce rapport). Ce choix est assumé et il a une
> contrepartie favorable : disposant de la vérité terrain sur le bruit injecté,
> nous pouvons situer chaque résultat par rapport au plafond réellement
> atteignable.

> **NB — Le prototype se lance et se corrige sans aucune clé d'API.**
> Sans clé, le système bascule sur son mode dégradé et reste fonctionnel :
> `.\run.ps1` suffit à reproduire les quatre scénarios.

---

## 1. Approche choisie pour analyser et router les tickets

### 1.1 Trois voies, un arbitrage en code

| Voie | Technique | Ce qu'elle apporte | Ce qu'elle ne sait pas faire |
|---|---|---|---|
| **A — Règles** | dictionnaire d'expressions pondérées | instantanée, explicable, disponible sans réseau ni apprentissage | couverture faible sur les formulations vagues |
| **B — Supervisée** | TF-IDF (mots 1-2 + caractères 3-5) → régression logistique calibrée | apprend le vocabulaire réel, résiste aux fautes, produit des probabilités exploitables | dépend d'un historique étiqueté |
| **C — Générative** | modèle de langage, exemples choisis par similarité | comprend l'implicite et l'inhabituel | latence, coût, non déterminisme |

L'arbitrage est **entièrement déterministe** : fusion pondérée des
distributions, puis application de règles impératives, puis décision
d'abstention. Ce choix est délibéré — une décision doit pouvoir être rejouée et
expliquée ligne à ligne, et une règle métier ne doit pas dépendre d'un modèle
génératif. **Les modèles proposent, le code décide.**

### 1.2 Pourquoi les n-grammes de caractères

La section 7 annonce des fautes d'orthographe, et notre corpus en contient 102.
Un vectoriseur par mots ne voit aucun rapport entre « imprimante » et
« imprimente ». Leurs n-grammes de caractères, eux, se recouvrent presque
entièrement. La robustesse est ainsi obtenue **sans correction orthographique**,
laquelle introduirait ses propres erreurs.

### 1.3 Ce que l'ablation a changé dans l'architecture

C'est le résultat le plus important de ce travail.

| Voie mesurée isolément | macro-F1 | exactitude |
|---|---|---|
| A — règles seules | 0,658 | 64,8 % |
| **B — modèle supervisé** | **0,857** | **86,7 %** |
| C — modèle de langage | 0,692 | 63,3 % |
| A+B+C — fusion systématique | 0,803 | 81,7 % |

> **NB — La fusion naïve des trois voies dégradait le résultat.** Sur
> l'échantillon commun, le modèle supervisé seul atteint 0,881 quand la fusion
> à trois voix retombe à 0,803. Faire voter le modèle de langage sur chaque
> ticket **détériorait** la classification.

L'architecture a donc été revue : le modèle de langage n'est plus un votant
permanent mais un **recours**, sollicité uniquement lorsque le modèle supervisé
doute (confiance < 0,60), lorsque les voies se contredisent, ou lorsque le
ticket ne ressemble à rien de connu. C'est précisément là qu'il apporte quelque
chose.

Effet secondaire décisif : le nombre d'appels réseau chute d'environ trois
quarts, ce qui a supprimé le plafonnement de débit rencontré pendant
l'évaluation et divisé d'autant la latence moyenne.

**C'est la mesure qui a dicté l'architecture, pas l'inverse.**

### 1.4 Priorité et routage

La priorité fait l'objet d'un **modèle distinct**. Le sujet annonce que des
tickets similaires portent des priorités différentes : la priorité dépend donc
du contexte — périmètre, échéance, statut de l'utilisateur — et non du seul
symptôme. Un modèle unique prédisant un couple les confondrait.

La priorité proposée par les modèles est ensuite arbitrée par des règles :

- marqueurs d'urgence relevés dans le texte ;
- contexte remonté par les outils de consultation — utilisateur VIP, matériel
  critique, service déclaré dégradé ;
- rattachement à un incident global, qui fait hériter le ticket de sa gravité ;
- **plancher par catégorie** : un incident de cybersécurité n'est jamais traité
  en priorité basse, même formulé sans emphase.

En cas de propositions divergentes, **la plus élevée l'emporte** : sous-estimer
l'urgence coûte plus cher que la surestimer.

Le routage vers l'équipe est une table déterministe, sans aucun modèle : c'est
une règle métier, elle doit être auditable et modifiable sans réapprentissage.

### 1.5 Abstention et hors distribution

- Sous 0,45 de confiance, le système **ne tranche pas** : catégorie
  `autre_indetermine` et validation humaine. Exception : jamais d'abstention sur
  un signal de sécurité — mieux vaut escalader à tort que laisser passer.
- La détection hors distribution repose sur la distance au centroïde de classe
  le plus proche, ce qui répond à la demande de la section 3.1 sur les tickets
  inhabituels.

---

## 2. Fonctionnement du système RAG

### 2.1 Découpage

Le découpage suit la **structure des documents**, section par section, et non un
nombre fixe de caractères. Dans une base de procédures, un titre délimite une
unité de sens complète ; couper une procédure au milieu de ses étapes produirait
des passages inexploitables et donc des réponses incomplètes. 27 articles → 83
passages, 204 caractères en moyenne.

Chaque passage porte le titre de son article et son identifiant. Cette
redondance est volontaire : un passage isolé perdrait tout contexte, et un
utilisateur citant « KB-SEC-02 » doit pouvoir retrouver le document.

### 2.2 Recherche hybride

```
BM25(requête) ─────┐
                   ├──▶ fusion de rangs réciproques (k=60) ──▶ 5 passages
TF-IDF cosinus ────┘
```

Les deux voies sont complémentaires : BM25 gagne sur les références exactes et
les sigles, les n-grammes de caractères sur les reformulations et les fautes. La
fusion **par rangs** évite d'avoir à normaliser une mesure BM25 non bornée face
à un cosinus dans [0, 1] — c'est son intérêt principal ici.

> **NB — Une voie sans signal ne vote pas.** Sur une requête truffée de fautes,
> aucun terme BM25 ne correspond : tous les scores sont nuls et l'ordre renvoyé
> est arbitraire. Le créditer revenait à injecter 25 passages tirés au hasard,
> qui noyaient le classement vectoriel, pourtant le seul pertinent. Cette
> correction a porté le rappel de la catégorie `droits_acces` de 94,7 % à 100 %.

### 2.3 Pourquoi pas d'embeddings neuronaux

Le corpus compte 83 passages pour un vocabulaire technique fermé. Un modèle
d'embeddings imposerait plusieurs centaines de mégaoctets à télécharger — un
point de défaillance réel un jour d'épreuve — pour un gain non démontré à cette
échelle. Le choix retenu atteint **89,2 % de rappel@5, hors ligne et de manière
déterministe**. La limite est assumée : sur un corpus dix fois plus grand et un
vocabulaire ouvert, la conclusion s'inverserait probablement.

### 2.4 Citations et abstention

Chaque passage porte une référence de la forme `KB-NET-04#c2`. Les étapes de
résolution ne sont produites **qu'à partir des passages effectivement
retrouvés**, et chacune porte sa source.

Lorsque la confiance de recherche tombe sous 0,30, le système **s'abstient** :
il ne propose aucune étape, signale la réponse comme incertaine et escalade.
C'est le garde-fou anti-hallucination le plus important, la section 6 citant
« génération d'une procédure inexistante » parmi les risques majeurs.

---

## 3. Outils accessibles à l'agent

Huit outils, adossés aux référentiels du projet.

| Outil | Type | Garde-fou spécifique |
|---|---|---|
| `rechercher_utilisateur` | consultation | le téléphone n'est jamais remonté |
| `consulter_equipement` | consultation | — |
| `verifier_etat_service` | consultation | — |
| `rechercher_incidents_actifs` | consultation | — |
| `creer_ticket` | action | paramètres validés avant exécution |
| `mettre_a_jour_ticket` | action | ticket inexistant → erreur exploitable |
| `affecter_ticket` | action | équipe vérifiée dans le référentiel |
| `escalader_vers_technicien` | action | **sensible : validation humaine obligatoire** |

Les quatre exigences de la section 5.2 :

- **Sélection raisonnée** — seuls les outils dont les paramètres sont
  effectivement disponibles sont appelés. Interroger l'annuaire sans identifiant
  produirait un échec prévisible, consommerait du budget et polluerait la trace.
- **Validation des paramètres** — chaque outil déclare un schéma Pydantic. Un
  argument invalide **n'atteint jamais le backend** et produit un message
  d'erreur réinjectable à l'agent.
- **Gestion des erreurs** — aucune exception ne remonte : toute erreur devient
  un appel au statut `erreur`. Le traitement du ticket n'est jamais interrompu.
- **Contrôle du nombre d'actions** — plafond de 8 appels par ticket, appliqué
  par construction et non par surveillance.

Chaque appel est journalisé avec ses paramètres, son résultat et son statut,
conformément à la section 3.4.

---

## 4. Stratégie d'évaluation

### 4.1 Classification

Séparation stratifiée 75/25 sur 420 tickets. Métrique principale : **macro-F1**,
et non l'exactitude — les classes sont volontairement déséquilibrées (24 % à
3 %), et l'exactitude récompenserait un modèle ignorant les classes rares.

La voie générative est évaluée sur un échantillon stratifié de 60 tickets :
chaque prédiction coûte un appel réseau.

### 4.2 Recherche documentaire

Le rappel est mesuré sur **400 tickets réels** portant leur vérité terrain — les
articles censés y répondre — et non sur des requêtes rédigées après coup, qui
flatteraient l'index.

| Métrique | Valeur |
|---|---|
| Rappel@5 | 89,2 % |
| Rappel@3 | 87,5 % |
| Rappel@1 | 78,8 % |
| MRR | 0,833 |

### 4.3 Scénarios obligatoires

Les quatre scénarios de la section 8 sont scriptés avec leurs **points de
contrôle vérifiés programmatiquement** (`scripts/demo_scenarios.py`). Le script
échoue si un contrôle n'est pas respecté : il sert donc de test de bout en bout.

| Scénario | Comportement obtenu |
|---|---|
| Incident courant | `KB-IMP-01` citée, 6 étapes, `resolution`, ticket affecté |
| Incident urgent | priorité `critique`, `escalade` retenue en attente de validation |
| Demande incomplète | `demande_information`, 3 questions ciblées, aucune source inventée |
| Demande malveillante | injection détectée, `escalade`, **aucun outil appelé** |

### 4.4 Observabilité

Un `trace_id` par ticket, un span par étape, portant entrée, sortie, latence,
jetons, coût estimé, statut et erreur. Double sortie : `observability/traces.jsonl`
et une table SQLite interrogée par l'onglet Observabilité de l'interface.

### 4.5 Tests

63 tests automatisés couvrent les contrats, le traçage, l'extraction JSON, la
cohérence du jeu de données, la normalisation, le découpage, la recherche et le
registre d'outils. Exécutés à chaque poussée et chaque *pull request*.

---

## 5. Mécanismes de sécurité

### 5.1 Le principe

> **NB — Les garde-fous sont appliqués en code, jamais confiés à une consigne
> de prompt.** `validation_humaine_requise` est forcé **après** la génération.
> Un ticket qui manipule le modèle ne peut pas désactiver la règle, puisque le
> modèle n'a aucune prise dessus. C'est ce qui fait tenir le scénario 4.

### 5.2 Couverture des sept risques de la section 6

| Risque | Contre-mesure |
|---|---|
| Données personnelles | détection (courriel, téléphone, IP, MAC, IBAN, mot de passe) puis **pseudonymisation avant tout envoi au modèle** ; restitution à l'affichage |
| Instructions malveillantes dans un ticket | 12 familles de motifs d'injection, score de risque, blocage au-delà du seuil |
| Instructions malveillantes dans un document | passages encadrés par des délimiteurs et déclarés non fiables dans le prompt |
| Procédure inexistante | seuil d'abstention documentaire, étapes produites uniquement à partir des passages retrouvés |
| Utilisation injustifiée d'un outil | appel conditionné à la disponibilité des paramètres, justification obligatoire, plafond de 8 appels |
| Modification d'un ticket sans autorisation | validation des paramètres, équipe vérifiée dans le référentiel |
| Traitement automatique d'un incident sensible | cybersécurité et droits d'accès forcés en validation humaine, plancher de priorité |

### 5.3 Le scénario 4 en détail

> **NB — L'absence d'appel d'outil sur le scénario 4 est le résultat attendu,
> pas une défaillance.** Le ticket combine quatre signaux d'injection
> (`consigne_ignorer`, `changement_role`, `mode_admin`, `sans_validation`). La
> chaîne s'interrompt avant l'étape de recherche : aucune action n'est
> déclenchée, le motif est consigné, la validation humaine est exigée et le
> dossier part au service sécurité. La trace le montre : elle ne contient aucun
> appel d'outil.

Le courriel présent dans le ticket est pseudonymisé avant tout traitement : il
n'est jamais transmis au service externe.

---

## 6. Robustesse opérationnelle

Le fournisseur de modèle bascule automatiquement sur quatre niveaux :

| Rang | Provider | Rôle |
|---|---|---|
| 1 | Groq `llama-3.3-70b-versatile` | primaire, ~1 100 ms |
| 2 | Gemini `gemini-3.5-flash` | secours réseau |
| 3 | Ollama `qwen2.5:7b-instruct` | secours hors ligne |
| 4 | *aucun* | règles + BM25 + TF-IDF — **le système reste fonctionnel** |

Deux comportements ont été ajoutés après observation en conditions réelles :

- **Réparation des réponses JSON tronquées.** Un modèle atteignant sa limite de
  sortie s'arrête au milieu de sa réponse ; les champs déjà écrits restent
  valides. Le parseur referme les chaînes ouvertes, retire une clé sans valeur
  et rééquilibre les délimiteurs. 12 tests couvrent les cas observés.
- **Reprise sur plafonnement de débit.** Une offre gratuite limite les appels
  par minute. Sans traitement, une évaluation en rafale écartait le provider dès
  les premières secondes et faussait les mesures — ce qui s'est effectivement
  produit lors de la première ablation.

---

## 7. Jeu de données

> **NB — Corpus reconstitué, section 7 du sujet non fournie.**

Six ressources générées : 420 tickets étiquetés, 27 articles de base de
connaissances, 60 utilisateurs, 74 équipements, 6 services, 4 incidents actifs.
Génération reproductible à l'identique (graine 1789).

Les défauts annoncés par la section 7 sont **injectés volontairement**, à taux
paramétrés et journalisés :

| Défaut annoncé | Occurrences |
|---|---|
| Fautes d'orthographe | 102 |
| Valeurs manquantes | 58 |
| Formulations vagues | 42 |
| Priorités incohérentes sur tickets similaires | 31 |
| Étiquettes imparfaites | 19 |
| Exemples inhabituels | 12 |
| Instructions malveillantes | 8 |
| Catégories déséquilibrées | 24 % → 3 % |

Les procédures de la base répondent effectivement aux symptômes décrits par les
tickets, et chaque ticket référence ses articles pertinents : c'est ce lien qui
constitue la vérité terrain de l'évaluation documentaire.

---

## 8. Limites connues

1. **La sélection des outils est déterministe, pas raisonnée par un modèle.**
   L'agent appelle les outils dont les paramètres sont disponibles, puis celui
   qui correspond à sa décision. Fiable et traçable, mais incapable de composer
   une séquence inédite face à une situation imprévue.

2. **Le seuil d'abstention documentaire n'est pas calibré.** L'écart entre une
   requête légitime difficile (0,207) et une requête hors corpus (0,143) est
   trop mince pour une valeur fixée à l'œil. Une calibration sur un jeu de
   développement dédié était prévue ; le temps a manqué.

3. **`autre_indetermine` : 11 % de rappel documentaire.** Comportement correct —
   une demande vide ne doit rien retrouver de confiant — mais ces tickets
   devraient court-circuiter la recherche plutôt que la lancer pour rien.

4. **La voie générative est évaluée sur 60 tickets**, contre 105 pour les
   autres. Chaque prédiction coûte un appel réseau.

5. **L'extraction d'entités est purement lexicale.** Elle est muette sur les
   formulations ne citant aucun identifiant connu, ce qui gonfle mécaniquement
   la liste des informations manquantes sur les tickets rédigés en langage
   courant.

6. **Aucune évaluation adversariale chiffrée.** Les mécanismes anti-injection
   sont implémentés et testés unitairement, mais le jeu red-team d'une trentaine
   d'attaques prévu au plan n'a pas été constitué. Le taux de succès d'attaque
   n'est donc pas mesuré, seulement contrôlé sur le scénario 4.

---

## 9. Ce que nous retenons

Le résultat le plus utile de ce travail n'est pas un score mais une correction
d'architecture. Nous avions supposé qu'une fusion de trois méthodes vaudrait
mieux que la meilleure d'entre elles. **La mesure a dit le contraire**, et
l'architecture a été revue en conséquence : le modèle de langage est devenu un
recours plutôt qu'un votant.

C'est aussi ce que la note de cadrage du sujet suggérait — une approche simple,
correctement justifiée et évaluée, plutôt qu'une approche complexe mal maîtrisée.
