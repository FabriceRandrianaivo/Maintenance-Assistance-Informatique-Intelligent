# Reinitialiser un mot de passe utilisateur

Identifiant : KB-CPT-01
Categorie : comptes_authentification
Type : procedure
Mots-cles : mot de passe, oublie, reinitialisation, connexion

## Objet
Reinitialiser le mot de passe d un compte du domaine lorsque l utilisateur l a oublie.

## Prerequis
L identite de l utilisateur doit etre verifiee avant toute action. Cette operation
modifie un acces et requiert la validation d un technicien habilite.

## Procedure
1. Verifier l identite du demandeur par un canal distinct de la demande initiale.
2. Ouvrir la console d administration des comptes et rechercher l identifiant.
3. Verifier que le compte n est pas verrouille ; le cas echeant appliquer KB-CPT-02.
4. Declencher la reinitialisation avec l option de changement obligatoire a la
   premiere connexion.
5. Communiquer le mot de passe provisoire par un canal distinct du courriel.
6. Consigner l operation dans le ticket et cloturer.

## Points de vigilance
Ne jamais transmettre un mot de passe provisoire a un tiers, ni par courriel, ni
par messagerie instantanee. Toute demande de reinitialisation portant sur un
compte autre que celui du demandeur doit etre escaladee au service securite.
