"""Placement (nesting) de polygones quelconques dans des plaques rectangulaires.

Principe
--------
* Chaque pièce est « gonflée » de espacement/2 : deux pièces gonflées qui ne se
  chevauchent pas sont au moins à `espacement` l'une de l'autre, et la plaque
  est agrandie de espacement/2 pour que la marge au bord reste exacte.
* Pour chaque pièce et chaque rotation candidate, une grille d'occupation
  rasterisée (de façon conservative) donne par corrélation FFT toutes les
  positions sans chevauchement ; on garde la meilleure selon une stratégie.
* La pièce est ensuite « tassée » (glissée vers le bas et la gauche) avec des
  calculs géométriques exacts, ce qui récupère la finesse perdue par la grille.
* Une recherche multi-départs (ordres de placement et stratégies variés,
  éventuellement sur plusieurs processus) conserve la meilleure solution :
  d'abord le moins de plaques, puis la plus petite zone utilisée sur la dernière.
"""
from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from itertools import count
from typing import Callable, Optional

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree

from .appariement import Unite, apparier
from .modeles import Parametres, Piece, PiecePlacee, PlaqueResultat, Resultat

TOL_AIRE = 1e-4          # mm² : chevauchement ignoré (bruit numérique)
QUAD_SEGS = 4            # finesse des arrondis du gonflement
MAX_CLASSES_ANGLE = 8    # nombre max de directions d'arêtes testées par forme
STRATEGIES = ("env", "env", "ct", "bl", "lb")


class ErreurPlacement(Exception):
    """Une pièce ne rentre dans aucune plaque."""


# --------------------------------------------------------------------------
# Géométrie de base
# --------------------------------------------------------------------------
def gonfler(poly: Polygon, espacement: float) -> Polygon:
    """Polygone élargi de espacement/2 (sans trou), jamais plus petit que demandé."""
    r = espacement / 2.0
    if r <= 0:
        return Polygon(poly.exterior)
    # Compense la discrétisation des arcs (cos) et la simplification interne de GEOS (≤ 1 % de r)
    r_corrige = 1.03 * r / math.cos(math.pi / (4 * QUAD_SEGS))
    g = poly.buffer(r_corrige, quad_segs=QUAD_SEGS, join_style="round")
    return Polygon(g.exterior)


def _signature(poly: Polygon, decimales: int = 2) -> tuple:
    coords = np.round(np.asarray(orient(poly, 1.0).exterior.coords)[:-1], decimales)
    k = min(range(len(coords)), key=lambda i: tuple(coords[i]))
    return tuple(map(tuple, np.roll(coords, -k, axis=0).tolist()))


_BOITES: dict[float, np.ndarray] = {}


def _boites(res: float, nr: int, nc: int) -> np.ndarray:
    """Cellules res x res (légèrement rétrécies) en cache, origine (0, 0)."""
    b = _BOITES.get(res)
    if b is None or b.shape[0] < nr or b.shape[1] < nc:
        if b is not None:
            nr, nc = max(nr, b.shape[0]), max(nc, b.shape[1])
        e = 1e-4
        X, Y = np.meshgrid(np.arange(nc) * res + e, np.arange(nr) * res + e)
        b = shapely.box(X, Y, X + res - 2 * e, Y + res - 2 * e)
        _BOITES[res] = b
    return b


def cellules(poly: Polygon, ox: float, oy: float, res: float, nr: int, nc: int) -> tuple[int, int, np.ndarray]:
    """Cellules (res x res, origine ox/oy) touchées par l'intérieur de `poly`.

    Renvoie (r0, c0, tableau booléen) pour la sous-grille concernée.
    """
    if ox or oy:
        poly = affinity.translate(poly, -ox, -oy)
    minx, miny, maxx, maxy = poly.bounds
    c0 = max(0, int(math.floor(minx / res)))
    c1 = min(nc, int(math.ceil(maxx / res)))
    r0 = max(0, int(math.floor(miny / res)))
    r1 = min(nr, int(math.ceil(maxy / res)))
    if c1 <= c0 or r1 <= r0:
        return r0, c0, np.zeros((0, 0), bool)
    boites = _boites(res, nr, nc)[r0:r1, c0:c1]
    shapely.prepare(poly)
    return r0, c0, shapely.intersects(poly, boites)


# --------------------------------------------------------------------------
# Orientations candidates d'une forme
# --------------------------------------------------------------------------
_COMPTEUR = count()
_CACHE_FFT: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_CACHE_FFT_OCTETS = 96 * 1024 * 1024   # mémoire max du cache de FFT par processus
_octets_cache = 0


class Orientation:
    """Une forme tournée d'un angle donné, ramenée à l'origine."""

    def __init__(self, angle: float, infl_tournee: Polygon):
        minx, miny, maxx, maxy = infl_tournee.bounds
        self.id = next(_COMPTEUR)
        self.angle = angle
        self.decal = (-minx, -miny)
        self.infl0 = affinity.translate(infl_tournee, -minx, -miny)
        self.w = maxx - minx
        self.h = maxy - miny
        self._masques: dict[float, np.ndarray] = {}

    def masque(self, res: float) -> np.ndarray:
        m = self._masques.get(res)
        if m is None:
            nr = max(1, math.ceil(self.h / res - 1e-9))
            nc = max(1, math.ceil(self.w / res - 1e-9))
            _, _, hit = cellules(self.infl0, 0.0, 0.0, res, nr, nc)
            m = np.zeros((nr, nc), bool)
            m[: hit.shape[0], : hit.shape[1]] = hit
            self._masques[res] = m
        return m

    def anneau(self, res: float) -> np.ndarray:
        """Masque (mr+2, mc+2) des cellules voisines (4-connexité) de la pièce, posée en (1, 1)."""
        m = self.masque(res)
        d = np.zeros((m.shape[0] + 2, m.shape[1] + 2), bool)
        d[1:-1, 1:-1] = m
        dil = d.copy()
        dil[1:, :] |= d[:-1, :]
        dil[:-1, :] |= d[1:, :]
        dil[:, 1:] |= d[:, :-1]
        dil[:, :-1] |= d[:, 1:]
        return dil & ~d

    def fft_conj(self, genre: str, res: float, nr: int, nc: int) -> np.ndarray:
        """FFT conjuguée du masque ('m') ou de son anneau de contact ('a') sur la grille (nr, nc) bordée."""
        global _octets_cache
        cle = (self.id, genre, res, nr, nc)
        f = _CACHE_FFT.get(cle)
        if f is None:
            if genre == "m":
                m = self.masque(res)
                a = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.float32)
                a[1:-1, 1:-1] = m
            else:
                a = self.anneau(res).astype(np.float32)
            f = np.conj(np.fft.rfft2(a, s=(nr, nc)))
            _CACHE_FFT[cle] = f
            _octets_cache += f.nbytes
            while _octets_cache > _CACHE_FFT_OCTETS and len(_CACHE_FFT) > 1:
                _, vieux = _CACHE_FFT.popitem(last=False)
                _octets_cache -= vieux.nbytes
        else:
            _CACHE_FFT.move_to_end(cle)
        return f


def _classes_angles(poly: Polygon) -> list[float]:
    """Angles (mod 90°) qui alignent une arête importante de la pièce sur un axe."""
    minx, miny, maxx, maxy = poly.bounds
    grand = max(maxx - minx, maxy - miny)
    arêtes: list[tuple[float, float]] = []
    for contour, seuil in ((poly.exterior, 0.08), (poly.convex_hull.exterior, 0.05)):
        c = np.asarray(contour.coords)
        d = np.diff(c, axis=0)
        longueurs = np.hypot(d[:, 0], d[:, 1])
        for (dx, dy), lg in zip(d, longueurs):
            if lg >= seuil * grand:
                arêtes.append(((-math.degrees(math.atan2(dy, dx))) % 90.0, float(lg)))
    arêtes.sort()
    classes: list[list[float]] = []  # [angle, longueur cumulée]
    for a, lg in arêtes:
        if classes and abs(a - classes[-1][0]) <= 0.05:
            classes[-1][1] += lg
        else:
            classes.append([a, lg])
    if len(classes) > 1 and (classes[0][0] + 90.0 - classes[-1][0]) <= 0.05:  # raccord circulaire
        classes[0][1] += classes[-1][1]
        classes.pop()
    classes.sort(key=lambda c: -c[1])
    return [c[0] for c in classes[:MAX_CLASSES_ANGLE]]


def angles_candidats(poly: Polygon, params: Parametres) -> list[float]:
    if params.rotations == "aucune":
        angles = {0.0}
    else:
        angles = {0.0, 90.0, 180.0, 270.0}
        if params.rotations == "libre":
            for a in _classes_angles(poly):
                for k in range(4):
                    angles.add(round((a + 90.0 * k) % 360.0, 4))
            if params.pas_rotation > 0:
                n = int(360.0 / params.pas_rotation)
                angles.update(round(i * params.pas_rotation, 4) for i in range(n))
    return sorted(angles)


class Forme:
    """Géométrie d'une pièce (partagée par les pièces identiques)."""

    def __init__(self, poly_norm: Polygon, params: Parametres):
        self.poly = poly_norm
        self.aire = poly_norm.area
        self.infl = gonfler(poly_norm, params.espacement)
        self.aire_gonflee = self.infl.area
        largeur_utile = params.largeur - 2 * params.marge + params.espacement
        hauteur_utile = params.hauteur - 2 * params.marge + params.espacement
        vues: set[tuple] = set()
        self.orients: list[Orientation] = []
        for angle in angles_candidats(poly_norm, params):
            o = Orientation(angle, affinity.rotate(self.infl, angle, origin=(0, 0)))
            if o.w > largeur_utile + 1e-9 or o.h > hauteur_utile + 1e-9:
                continue
            sig = _signature(o.infl0, 1)
            if sig in vues:  # forme symétrique : orientation identique à une autre
                continue
            vues.add(sig)
            self.orients.append(o)


def construire_formes(polygones: list[Polygon], params: Parametres) -> tuple[list[Forme], list[int]]:
    """Dédoublonne les polygones identiques. Renvoie (formes, indice de forme par pièce)."""
    formes: list[Forme] = []
    index: dict[tuple, int] = {}
    forme_de_piece: list[int] = []
    for poly in polygones:
        minx, miny, _, _ = poly.bounds
        norm = affinity.translate(orient(poly, 1.0), -minx, -miny)
        sig = _signature(norm)
        if sig not in index:
            index[sig] = len(formes)
            formes.append(Forme(norm, params))
        forme_de_piece.append(index[sig])
    return formes, forme_de_piece


# --------------------------------------------------------------------------
# Plaque en cours de remplissage
# --------------------------------------------------------------------------
class Grille:
    """Occupation de la plaque, avec un cadre d'une cellule (occupé) pour mesurer le contact avec les bords."""

    def __init__(self, plaque: "Plaque", res: float):
        self.res = res
        self.nr = int((plaque.y1 - plaque.y0) / res + 1e-9)
        self.nc = int((plaque.x1 - plaque.x0) / res + 1e-9)
        self.occ = np.ones((self.nr + 2, self.nc + 2), np.float32)
        self.occ[1:-1, 1:-1] = 0.0
        self._fft: Optional[np.ndarray] = None

    def fft(self) -> np.ndarray:
        if self._fft is None:
            self._fft = np.fft.rfft2(self.occ)
        return self._fft

    def marquer(self, poly: Polygon, plaque: "Plaque") -> None:
        r0, c0, hit = cellules(poly, plaque.x0, plaque.y0, self.res, self.nr, self.nc)
        if hit.size:
            self.occ[1 + r0 : 1 + r0 + hit.shape[0], 1 + c0 : 1 + c0 + hit.shape[1]][hit] = 1.0
            self._fft = None


class Plaque:
    """Une plaque et les pièces (gonflées) déjà posées dessus."""

    def __init__(self, params: Parametres):
        s = params.espacement / 2.0
        self.x0 = params.marge - s
        self.y0 = params.marge - s
        self.x1 = params.largeur - params.marge + s
        self.y1 = params.hauteur - params.marge + s
        self.geoms: list[Polygon] = []
        self.arr = np.empty(0, dtype=object)
        self.arbre: Optional[STRtree] = None
        self.env: Optional[tuple[float, float, float, float]] = None
        self.libre = (self.x1 - self.x0) * (self.y1 - self.y0)
        self.grille = Grille(self, params.resolution)
        self.placements: list[tuple[int, float, float, float]] = []  # (pièce, angle, dx, dy)
        self.res = params.resolution

    # -- collisions exactes -------------------------------------------------
    def hors_plaque(self, poly: Polygon) -> bool:
        minx, miny, maxx, maxy = poly.bounds
        e = 1e-6
        return minx < self.x0 - e or miny < self.y0 - e or maxx > self.x1 + e or maxy > self.y1 + e

    def en_collision(self, poly: Polygon) -> bool:
        if self.hors_plaque(poly):
            return True
        if not self.geoms:
            return False
        idx = self.arbre.query(poly, predicate="intersects")
        if len(idx) == 0:
            return False
        inter = shapely.intersection(poly, self.arr[idx])
        return bool((shapely.area(inter) > TOL_AIRE).any())

    # -- recherche de position sur la grille --------------------------------
    def meilleur(self, o: Orientation, strat: str, poids: float, bruit: float, rng: np.random.Generator):
        g = self.grille
        mr, mc = o.masque(g.res).shape
        if mr > g.nr or mc > g.nc:
            return None
        taille = (g.nr + 2, g.nc + 2)
        gf = g.fft()
        corr = np.fft.irfft2(gf * o.fft_conj("m", g.res, *taille), s=taille)
        libre = corr[: g.nr - mr + 1, : g.nc - mc + 1] < 0.5
        ii, jj = np.nonzero(libre)
        if ii.size == 0:
            return None
        x0 = self.x0 + jj * g.res
        y0 = self.y0 + ii * g.res
        x1 = x0 + o.w
        y1 = y0 + o.h
        if strat == "bl":
            cle = y1 + 1e-3 * x1
        elif strat == "lb":
            cle = x1 + 1e-3 * y1
        else:
            contact = np.fft.irfft2(gf * o.fft_conj("a", g.res, *taille), s=taille)
            contact = contact[: g.nr - mr + 1, : g.nc - mc + 1][ii, jj]
            if strat == "ct":
                cle = -contact + 1e-3 * (x0 + y0)
            elif self.env is None:
                cle = o.w * o.h + 1e-3 * (x0 + y0) - poids * contact * g.res * 100.0
            else:
                ex0, ey0, ex1, ey1 = self.env
                aire = (np.maximum(x1, ex1) - np.minimum(x0, ex0)) * (np.maximum(y1, ey1) - np.minimum(y0, ey0))
                cle = aire + 1e-3 * (x0 + y0) - poids * contact * g.res * 100.0
        if bruit:
            cle = cle * (1.0 + bruit * rng.random(cle.size))
        k = int(np.argmin(cle))
        return float(cle[k]), int(ii[k]), int(jj[k])

    # -- tassement exact -----------------------------------------------------
    def glisser(self, poly: Polygon, ux: float, uy: float) -> float:
        """Distance dont `poly` peut glisser dans la direction axiale (ux, uy) sans chevaucher."""
        minx, miny, maxx, maxy = poly.bounds
        if ux < 0:
            dmax = minx - self.x0
        elif ux > 0:
            dmax = self.x1 - maxx
        elif uy < 0:
            dmax = miny - self.y0
        else:
            dmax = self.y1 - maxy
        if dmax <= 1e-6:
            return 0.0
        zone = shapely.box(
            minx + min(0.0, ux * dmax), miny + min(0.0, uy * dmax),
            maxx + max(0.0, ux * dmax), maxy + max(0.0, uy * dmax),
        )
        obstacles = self.arr[self.arbre.query(zone)] if self.geoms else []
        if len(obstacles) == 0:
            return dmax

        c = np.asarray(poly.exterior.coords)[:-1]
        a = c
        b = np.roll(c, -1, axis=0)
        e = b - a
        non_parallele = np.abs(e[:, 0] * uy - e[:, 1] * ux) > 1e-9
        a, b = a[non_parallele], b[non_parallele]

        def libre(t: float) -> bool:
            if t <= 0:
                return True
            d = np.array([ux * t, uy * t])
            anneaux = np.stack([a, b, b + d, a + d, a], axis=1)
            composants = np.concatenate([[affinity.translate(poly, d[0], d[1])], shapely.polygons(anneaux)])
            touche = shapely.intersects(composants[:, None], obstacles[None, :])
            if not touche.any():
                return True
            ci, oi = np.nonzero(touche)
            return not (shapely.area(shapely.intersection(composants[ci], obstacles[oi])) > TOL_AIRE).any()

        lo, hi = 0.0, min(max(self.res, 1.0), dmax)
        while libre(hi):
            lo = hi
            if hi >= dmax:
                return dmax
            hi = min(2.0 * hi, dmax)
        for _ in range(16):
            mid = 0.5 * (lo + hi)
            if libre(mid):
                lo = mid
            else:
                hi = mid
            if hi - lo < 0.01:
                break
        return lo

    def tasser(self, poly: Polygon, tx: float, ty: float, strat: str):
        directions = ((-1.0, 0.0), (0.0, -1.0)) if strat == "lb" else ((0.0, -1.0), (-1.0, 0.0))
        for _ in range(6):
            bouge = 0.0
            for ux, uy in directions:
                t = self.glisser(poly, ux, uy)
                if t > 1e-3:
                    poly = affinity.translate(poly, ux * t, uy * t)
                    tx += ux * t
                    ty += uy * t
                    bouge += t
            if bouge < 0.05:
                break
        return poly, tx, ty

    # -- pose ----------------------------------------------------------------
    def poser(self, o: Orientation, i: int, j: int, strat: str, piece: int):
        g = self.grille
        tx = self.x0 + j * g.res
        ty = self.y0 + i * g.res
        poly = affinity.translate(o.infl0, tx, ty)
        if self.en_collision(poly):
            return False
        poly, tx, ty = self.tasser(poly, tx, ty, strat)
        if self.en_collision(poly):  # sécurité : ne devrait jamais arriver
            return False
        self.ajouter(poly)
        self.placements.append((piece, o.angle, o.decal[0] + tx, o.decal[1] + ty))
        return True

    def ajouter(self, poly: Polygon) -> None:
        self.geoms.append(poly)
        self.arbre = STRtree(self.geoms)
        self.arr = np.array(self.geoms, dtype=object)
        bx0, by0, bx1, by1 = poly.bounds
        if self.env is None:
            self.env = (bx0, by0, bx1, by1)
        else:
            e = self.env
            self.env = (min(e[0], bx0), min(e[1], by0), max(e[2], bx1), max(e[3], by1))
        self.libre -= poly.area
        self.grille.marquer(poly, self)

    def aire_enveloppe(self) -> float:
        if self.env is None:
            return 0.0
        return (self.env[2] - self.env[0]) * (self.env[3] - self.env[1])


# --------------------------------------------------------------------------
# Un essai complet
# --------------------------------------------------------------------------
def _placer(plaque: Plaque, forme: Forme, strat: str, poids: float, bruit: float, rng, piece: int) -> bool:
    candidats = []
    for o in forme.orients:
        r = plaque.meilleur(o, strat, poids, bruit, rng)
        if r is not None:
            candidats.append((r[0], len(candidats), o, r[1], r[2]))
    candidats.sort(key=lambda c: (c[0], c[1]))
    for _, _, o, i, j in candidats[:3]:
        if plaque.poser(o, i, j, strat, piece):
            return True
    return False


def executer_essai(
    formes: list[Forme],
    forme_de_piece: list[int],
    ordre: list[int],
    params: Parametres,
    strat: str,
    poids: float,
    bruit: float,
    rng: np.random.Generator,
) -> list[Plaque]:
    plaques: list[Plaque] = []
    echecs: set[tuple[int, int]] = set()
    for p in ordre:
        f = forme_de_piece[p]
        forme = formes[f]
        place = False
        for k, plaque in enumerate(plaques):
            if (f, k) in echecs:
                continue
            if plaque.libre < forme.aire_gonflee or not _placer(plaque, forme, strat, poids, bruit, rng, p):
                echecs.add((f, k))  # une plaque ne se vide jamais : l'échec est définitif
                continue
            place = True
            break
        if not place:
            plaque = Plaque(params)
            plaques.append(plaque)
            if not _placer(plaque, forme, strat, poids, bruit, rng, p):
                raise ErreurPlacement(f"La pièce n°{p + 1} ne rentre pas dans une plaque vide")
    return plaques


def _objectif(plaques: list[Plaque]) -> tuple[int, float]:
    return len(plaques), plaques[-1].aire_enveloppe()


def _configuration(k: int, rng: np.random.Generator, aires: np.ndarray, cotes: np.ndarray):
    """Ordre de placement, stratégie, poids du contact et bruit du k-ième essai."""
    n = len(aires)
    fixes = (("env", 1.0, aires), ("ct", 0.0, aires), ("bl", 0.0, aires), ("lb", 0.0, aires), ("env", 3.0, cotes))
    if k < len(fixes):
        strat, poids, cle = fixes[k]
        return list(np.argsort(-cle, kind="stable")), strat, poids, 0.0
    sigma = float(rng.choice([0.1, 0.25, 0.5]))
    base = aires if rng.random() < 0.7 else cotes
    cle = base * np.exp(rng.normal(0.0, sigma, n))
    strat = STRATEGIES[int(rng.integers(len(STRATEGIES)))]
    poids = float(rng.choice([0.3, 1.0, 3.0, 10.0]))
    bruit = float(rng.choice([0.0, 0.0, 0.02, 0.05]))
    return list(np.argsort(-cle, kind="stable")), strat, poids, bruit


def _travailler(args):
    """Boucle d'essais d'un processus. Renvoie (objectif, placements, nombre d'essais)."""
    polygones, params, graine, echeance, depart, pas = args
    formes, forme_de_piece = construire_formes(polygones, params)
    aires = np.array([p.area for p in polygones])
    cotes = np.array([max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) for p in polygones])
    meilleur = None
    essais = 0
    k = depart
    while True:
        rng = np.random.default_rng([graine, k])
        ordre, strat, poids, bruit = _configuration(k, rng, aires, cotes)
        plaques = executer_essai(formes, forme_de_piece, ordre, params, strat, poids, bruit, rng)
        essais += 1
        obj = _objectif(plaques)
        if meilleur is None or obj < meilleur[0]:
            meilleur = (obj, [pl.placements for pl in plaques])
        k += pas
        if params.essais_max is not None and essais >= params.essais_max:
            break
        if time.time() >= echeance:
            break
    return meilleur[0], meilleur[1], essais


def _resultat(pieces: list[Piece], unites: list[Unite], placements, params: Parametres) -> Resultat:
    plaques = []
    for idx, lot in enumerate(placements):
        pr = PlaqueResultat(index=idx)
        for u, angle, dx, dy in sorted(lot):
            for k, membre in zip(unites[u].indices, unites[u].membres):
                poly = affinity.translate(affinity.rotate(membre, angle, origin=(0, 0)), dx, dy)
                pr.pieces.append(PiecePlacee(piece=pieces[k], polygone=poly, angle=angle))
        pr.pieces.sort(key=lambda pp: pp.piece.id)
        plaques.append(pr)
    return Resultat(parametres=params, plaques=plaques)


def verifier_pieces_plaque(params: Parametres) -> None:
    if params.largeur - 2 * params.marge <= 0 or params.hauteur - 2 * params.marge <= 0:
        raise ErreurPlacement("La marge est trop grande pour la taille de la plaque")
    if params.espacement < 0 or params.marge < 0:
        raise ErreurPlacement("L'espacement et la marge doivent être positifs")
    if params.resolution <= 0:
        raise ErreurPlacement("La résolution doit être positive")


def optimiser(
    pieces: list[Piece],
    params: Parametres,
    rappel: Optional[Callable[[str], None]] = None,
) -> Resultat:
    """Cherche le placement qui utilise le moins de plaques possible."""
    if not pieces:
        raise ErreurPlacement("Aucune pièce à placer")
    verifier_pieces_plaque(params)
    debut = time.time()
    unites = apparier(pieces, params)
    formes, forme_de_unite = construire_formes([u.poly for u in unites], params)
    if any(not formes[f].orients for f in forme_de_unite):
        # une unité (paire) trop grande pour la plaque : on revient aux pièces seules
        unites = apparier(pieces, Parametres(**{**params.__dict__, "appariement": False}))
        formes, forme_de_unite = construire_formes([u.poly for u in unites], params)
    for u, f in enumerate(forme_de_unite):
        if not formes[f].orients:
            raise ErreurPlacement(
                f"La pièce {pieces[unites[u].indices[0]].nom} est trop grande pour la plaque "
                f"({params.largeur:g} x {params.hauteur:g} mm, rotations « {params.rotations} »)"
            )
    polygones = [u.poly for u in unites]

    jobs = params.jobs if params.jobs > 0 else (os.cpu_count() or 1)
    jobs = max(1, min(jobs, 32))
    echeance = debut + params.temps
    taches = [(polygones, params, params.graine, echeance, j, jobs) for j in range(jobs)]
    if jobs == 1:
        sorties = [_travailler(taches[0])]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            sorties = list(pool.map(_travailler, taches))
    obj, placements, _ = min(sorties, key=lambda s: s[0])
    resultat = _resultat(pieces, unites, placements, params)
    resultat.essais = sum(s[2] for s in sorties)
    resultat.duree = time.time() - debut
    if rappel:
        rappel(f"{resultat.essais} essais en {resultat.duree:.1f} s")
    return resultat


# --------------------------------------------------------------------------
# Contrôle indépendant du résultat
# --------------------------------------------------------------------------
def verifier(resultat: Resultat, tolerance: float = 1e-3) -> list[str]:
    """Vérifie bords, marge et espacement sur les polygones réellement produits."""
    p = resultat.parametres
    problemes: list[str] = []
    for plaque in resultat.plaques:
        polys = [pp.polygone for pp in plaque.pieces]
        for pp in plaque.pieces:
            x0, y0, x1, y1 = pp.polygone.bounds
            if (x0 < p.marge - tolerance or y0 < p.marge - tolerance
                    or x1 > p.largeur - p.marge + tolerance or y1 > p.hauteur - p.marge + tolerance):
                problemes.append(f"Plaque {plaque.index + 1} : {pp.piece.nom} dépasse de la zone utile")
        if len(polys) > 1:
            arbre = STRtree(polys)
            for i, poly in enumerate(polys):
                for k in arbre.query(poly.buffer(p.espacement + 1.0)):
                    k = int(k)
                    if k <= i:
                        continue
                    d = poly.distance(polys[k])
                    if d < p.espacement - tolerance:
                        a, b = plaque.pieces[i].piece.nom, plaque.pieces[k].piece.nom
                        problemes.append(
                            f"Plaque {plaque.index + 1} : {a} et {b} à {d:.3f} mm (< {p.espacement:g} mm)"
                        )
    return problemes
