"""Structures de données partagées."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import Polygon


@dataclass(frozen=True)
class Parametres:
    """Réglages du placement (toutes les longueurs en mm)."""

    largeur: float = 1500.0
    hauteur: float = 1000.0
    espacement: float = 2.0      # distance minimale entre deux pièces
    marge: float = 0.0           # distance minimale entre une pièce et le bord de la plaque
    rotations: str = "libre"     # "libre" | "90" | "aucune"
    pas_rotation: float = 0.0    # angles supplémentaires tous les N degrés (0 = désactivé)
    resolution: float = 4.0      # finesse de la grille de recherche (mm)
    temps: float = 20.0          # durée de la recherche (s)
    graine: int = 0
    essais_max: Optional[int] = None
    jobs: int = 1                # nombre de processus (0 = tous les coeurs)
    appariement: bool = True     # regroupe les pièces complémentaires (ex. 2 triangles)


@dataclass
class Piece:
    id: int
    nom: str
    polygone: Polygon
    calque: str = "0"


@dataclass
class PiecePlacee:
    piece: Piece
    polygone: Polygon            # coordonnées dans le repère de la plaque (0,0 = coin bas-gauche)
    angle: float                 # rotation appliquée (degrés)


@dataclass
class PlaqueResultat:
    index: int
    pieces: list[PiecePlacee] = field(default_factory=list)

    @property
    def aire_pieces(self) -> float:
        return sum(p.polygone.area for p in self.pieces)

    def zone_utilisee(self) -> tuple[float, float]:
        """Largeur et hauteur de la boîte englobant les pièces posées."""
        if not self.pieces:
            return 0.0, 0.0
        x0 = min(p.polygone.bounds[0] for p in self.pieces)
        y0 = min(p.polygone.bounds[1] for p in self.pieces)
        x1 = max(p.polygone.bounds[2] for p in self.pieces)
        y1 = max(p.polygone.bounds[3] for p in self.pieces)
        return x1 - x0, y1 - y0


@dataclass
class Resultat:
    parametres: Parametres
    plaques: list[PlaqueResultat]
    essais: int = 0
    duree: float = 0.0

    @property
    def aire_pieces(self) -> float:
        return sum(p.aire_pieces for p in self.plaques)

    @property
    def aire_plaques(self) -> float:
        return len(self.plaques) * self.parametres.largeur * self.parametres.hauteur

    @property
    def taux_remplissage(self) -> float:
        return self.aire_pieces / self.aire_plaques if self.plaques else 0.0

    def taux_plaque(self, plaque: PlaqueResultat) -> float:
        return plaque.aire_pieces / (self.parametres.largeur * self.parametres.hauteur)
