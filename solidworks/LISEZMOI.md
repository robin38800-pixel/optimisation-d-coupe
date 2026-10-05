# Macro SolidWorks - répartition des isolants dans les plaques

Depuis une **mise en plan avec nomenclature**, la macro :

1. lit la nomenclature (repère et **quantité** de chaque pièce). Si le tableau n'est pas relié à un assemblage, la pièce de
   chaque ligne est retrouvée **d'après sa désignation** (par exemple « N° PLAN : CALORIFUGE ECF A1-A » → fichier
   contenant ce nom), d'abord parmi les modèles des vues du plan, puis dans le dossier du plan ;
2. relève le contour de la **plus grande face plane** de chaque pièce 3D (vraie grandeur, pas de problème d'échelle de vue) ;
3. appelle `DecoupeIsolant.exe`, qui répartit toutes les pièces dans des plaques de 1500 x 1000 mm ;
4. crée une **nouvelle feuille « Plaques hhmmss »** (échelle 1:1) dans la mise en plan avec les plaques et, pour chaque
   pièce, une **vraie vue du modèle** (liée à la pièce, cotable), tournée et placée à l'endroit calculé, avec son repère
   (repère-1, repère-2... quand la quantité est supérieure à 1). Aucun DXF n'est créé à côté du plan.

La vue utilisée est la vue standard (*Face, *Dessus, *Droite, *Arrière, *Dessous ou *Gauche) qui regarde la grande face
de la pièce. Si la face n'est pas parallèle à un plan principal, ou si SolidWorks ne crée pas la vue attendue, la pièce
est **tracée en traits** à la place (le message final indique « x en vues, y en traits ») ; le journal explique pourquoi.
Pour n'avoir que des traits, mettez `MODE_VUES` à `False` en haut du fichier `.bas`.

> **Mettez à jour ensemble la macro et `DecoupeIsolant.exe`** : ils échangent un fichier dont le format a changé
> (la macro le signale si l'exe est trop ancien).

> **Version d'essai.** La macro a été écrite pour SolidWorks 2024 sans pouvoir être lancée sur SolidWorks lui-même.
> Si elle affiche une erreur, envoyez le **journal** (voir plus bas) : il indique l'étape exacte.

## Installation (une seule fois)

1. Copiez `DecoupeIsolant.exe` (archive Windows) où vous voulez, **idéalement dans le même dossier que le fichier `.swp`**
   de la macro (elle l'y retrouve toute seule). Sinon elle vous demandera son chemin au premier lancement.
2. Dans SolidWorks : **Outils > Macro > Nouvelle...**, enregistrez sous le nom `DecoupeIsolant.swp` (dans le même dossier que l'exe).
   L'éditeur VBA s'ouvre avec un module vide (`Module1`).
3. Dans l'éditeur, à gauche, déroulez **Modules** : il contient un module vide (`DecoupeIsolant1` ou `Module1`).
   Clic droit sur **ce module** (pas sur le dossier « Modules », qui est grisé) > **Supprimer ...** (répondre *Non*
   à la question sur l'export). Cette étape est facultative.
4. **Fichier > Importer un fichier...** et choisissez `DecoupeIsolant.bas` (dossier `solidworks` de l'archive). Un module nommé `ModDecoupe` apparaît.
5. Enregistrez (Ctrl+S) et fermez l'éditeur.
6. Facultatif : **Outils > Personnaliser > Macros** pour mettre un bouton dans la barre d'outils.

## Utilisation

1. Ouvrez la mise en plan qui contient la nomenclature des isolants.
2. **Outils > Macro > Exécuter...** > `DecoupeIsolant.swp` > module `ModDecoupe` > `main`.
3. Si l'exe n'est pas à côté du `.swp`, indiquez son chemin complet (il est mémorisé).
4. Répondez aux deux questions :
   * **Espacement** entre pièces (mm) ;
   * **Épaisseur des isolants** (mm) : permet d'ignorer les autres lignes de la nomenclature (visserie, cadres...).
     Laissez vide pour prendre toutes les pièces.
5. Confirmez le calcul (environ 30 secondes, SolidWorks reste figé pendant ce temps).
6. La feuille « Plaques ... » est créée et affichée.

Les réglages fixes (taille de plaque, marge au bord, durée du calcul, hauteur du texte) sont en haut du fichier
`DecoupeIsolant.bas`, section *Réglages modifiables*.

## En cas de problème

La macro écrit un journal détaillé : `%TEMP%\DecoupeIsolant\journal.txt` (tapez `%TEMP%\DecoupeIsolant` dans
l'explorateur Windows). Il contient les lignes de nomenclature lues, les pièces retrouvées, leur épaisseur estimée
et la moindre erreur. Joignez aussi `entree.txt` du même dossier : c'est ce que la macro a envoyé au programme.

Cas fréquents :

| Symptôme | Cause probable |
|---|---|
| « Aucune nomenclature trouvée » | La mise en plan n'a pas de tableau de nomenclature (BOM) SolidWorks. |
| « Aucune piece exploitable » | Épaisseur saisie trop différente, ou pièces pas des corps volumiques avec une grande face plane. |
| « Le programme de calcul n'a produit aucun resultat » | Mauvais chemin vers `DecoupeIsolant.exe` (supprimez-le en relançant et saisissez le bon). |
| Les pièces sont l'image « miroir » de la vue | Normal : seule la grande face est relevée ; une pièce peut être retournée sur la plaque. |
