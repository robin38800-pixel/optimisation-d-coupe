"""Lecture des découpes depuis un DXF et écriture des plaques placées."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

import ezdxf
from ezdxf import path as ezpath
from ezdxf import recover, units
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree

from .modeles import Piece, Resultat

TYPES_GEOMETRIQUES = {"LINE", "ARC", "CIRCLE", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE"}
UNITES = {0: None, 1: "pouces", 2: "pieds", 4: "mm", 5: "cm", 6: "m"}


@dataclass
class LectureDxf:
    pieces: list[Piece]
    avertissements: list[str] = field(default_factory=list)


def _entites_a_plat(entites: Iterable, profondeur: int = 0) -> Iterator:
    """Parcourt les entités en dépliant les blocs (INSERT)."""
    for e in entites:
        if e.dxftype() == "INSERT":
            if profondeur >= 8:
                continue
            try:
                sous = list(e.virtual_entities())
            except Exception:
                continue
            yield from _entites_a_plat(sous, profondeur + 1)
        else:
            yield e


def _proche(a, b, eps: float) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= eps


def _assembler(ouverts: list[list[tuple]], eps: float) -> tuple[list[list[tuple]], int]:
    """Chaîne des segments/arcs ouverts pour former des contours fermés."""
    restants = [list(p) for p in ouverts]
    fermes: list[list[tuple]] = []
    abandonnes = 0
    while restants:
        chaine = restants.pop()
        progres = True
        while progres and not (len(chaine) >= 4 and _proche(chaine[0], chaine[-1], eps)):
            progres = False
            for k, autre in enumerate(restants):
                if _proche(chaine[-1], autre[0], eps):
                    chaine = chaine + autre[1:]
                elif _proche(chaine[-1], autre[-1], eps):
                    chaine = chaine + autre[::-1][1:]
                elif _proche(chaine[0], autre[-1], eps):
                    chaine = autre[:-1] + chaine
                elif _proche(chaine[0], autre[0], eps):
                    chaine = autre[::-1][:-1] + chaine
                else:
                    continue
                restants.pop(k)
                progres = True
                break
        if len(chaine) >= 4 and _proche(chaine[0], chaine[-1], eps):
            fermes.append(chaine[:-1])
        else:
            abandonnes += 1
    return fermes, abandonnes


def _vers_polygone(points: list[tuple], echelle: float, avertissements: list[str], nom: str) -> Optional[Polygon]:
    pts = [(x * echelle, y * echelle) for x, y in points]
    if len(pts) < 3:
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        corrige = poly.buffer(0)
        if isinstance(corrige, MultiPolygon):
            corrige = max(corrige.geoms, key=lambda g: g.area)
        avertissements.append(f"{nom} : contour auto-sécant, corrigé automatiquement")
        poly = corrige
    if not isinstance(poly, Polygon) or poly.is_empty or poly.area < 1e-6:
        return None
    return orient(Polygon(poly.exterior), 1.0)


def lire_dxf(
    chemin: str | Path,
    calques: Optional[list[str]] = None,
    tolerance_arc: float = 0.1,
    echelle: float = 1.0,
    tolerance_jonction: float = 0.05,
) -> LectureDxf:
    """Lit tous les contours fermés d'un DXF et les renvoie comme pièces.

    Les polylignes fermées, cercles, ellipses, splines fermées ainsi que les
    suites de LINE/ARC jointives sont reconnus. Les arcs sont discrétisés avec
    une flèche maximale de `tolerance_arc` mm.
    """
    avertissements: list[str] = []
    try:
        doc = ezdxf.readfile(str(chemin))
    except ezdxf.DXFStructureError:
        doc, _ = recover.readfile(str(chemin))
        avertissements.append("Fichier DXF endommagé : lecture en mode récupération")

    code_unite = doc.header.get("$INSUNITS", 0)
    unite = UNITES.get(code_unite, f"code {code_unite}")
    if unite not in (None, "mm") and echelle == 1.0:
        avertissements.append(
            f"Unité du DXF : {unite}. Le programme travaille en mm ; utilisez --echelle si nécessaire."
        )

    filtre = {c.lower() for c in calques} if calques else None
    fermes: list[tuple[list[tuple], str]] = []
    ouverts: list[list[tuple]] = []

    for e in _entites_a_plat(doc.modelspace()):
        t = e.dxftype()
        if t not in TYPES_GEOMETRIQUES:
            continue
        calque = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        if filtre is not None and calque.lower() not in filtre:
            continue
        try:
            chemin_e = ezpath.make_path(e)
            pts = [(v.x, v.y) for v in chemin_e.flattening(tolerance_arc, segments=8)]
        except Exception as exc:  # entité dégénérée
            avertissements.append(f"Entité {t} ignorée ({exc})")
            continue
        if len(pts) < 2:
            continue
        if chemin_e.is_closed or (len(pts) > 3 and _proche(pts[0], pts[-1], tolerance_jonction)):
            fermes.append((pts[:-1], calque))
        else:
            ouverts.append(pts)

    if ouverts:
        assembles, abandonnes = _assembler(ouverts, tolerance_jonction)
        for pts in assembles:
            fermes.append((pts, "0"))
        if abandonnes:
            avertissements.append(f"{abandonnes} contour(s) ouvert(s) non refermable(s) ignoré(s)")

    pieces: list[Piece] = []
    for pts, calque in fermes:
        nom = f"P{len(pieces) + 1:03d}"
        poly = _vers_polygone(pts, echelle, avertissements, nom)
        if poly is not None:
            pieces.append(Piece(id=len(pieces), nom=nom, polygone=poly, calque=calque))

    if len(pieces) > 1:
        arbre = STRtree([p.polygone for p in pieces])
        contenues = set()
        for p in pieces:
            for k in arbre.query(p.polygone, predicate="contains"):
                autre = pieces[int(k)]
                if autre.id != p.id and autre.polygone.area < p.polygone.area:
                    contenues.add(autre.nom)
        if contenues:
            avertissements.append(
                f"{len(contenues)} contour(s) sont situés à l'intérieur d'un autre (cadre de dessin, trous, vues "
                "imbriquées ?) et sont traités comme des pièces distinctes. Utilisez --calque / --ignorer si besoin."
            )
    return LectureDxf(pieces=pieces, avertissements=avertissements)


def petit_cote(poly: Polygon) -> float:
    """Plus petite dimension du rectangle englobant (quelle que soit l'orientation)."""
    xs, ys = poly.minimum_rotated_rectangle.exterior.coords.xy
    return min(math.hypot(xs[1] - xs[0], ys[1] - ys[0]), math.hypot(xs[2] - xs[1], ys[2] - ys[1]))


def filtrer_pieces(
    pieces: list[Piece], ignorer_profils: float = 0.0, ignorer: Optional[list[str]] = None
) -> tuple[list[Piece], list[str]]:
    """Retire les vues de profil (plus petit côté <= ignorer_profils mm) et les pièces nommées."""
    noms = {n.upper() for n in (ignorer or [])}
    gardees: list[Piece] = []
    retirees: list[str] = []
    for p in pieces:
        if p.nom.upper() in noms or (ignorer_profils > 0 and petit_cote(p.polygone) <= ignorer_profils + 0.5):
            retirees.append(p.nom)
        else:
            gardees.append(p)
    return gardees, retirees


def decrire_pieces(pieces: list[Piece]) -> str:
    """Tableau lisible des contours détectés."""
    lignes = ["  nom    largeur x hauteur (mm)   plus petit côté   aire (cm²)  sommets  calque"]
    for p in pieces:
        x0, y0, x1, y1 = p.polygone.bounds
        lignes.append(
            f"  {p.nom}  {x1 - x0:9.1f} x {y1 - y0:<9.1f}  {petit_cote(p.polygone):14.1f}  "
            f"{p.polygone.area / 100:11.1f}  {len(p.polygone.exterior.coords) - 1:7d}  {p.calque}"
        )
    return "\n".join(lignes)


def _coins(poly: Polygon) -> list[tuple[float, float]]:
    return [(x, y) for x, y in poly.exterior.coords][:-1]


def _hauteur_texte(poly: Polygon) -> float:
    rect = poly.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    cotes = sorted(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2))
    return max(3.0, min(30.0, cotes[0] / 6.0))


def _dessiner_plaque(msp, resultat: Resultat, plaque, ox: float, etiquettes: bool) -> None:
    p = resultat.parametres
    L, H = p.largeur, p.hauteur
    msp.add_lwpolyline([(ox, 0), (ox + L, 0), (ox + L, H), (ox, H)], close=True, dxfattribs={"layer": "PLAQUE"})
    titre = f"Plaque {plaque.index + 1} - remplissage {100 * resultat.taux_plaque(plaque):.1f} %"
    msp.add_text(titre, height=25, dxfattribs={"layer": "ETIQUETTES"}).set_placement(
        (ox, H + 20), align=TextEntityAlignment.LEFT
    )
    for pp in plaque.pieces:
        pts = [(x + ox, y) for x, y in _coins(pp.polygone)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "DECOUPES"})
        if etiquettes:
            c = pp.polygone.representative_point()
            msp.add_text(pp.piece.nom, height=_hauteur_texte(pp.polygone), dxfattribs={"layer": "ETIQUETTES"}).set_placement(
                (c.x + ox, c.y), align=TextEntityAlignment.MIDDLE_CENTER
            )


def _nouveau_document():
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    doc.layers.add("PLAQUE", color=8)
    doc.layers.add("DECOUPES", color=3)
    doc.layers.add("ETIQUETTES", color=2)
    return doc


def ecrire_dxf(
    chemin: str | Path,
    resultat: Resultat,
    etiquettes: bool = True,
    separe: bool = False,
    ecart: float = 100.0,
) -> list[Path]:
    """Écrit le résultat. Un seul DXF (plaques côte à côte) ou un DXF par plaque."""
    chemin = Path(chemin)
    ecrits: list[Path] = []
    if separe:
        for plaque in resultat.plaques:
            doc = _nouveau_document()
            _dessiner_plaque(doc.modelspace(), resultat, plaque, 0.0, etiquettes)
            sortie = chemin.with_name(f"{chemin.stem}_plaque{plaque.index + 1}{chemin.suffix or '.dxf'}")
            doc.saveas(sortie)
            ecrits.append(sortie)
    else:
        doc = _nouveau_document()
        msp = doc.modelspace()
        pas = resultat.parametres.largeur + ecart
        for plaque in resultat.plaques:
            _dessiner_plaque(msp, resultat, plaque, plaque.index * pas, etiquettes)
        doc.saveas(chemin)
        ecrits.append(chemin)
    return ecrits
