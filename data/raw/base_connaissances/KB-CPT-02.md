# Deverrouiller un compte apres echecs de connexion

Identifiant : KB-CPT-02
Categorie : comptes_authentification
Type : procedure
Mots-cles : compte verrouille, bloque, tentatives, echec connexion

## Objet
Deverrouiller un compte bloque apres depassement du nombre de tentatives autorisees.

## Contexte
La politique du domaine verrouille un compte apres cinq echecs consecutifs. Le
deverrouillage automatique intervient au bout de trente minutes.

## Procedure
1. Confirmer l identite de l utilisateur.
2. Consulter le journal d authentification pour identifier l origine des echecs.
3. Si les echecs proviennent d un poste inhabituel ou d une adresse externe,
   ne pas deverrouiller et escalader immediatement au service securite.
4. Sinon deverrouiller le compte depuis la console d administration.
5. Verifier avec l utilisateur que la connexion fonctionne.
6. Rappeler que les identifiants enregistres sur un ancien telephone ou un
   client de messagerie provoquent souvent des verrouillages repetes.
