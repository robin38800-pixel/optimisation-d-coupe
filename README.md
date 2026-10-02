# Optimisation de découpe d'isolant

Place automatiquement toutes les découpes d'un fichier **DXF** dans des plaques
(1500 × 1000 mm par défaut) pour **minimiser le nombre de plaques et la chute**,
et réécrit le résultat en **DXF**.

## Installation

```bash
pip install -r requirements.txt        # ezdxf, shapely, numpy
```

## Utilisation

```bash
python -m decoupe pieces.dxf -o resultat.dxf --espacement 3 --temps 60
```

| Option | Rôle | Défaut |
|---|---|---|
| `--largeur`, `--hauteur` | taille de la plaque (mm) | 1500 × 1000 |
| `--espacement` | distance minimale entre deux pièces (mm) | 2 |
| `--marge` | distance minimale entre pièces et bord de plaque (mm) | 0 |
| `--rotations` | `libre` (tout angle utile), `90` (multiples de 90°), `aucune` | `libre` |
| `--pas-rotation N` | teste en plus un angle tous les N° (plus lent) | désactivé |
| `--temps` | durée de la recherche en secondes (plus long = souvent meilleur) | 30 |
| `--jobs` | nombre de processus (0 = tous les coeurs) | 0 |
| `--calque NOM` | ne lit que ce calque du DXF (répétable) | tous |
| `--echelle` | facteur vers les mm si le DXF est en cm (10) ou m (1000) | 1 |
| `--separe` | un DXF par plaque (`resultat_plaque1.dxf`, ...) | un seul fichier |
| `--apercu f.svg` | écrit aussi un aperçu visuel | non |
| `--sans-appariement` | ne regroupe pas les pièces complémentaires | actif |
| `--resolution` | finesse de la grille de recherche (mm) | 4 |

Exemple de démonstration : `python -m decoupe exemples/exemple.dxf -o sortie.dxf --apercu sortie.svg`
(`python exemples/generer_exemple.py` régénère ce fichier).

## Fichier d'entrée

Chaque **contour fermé** est une pièce : polylignes fermées (LWPOLYLINE/POLYLINE), cercles,
ellipses, splines fermées, et suites de LINE/ARC jointives. Les blocs (INSERT) sont dépliés.
Les contours ouverts sont signalés et ignorés. Si le DXF contient aussi le cadre de la plaque
ou des cotes, utilisez `--calque` pour ne lire que le calque des découpes.
Le programme travaille en **mm** (un avertissement s'affiche si le DXF déclare une autre unité).

## Fichier de sortie

DXF (R2010, mm) avec les calques `PLAQUE` (cadre 1500 × 1000), `DECOUPES` (contours
placés), `ETIQUETTES` (numéro de chaque pièce et taux de remplissage). Si plusieurs
plaques sont nécessaires, elles sont posées côte à côte (ou `--separe`).
Le programme affiche le nombre de plaques, le taux de remplissage, la chute et la zone
utilisée sur chaque plaque (la dernière est volontairement la moins remplie, pour
récupérer la chute en un seul morceau).

## Comment ça marche

1. **Appariement** : les pièces qui s'emboîtent le long d'une arête de même longueur
   (2 triangles issus d'un rectangle, un L et son complément...) sont rangées ensemble.
2. **Placement** : pour chaque pièce, rotations candidates (arêtes alignées sur les axes +
   multiples de 90°), recherche des positions libres par grille + FFT, choix selon le
   contact avec les pièces voisines / la compacité, puis tassement géométrique exact.
3. **Recherche multi-départs** : de nombreux ordres et stratégies sont essayés
   (en parallèle) pendant `--temps` secondes ; on garde le moins de plaques, puis la plus
   petite zone utilisée sur la dernière.
4. **Contrôle final** indépendant : espacement, marge et bords sont revérifiés sur les
   polygones écrits ; une erreur est signalée si une contrainte n'était pas respectée.

C'est une **heuristique** : le résultat est très bon en pratique mais pas garanti optimal.
Pour gagner quelques points, augmentez `--temps`, essayez `--pas-rotation 15`, ou plusieurs `--graine`.

## Tests

```bash
pip install -r requirements-dev.txt && python -m pytest
```
