# Lenteur reseau et temps de reponse degrades

Identifiant : KB-NET-02
Categorie : reseau_connectivite
Type : procedure
Mots-cles : lenteur, lent, ralenti, debit, temps de reponse

## Objet
Traiter une plainte de lenteur reseau.

## Qualification prealable
Determiner si la lenteur touche un seul utilisateur, un etage, un site entier,
ou une application en particulier. Cette distinction oriente tout le diagnostic.

## Diagnostic
1. Consulter la liste des incidents actifs : une lenteur generalisee correspond
   souvent a un incident deja ouvert.
2. Mesurer le temps de reponse vers la passerelle puis vers le serveur applicatif.
3. Verifier le taux d occupation du lien inter-sites.
4. Verifier qu aucune sauvegarde ou synchronisation massive n est en cours.

## Resolution
Une lenteur limitee a un poste releve generalement du poste lui-meme. Une lenteur
touchant plusieurs utilisateurs d un meme site doit etre escaladee vers l equipe
infrastructure avec le perimetre constate.
