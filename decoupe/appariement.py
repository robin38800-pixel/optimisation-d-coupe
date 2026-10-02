"""Appariement de pièces complémentaires avant le placement.

Deux pièces qui s'emboîtent le long d'une arête de même longueur (deux triangles
formant un rectangle ou un parallélogramme, un L et son complément...) sont
regroupées en une « unité » rigide, beaucoup plus facile à ranger qu'un triangle
isolé. L'espacement demandé est conservé entre les deux pièces d'une unité.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .modeles import Parametres, Piece

SEUIL_ARETE = 0.10        # arêtes utilisées : au moins 10 % de la plus grande dimension de la pièce
TOL_LONGUEUR_MM = 0.5     # écart toléré entre deux arêtes à assembler
HULL_MIN = 0.90           # l'unité doit rester presque convexe
GAIN_MIN = 0.5            # le vide dans le rectangle englobant doit être au moins divisé par 2


@dataclass
class Unite:
    """Un ou deux pièces rangées ensemble (coordonnées normalisées : coin bas-gauche en 0, 0)."""

    indices: list[int]
    membres: list[Polygon]
    poly: Polygon


def _normaliser(poly: Polygon) -> Polygon:
    minx, miny, _, _ = poly.bounds
    return affinity.translate(orient(poly, 1.0), -minx, -miny)


def _signature(poly: Polygon) -> tuple:
    coords = np.round(np.asarray(poly.exterior.coords)[:-1], 2)
    k = min(range(len(coords)), key=lambda i: tuple(coords[i]))
    return tuple(map(tuple, np.roll(coords, -k, axis=0).tolist()))


def _vide(p: Polygon) -> float:
    return p.minimum_rotated_rectangle.area - p.area


def _aretes(poly: Polygon) -> list[tuple[int, np.ndarray, np.ndarray, float]]:
    c = np.asarray(poly.exterior.coords)
    minx, miny, maxx, maxy = poly.bounds
    seuil = SEUIL_ARETE * max(maxx - minx, maxy - miny)
    res = []
    for k in range(len(c) - 1):
        lg = float(np.hypot(*(c[k + 1] - c[k])))
        if lg >= seuil:
            res.append((k, c[k], c[k + 1], lg))
    return res


def _assembler(a: Polygon, ea, b: Polygon, eb, espacement: float):
    """Pose b contre l'arête ea de a (arête eb de b). Renvoie (b posée, polygone fusionné) ou None."""
    _, a0, a1, la = ea
    _, b0, b1, _ = eb
    angle = math.atan2(a1[1] - a0[1], a1[0] - a0[0]) - math.atan2(b0[1] - b1[1], b0[0] - b1[0])
    bt = affinity.rotate(b, angle, origin=(float(b1[0]), float(b1[1])), use_radians=True)
    dx, dy = a0 - b1
    n = np.array([a1[1] - a0[1], -(a1[0] - a0[0])]) / la  # normale sortante de a (a est anti-horaire)
    dx += espacement * n[0]
    dy += espacement * n[1]
    bt = affinity.translate(bt, dx, dy)
    if a.intersection(bt).area > 1e-2:
        return None
    if espacement > 0 and a.distance(bt) < espacement - 1e-3:
        return None
    parties = [a, bt]
    if espacement > 0:
        # comble la fente d'espacement pour que l'unité reste un polygone plein
        p1 = a0 + espacement * n
        p2 = a1 + espacement * n
        parties.append(Polygon([a0, a1, p2, p1]))
    fusion = unary_union(parties)
    if fusion.geom_type != "Polygon":
        fusion = fusion.buffer(0.02, join_style=2).buffer(-0.02, join_style=2)
    if fusion.geom_type != "Polygon" or len(fusion.interiors) > 0:
        return None
    return bt, fusion


def apparier(pieces: list[Piece], params: Parametres) -> list[Unite]:
    """Regroupe les pièces complémentaires par deux. Les autres restent seules."""
    normes = [_normaliser(p.polygone) for p in pieces]
    seules = [Unite([i], [normes[i]], normes[i]) for i in range(len(pieces))]
    if not params.appariement or len(pieces) < 2:
        return seules

    # regroupement des pièces par forme identique
    formes: dict[tuple, list[int]] = {}
    for i, n in enumerate(normes):
        formes.setdefault(_signature(n), []).append(i)
    sigs = list(formes)
    reps = [normes[formes[s][0]] for s in sigs]
    vides = [_vide(r) for r in reps]
    aretes = [_aretes(r) for r in reps]

    candidats = []  # (gain, sa, sb, b posée, fusion)
    for x in range(len(sigs)):
        for y in range(x, len(sigs)):
            if x == y and len(formes[sigs[x]]) < 2:
                continue
            base = vides[x] + vides[y]
            if base < 1e-6 * (reps[x].area + reps[y].area):
                continue  # deux rectangles : rien à gagner
            meilleur = None
            for ea in aretes[x]:
                for eb in aretes[y]:
                    if abs(ea[3] - eb[3]) > max(TOL_LONGUEUR_MM, 0.003 * ea[3]):
                        continue
                    r = _assembler(reps[x], ea, reps[y], eb, params.espacement)
                    if r is None:
                        continue
                    bt, fusion = r
                    if fusion.area / fusion.convex_hull.area < HULL_MIN:
                        continue
                    reste = _vide(fusion)
                    if reste > GAIN_MIN * base:
                        continue
                    gain = base - reste
                    if meilleur is None or gain > meilleur[0]:
                        meilleur = (gain, x, y, bt, fusion)
            if meilleur:
                candidats.append(meilleur)

    candidats.sort(key=lambda c: -c[0])
    restants = {s: list(idx) for s, idx in formes.items()}
    unites: list[Unite] = []
    for gain, x, y, bt, fusion in candidats:
        lx, ly = restants[sigs[x]], restants[sigs[y]]
        k = len(lx) // 2 if x == y else min(len(lx), len(ly))
        for _ in range(k):
            ia = lx.pop()
            ib = ly.pop()
            minx, miny, _, _ = fusion.bounds
            membres = [affinity.translate(reps[x], -minx, -miny), affinity.translate(bt, -minx, -miny)]
            poly = Polygon(affinity.translate(fusion, -minx, -miny).exterior)
            unites.append(Unite([ia, ib], membres, poly))
    for idx in restants.values():
        for i in idx:
            unites.append(Unite([i], [normes[i]], normes[i]))
    return unites
