"""Auto-test de l'application installée : `DecoupeIsolant --autotest fichier.txt`."""
from __future__ import annotations

import tempfile
import traceback
from pathlib import Path


def lancer(sortie: str) -> int:
    """Lit un DXF, optimise sur 2 processus, écrit un DXF, puis note le verdict dans `sortie`."""
    try:
        import ezdxf

        from .dxf_io import ecrire_dxf, lire_dxf
        from .modeles import Parametres
        from .nesting import optimiser, verifier

        with tempfile.TemporaryDirectory() as tmp:
            doc = ezdxf.new("R2010")
            msp = doc.modelspace()
            for k in range(6):
                msp.add_lwpolyline([(k * 700, 0), (k * 700 + 600, 0), (k * 700 + 300, 400)], close=True)
            entree = Path(tmp) / "e.dxf"
            doc.saveas(entree)
            pieces = lire_dxf(entree).pieces
            res = optimiser(pieces, Parametres(temps=2, jobs=2))
            erreurs = verifier(res)
            fichiers = ecrire_dxf(Path(tmp) / "s.dxf", res)
            assert len(pieces) == 6 and not erreurs and fichiers[0].exists()
        texte = f"OK {len(pieces)} pièces, {len(res.plaques)} plaque(s), {res.essais} essais"
        code = 0
    except Exception:
        texte = "ECHEC\n" + traceback.format_exc()
        code = 1
    Path(sortie).write_text(texte, encoding="utf-8")
    return code
