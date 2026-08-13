# Acces impossible a une application hebergee

Identifiant : KB-NET-04
Categorie : reseau_connectivite
Type : procedure
Mots-cles : application inaccessible, serveur, indisponible, erreur

## Objet
Traiter l impossibilite d atteindre une application hebergee au siege.

## Procedure
1. Verifier l etat du service concerne avant tout diagnostic poste.
2. Consulter la liste des incidents actifs.
3. Si le service est declare indisponible, rattacher le ticket a l incident global
   et informer l utilisateur du delai estime. Ne pas ouvrir de diagnostic poste.
4. Si le service est operationnel, verifier la resolution de nom depuis le poste
   puis l atteignabilite du serveur.
5. Verifier les droits d acces de l utilisateur sur l application.

## Escalade
Toute indisponibilite confirmee d un service partage est escaladee vers l equipe
infrastructure avec la priorite correspondant au nombre d utilisateurs impactes.
