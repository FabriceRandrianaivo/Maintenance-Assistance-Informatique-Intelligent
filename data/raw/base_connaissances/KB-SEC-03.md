# Verification d identite avant une operation sensible

Identifiant : KB-SEC-03
Categorie : cybersecurite
Type : regle_securite
Mots-cles : identite, verification, usurpation, ingenierie sociale

## Objet
Encadrer la verification d identite prealable aux operations sensibles.

## Operations concernees
Reinitialisation de mot de passe, revocation de second facteur, modification de
droits, deverrouillage de compte, acces a des donnees personnelles.

## Regle
L identite doit etre verifiee par un canal different de celui de la demande. Une
demande formulee par courriel se verifie par telephone sur le numero du
referentiel, jamais sur un numero fourni dans la demande.

## Signaux d ingenierie sociale
Urgence mise en avant, invocation d une autorite hierarchique, demande portant
sur le compte d un tiers, refus du rappel telephonique, insistance a contourner
la procedure, demande de transmission d un mot de passe.

## Regle absolue
Aucun mot de passe n est jamais communique a un tiers, quel que soit le motif
invoque et quelle que soit l autorite dont se reclame le demandeur.
