"""Échange avec SolidWorks : la macro écrit un fichier texte, l'application répond par un autre.

Fichier d'entrée (écrit par la macro, longueurs en mm) ::

    DECOUPE-ECHANGE 1
    PIECE|<repère>|<quantité>|<nom de la pièce>
    NORMALE nx ny nz                 (normale de la grande face de la pièce)
    P x y z  x y z  x y z ...        (polyligne 3D d'une arête du contour extérieur)
    P ...
    PIECE|...                        (pièce suivante)
    FIN

Fichier de sortie (écrit par l'application, coordonnées dans le repère de chaque plaque) ::

    DECOUPE-RESULTAT 1
    PLAQUES <n> <largeur> <hauteur>
    PLAQUE <k> <taux de remplissage en %>
    POSE <repère>|<étiquette>|<nom>|<nombre de points> x1 y1 x2 y2 ...
    FIN
    (ou, en cas d'échec :  ERREUR <message>)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon

from .dxf_io import _assembler, _vers_polygone
from .modeles import Piece, Resultat

EN_TETE_ENTREE = "DECOUPE-ECHANGE"
EN_TETE_SORTIE = "DECOUPE-RESULTAT"


@dataclass
class PieceBrute:
    repere: str
    quantite: int
    nom: str
    normale: tuple[float, float, float] = (0.0, 0.0, 1.0)
    polylignes: list[np.ndarray] = field(default_factory=list)   # chaque tableau (n, 3)


def _lire_texte(chemin: Path) -> str:
    donnees = chemin.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return donnees.decode(enc)
        except UnicodeDecodeError:
            continue
    return donnees.decode("latin-1", errors="replace")


def _nombres(texte: str) -> list[float]:
    return [float(t) for t in texte.replace(",", ".").split()]


def lire_brut(chemin: str | Path) -> list[PieceBrute]:
    lignes = [l.strip() for l in _lire_texte(Path(chemin)).splitlines() if l.strip()]
    if not lignes or not lignes[0].startswith(EN_TETE_ENTREE):
        raise ValueError("Ce n'est pas un fichier d'échange SolidWorks valide (en-tête manquant)")
    pieces: list[PieceBrute] = []
    for l in lignes[1:]:
        if l.startswith("PIECE|"):
            champs = l.split("|", 3)
            if len(champs) < 4:
                raise ValueError(f"Ligne PIECE incomplète : {l}")
            try:
                q = int(float(champs[2].replace(",", ".")))
            except ValueError:
                raise ValueError(f"Quantité illisible pour {champs[1]} : « {champs[2]} »") from None
            pieces.append(PieceBrute(repere=champs[1].strip(), quantite=q, nom=champs[3].strip()))
        elif l.startswith("NORMALE") and pieces:
            n = _nombres(l[len("NORMALE"):])
            if len(n) != 3:
                raise ValueError(f"Normale invalide : {l}")
            pieces[-1].normale = (n[0], n[1], n[2])
        elif l.startswith("P ") and pieces:
            v = _nombres(l[1:])
            if len(v) >= 6 and len(v) % 3 == 0:
                pieces[-1].polylignes.append(np.array(v).reshape(-1, 3))
        # FIN, lignes de commentaire : ignorées
    return pieces


def _base_plan(normale: tuple[float, float, float]):
    n = np.array(normale, float)
    norme = np.linalg.norm(n)
    if norme < 1e-9:
        raise ValueError("normale nulle")
    n /= norme
    a = np.eye(3)[int(np.argmin(np.abs(n)))]       # axe le moins aligné avec la normale
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)                               # (u, v, n) direct : vue depuis l'extérieur de la face
    return u, v


def polygone_de(p: PieceBrute, avertissements: list[str]) -> Polygon | None:
    """Contour extérieur 2D d'une pièce : projette les arêtes sur le plan de la face puis les chaîne."""
    try:
        u, v = _base_plan(p.normale)
    except ValueError as exc:
        avertissements.append(f"{p.repere} : {exc}")
        return None
    chaines = []
    for pl in p.polylignes:
        pts2d = np.column_stack([pl @ u, pl @ v])
        if len(pts2d) >= 2:
            chaines.append([(float(x), float(y)) for x, y in pts2d])
    if not chaines:
        avertissements.append(f"{p.repere} ({p.nom}) : aucun contour reçu")
        return None
    fermes, _ = _assembler(chaines, 0.1)
    candidats = []
    for pts in fermes:
        poly = _vers_polygone(pts, 1.0, avertissements, p.repere)
        if poly is not None:
            candidats.append(poly)
    if not candidats:
        avertissements.append(f"{p.repere} ({p.nom}) : le contour reçu n'est pas fermé")
        return None
    return max(candidats, key=lambda g: g.area)


def pieces_depuis_echange(chemin: str | Path) -> tuple[list[Piece], list[str]]:
    """Pièces prêtes à placer (une par exemplaire, selon les quantités) et avertissements."""
    avertissements: list[str] = []
    pieces: list[Piece] = []
    for brute in lire_brut(chemin):
        if brute.quantite <= 0:
            avertissements.append(f"{brute.repere} ({brute.nom}) : quantité {brute.quantite}, ignorée")
            continue
        poly = polygone_de(brute, avertissements)
        if poly is None:
            continue
        for k in range(brute.quantite):
            nom = brute.repere if brute.quantite == 1 else f"{brute.repere}-{k + 1}"
            pieces.append(Piece(id=len(pieces), nom=nom, polygone=poly, calque=brute.nom))
    return pieces, avertissements


def _num(x: float) -> str:
    return f"{x:.3f}"


def ecrire_resultat(chemin: str | Path, resultat: Resultat) -> None:
    p = resultat.parametres
    out = [f"{EN_TETE_SORTIE} 1", f"PLAQUES {len(resultat.plaques)} {_num(p.largeur)} {_num(p.hauteur)}"]
    for pl in resultat.plaques:
        out.append(f"PLAQUE {pl.index + 1} {100 * resultat.taux_plaque(pl):.1f}")
        for pp in pl.pieces:
            pts = list(pp.polygone.exterior.coords)[:-1]
            coords = " ".join(f"{_num(x)} {_num(y)}" for x, y in pts)
            nom = pp.piece.nom
            repere = nom.rsplit("-", 1)[0] if "-" in nom and nom.rsplit("-", 1)[1].isdigit() else nom
            out.append(f"POSE {repere}|{nom}|{pp.piece.calque}|{len(pts)} {coords}")
    out.append("FIN")
    Path(chemin).write_text("\n".join(out) + "\n", encoding="cp1252", errors="replace")


def ecrire_erreur(chemin: str | Path, message: str) -> None:
    Path(chemin).write_text(f"{EN_TETE_SORTIE} 1\nERREUR {message}\n", encoding="cp1252", errors="replace")
