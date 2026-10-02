"""Génère un DXF de démonstration : pièces variées (rectangles, trapèzes, L, triangles, arcs)."""
import math
import random
import sys

import ezdxf


def main(sortie: str = "exemples/exemple.dxf", n: int = 45, graine: int = 1) -> None:
    rnd = random.Random(graine)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    x = 0.0
    for _ in range(n):
        genre = rnd.choice(["rect", "rect", "trapeze", "L", "triangle", "pentagone", "arrondi"])
        w, h = rnd.uniform(120, 520), rnd.uniform(100, 420)
        if genre == "rect":
            pts = [(0, 0), (w, 0), (w, h), (0, h)]
        elif genre == "trapeze":
            d = rnd.uniform(0.15, 0.4) * w
            pts = [(0, 0), (w, 0), (w - d, h), (d / 2, h)]
        elif genre == "L":
            a, b = rnd.uniform(0.3, 0.6) * w, rnd.uniform(0.3, 0.6) * h
            pts = [(0, 0), (w, 0), (w, b), (a, b), (a, h), (0, h)]
        elif genre == "triangle":
            pts = [(0, 0), (w, 0), (rnd.uniform(0, w), h)]
        elif genre == "pentagone":
            pts = [(0, h * 0.4), (w * 0.5, 0), (w, h * 0.4), (w * 0.8, h), (w * 0.2, h)]
        else:  # rectangle à coins arrondis (bulges)
            r = min(w, h) * 0.2
            k = math.tan(math.radians(90) / 4)
            msp.add_lwpolyline(
                [(x + r, 0, 0, 0, 0), (x + w - r, 0, 0, 0, k), (x + w, r, 0, 0, 0), (x + w, h - r, 0, 0, k),
                 (x + w - r, h, 0, 0, 0), (x + r, h, 0, 0, k), (x, h - r, 0, 0, 0), (x, r, 0, 0, k)],
                format="xyseb", close=True)
            x += w + 50
            continue
        msp.add_lwpolyline([(x + px, py) for px, py in pts], close=True)
        x += w + 50
    doc.saveas(sortie)
    print(f"{n} pièces écrites dans {sortie}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
