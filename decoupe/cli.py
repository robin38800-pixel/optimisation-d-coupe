"""Interface en ligne de commande : python -m decoupe pieces.dxf -o resultat.dxf"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .apercu import ecrire_svg
from .dxf_io import decrire_pieces, ecrire_dxf, filtrer_pieces, lire_dxf
from .modeles import Parametres
from .nesting import ErreurPlacement, optimiser, verifier


def _arguments(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="decoupe",
        description="Place les découpes d'un DXF dans des plaques (1500 x 1000 mm par défaut) "
        "en minimisant le nombre de plaques et la chute.",
    )
    p.add_argument("entree", help="DXF contenant toutes les découpes (contours fermés)")
    p.add_argument("-o", "--sortie", default="sortie.dxf", help="DXF de résultat (défaut : sortie.dxf)")
    p.add_argument("--largeur", type=float, default=1500.0, help="largeur de la plaque en mm (défaut 1500)")
    p.add_argument("--hauteur", type=float, default=1000.0, help="hauteur de la plaque en mm (défaut 1000)")
    p.add_argument("--espacement", type=float, default=2.0, help="distance minimale entre deux pièces en mm (défaut 2)")
    p.add_argument("--marge", type=float, default=0.0, help="distance minimale pièces / bord de plaque en mm (défaut 0)")
    p.add_argument("--rotations", choices=["libre", "90", "aucune"], default="libre",
                   help="libre : tout angle utile ; 90 : multiples de 90° ; aucune (défaut : libre)")
    p.add_argument("--pas-rotation", type=float, default=0.0,
                   help="teste en plus un angle tous les N degrés (ex. 15) ; plus lent")
    p.add_argument("--temps", type=float, default=30.0, help="durée de la recherche en secondes (défaut 30)")
    p.add_argument("--jobs", type=int, default=0, help="nombre de processus (0 = tous les coeurs, défaut)")
    p.add_argument("--graine", type=int, default=0, help="graine aléatoire (résultats reproductibles à temps égal)")
    p.add_argument("--resolution", type=float, default=4.0,
                   help="finesse de la grille de recherche en mm (défaut 4 ; plus petit = plus fin mais plus lent)")
    p.add_argument("--sans-appariement", action="store_true",
                   help="ne regroupe pas les pièces complémentaires (ex. 2 triangles formant un rectangle)")
    p.add_argument("--calque", action="append", metavar="NOM",
                   help="ne lire que ce calque du DXF d'entrée (option répétable)")
    p.add_argument("--ignorer-profils", type=float, default=0.0, metavar="EPAISSEUR",
                   help="ignore les contours dont le plus petit côté est <= EPAISSEUR mm "
                   "(vues de profil d'un plan : ex. 30 pour un isolant de 30 mm)")
    p.add_argument("--ignorer", action="append", metavar="NOM",
                   help="ignore la pièce de ce nom (voir --lister), option répétable")
    p.add_argument("--lister", action="store_true",
                   help="affiche seulement les contours détectés (nom, taille, aire) puis s'arrête")
    p.add_argument("--tolerance-arc", type=float, default=0.1,
                   help="écart max en mm entre un arc et sa discrétisation (défaut 0.1)")
    p.add_argument("--echelle", type=float, default=1.0, help="facteur d'échelle du DXF d'entrée vers des mm (ex. 10 si cm)")
    p.add_argument("--separe", action="store_true", help="un fichier DXF par plaque (sortie_plaque1.dxf, ...)")
    p.add_argument("--sans-etiquettes", action="store_true", help="n'écrit pas les numéros de pièces dans le DXF")
    p.add_argument("--apercu", metavar="FICHIER.svg", help="écrit aussi un aperçu SVG du résultat")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = _arguments(argv)
    try:
        lecture = lire_dxf(a.entree, calques=a.calque, tolerance_arc=a.tolerance_arc, echelle=a.echelle)
    except (OSError, ValueError) as exc:
        print(f"Erreur de lecture : {exc}", file=sys.stderr)
        return 2
    for av in lecture.avertissements:
        print(f"Attention : {av}", file=sys.stderr)
    pieces, retirees = filtrer_pieces(lecture.pieces, a.ignorer_profils, a.ignorer)
    if retirees:
        print(f"{len(retirees)} contour(s) ignoré(s) : {', '.join(retirees)}")
    if a.lister:
        print(f"{len(pieces)} contour(s) fermé(s) retenu(s) :")
        print(decrire_pieces(pieces))
        return 0
    if not pieces:
        print("Aucun contour fermé trouvé dans le DXF.", file=sys.stderr)
        return 2

    params = Parametres(
        largeur=a.largeur, hauteur=a.hauteur, espacement=a.espacement, marge=a.marge,
        rotations=a.rotations, pas_rotation=a.pas_rotation, resolution=a.resolution,
        temps=a.temps, graine=a.graine, jobs=a.jobs, appariement=not a.sans_appariement,
    )
    aire = sum(p.polygone.area for p in pieces)
    borne = -(-aire // (params.largeur * params.hauteur))
    print(f"{len(pieces)} pièces lues, surface totale {aire / 1e6:.3f} m²")
    print(f"Plaque {params.largeur:g} x {params.hauteur:g} mm, espacement {params.espacement:g} mm, "
          f"marge {params.marge:g} mm, rotations : {params.rotations}")
    print(f"Minimum théorique : {int(borne)} plaque(s). Optimisation en cours ({params.temps:g} s)...")

    try:
        resultat = optimiser(pieces, params, rappel=print)
    except ErreurPlacement as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        print("Astuce : `--lister` montre les contours lus ; `--calque`, `--ignorer` et `--ignorer-profils` "
              "permettent d'écarter cadres, cotations et vues de profil.", file=sys.stderr)
        return 1

    problemes = verifier(resultat)
    for pb in problemes:
        print(f"ERREUR de contrôle : {pb}", file=sys.stderr)

    print(f"\nRésultat : {len(resultat.plaques)} plaque(s), remplissage global {100 * resultat.taux_remplissage:.1f} % "
          f"(chute {100 * (1 - resultat.taux_remplissage):.1f} %)")
    for pl in resultat.plaques:
        l, h = pl.zone_utilisee()
        print(f"  Plaque {pl.index + 1} : {len(pl.pieces)} pièces, remplissage {100 * resultat.taux_plaque(pl):.1f} %, "
              f"zone utilisée {l:.0f} x {h:.0f} mm")

    for f in ecrire_dxf(a.sortie, resultat, etiquettes=not a.sans_etiquettes, separe=a.separe):
        print(f"DXF écrit : {f}")
    if a.apercu:
        print(f"Aperçu écrit : {ecrire_svg(Path(a.apercu), resultat)}")
    return 1 if problemes else 0
