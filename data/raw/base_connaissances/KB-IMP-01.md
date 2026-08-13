# Impression impossible depuis un poste

Identifiant : KB-IMP-01
Categorie : imprimantes_peripheriques
Type : procedure
Mots-cles : imprimer, impression, ne sort pas, imprimante

## Objet
Retablir l impression depuis un poste de travail.

## Procedure
1. Verifier que l imprimante est allumee, en ligne et sans message d erreur.
2. Verifier que la file d attente locale ne contient pas un travail bloque.
3. Vider la file d attente et relancer le service d impression du poste.
4. Verifier que l imprimante selectionnee par defaut est la bonne.
5. Imprimer une page de test depuis les proprietes de l imprimante.
6. Reinstaller la file d impression depuis le serveur si necessaire.

## Escalade
Si plusieurs utilisateurs ne peuvent plus imprimer sur la meme imprimante,
verifier l etat du serveur d impression avant toute intervention sur les postes.
