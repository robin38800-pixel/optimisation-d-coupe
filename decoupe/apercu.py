"""Aperçu SVG du résultat (facultatif, pour contrôler visuellement)."""
from __future__ import annotations

from pathlib import Path

from .modeles import Resultat

COULEURS = ["#9ecae1", "#a1d99b", "#fdd0a2", "#bcbddc", "#fcbba1", "#c7e9c0", "#dadaeb", "#fdae6b"]


def ecrire_svg(chemin: str | Path, resultat: Resultat, colonnes: int = 2, ecart: float = 80.0) -> Path:
    p = resultat.parametres
    L, H = p.largeur, p.hauteur
    n = len(resultat.plaques)
    cols = max(1, min(colonnes, n))
    lignes = (n + cols - 1) // cols
    larg = cols * (L + ecart) + ecart
    haut = lignes * (H + ecart + 40) + ecart
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {larg:.0f} {haut:.0f}" width="{larg / 2:.0f}" height="{haut / 2:.0f}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for plaque in resultat.plaques:
        ox = ecart + (plaque.index % cols) * (L + ecart)
        oy = ecart + (plaque.index // cols) * (H + ecart + 40)

        def pt(x, y):  # l'axe y du DXF pointe vers le haut
            return f"{ox + x:.2f},{oy + H - y:.2f}"

        titre = f"Plaque {plaque.index + 1} - {100 * resultat.taux_plaque(plaque):.1f} %"
        out.append(f'<text x="{ox}" y="{oy - 15}" font-size="32" font-family="sans-serif">{titre}</text>')
        out.append(f'<rect x="{ox}" y="{oy}" width="{L}" height="{H}" fill="#f4f4f4" stroke="#444" stroke-width="3"/>')
        for k, pp in enumerate(plaque.pieces):
            pts = " ".join(pt(x, y) for x, y in pp.polygone.exterior.coords)
            out.append(f'<polygon points="{pts}" fill="{COULEURS[k % len(COULEURS)]}" stroke="#222" stroke-width="2"/>')
            c = pp.polygone.representative_point()
            out.append(
                f'<text x="{ox + c.x:.1f}" y="{oy + H - c.y:.1f}" font-size="22" text-anchor="middle" '
                f'font-family="sans-serif">{pp.piece.nom}</text>'
            )
    out.append("</svg>")
    chemin = Path(chemin)
    chemin.write_text("\n".join(out), encoding="utf-8")
    return chemin
