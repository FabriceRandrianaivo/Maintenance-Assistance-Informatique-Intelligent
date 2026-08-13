# Probleme d authentification a double facteur

Identifiant : KB-CPT-03
Categorie : comptes_authentification
Type : procedure
Mots-cles : double facteur, 2FA, code, authentificateur, telephone

## Objet
Retablir l acces lorsque le second facteur d authentification est indisponible.

## Cas traites
Telephone perdu, application d authentification desinstallee, changement d appareil,
decalage de l horloge du telephone.

## Procedure
1. Verifier l identite du demandeur de maniere renforcee : deux elements distincts
   du dossier administratif.
2. En cas de simple decalage de codes, faire synchroniser l heure du telephone.
3. Pour un changement d appareil, generer un code d enrolement temporaire valable
   quinze minutes.
4. Revoquer l ancien enrolement une fois le nouveau confirme.
5. Toute revocation de second facteur est une operation sensible : elle requiert
   la validation d un technicien du service securite.
