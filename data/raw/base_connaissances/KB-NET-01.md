# Poste sans connexion reseau filaire

Identifiant : KB-NET-01
Categorie : reseau_connectivite
Type : procedure
Mots-cles : pas de connexion, cable, ethernet, reseau, deconnecte

## Objet
Diagnostiquer l absence de connexion reseau sur un poste raccorde en filaire.

## Diagnostic
1. Verifier l etat des temoins lumineux de la prise reseau du poste.
2. Verifier que le cable est correctement enfiche des deux cotes.
3. Tester le cable sur un autre poste ou tester un autre cable sur le meme poste.
4. Verifier l adresse obtenue : une adresse commencant par 169.254 indique une
   absence de serveur d adressage.
5. Verifier l etat du port sur le commutateur de l etage.

## Resolution
Si l adresse est en 169.254, relancer l obtention d adresse. Si le probleme
persiste sur plusieurs postes du meme etage, il s agit probablement d un incident
sur le commutateur : escalader vers l equipe infrastructure sans attendre.
