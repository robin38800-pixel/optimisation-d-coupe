import random

import numpy as np
import pytest

from decoupe.cli import main
from decoupe.echange import lire_brut, pieces_depuis_echange


def _rotation(seed):
    rnd = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rnd.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def _piece_3d(contour2d, rep, qte, nom, seed, melanger=True):
    """Écrit une pièce comme le ferait la macro : arêtes 3D en désordre, plan quelconque."""
    r = _rotation(seed)
    decal = np.array([123.4, -56.7, 890.1])
    pts3 = [r @ np.array([x, y, 0.0]) + decal for x, y in contour2d]
    normale = r @ np.array([0.0, 0.0, 1.0])
    aretes = [(pts3[i], pts3[(i + 1) % len(pts3)]) for i in range(len(pts3))]
    if melanger:
        rnd = random.Random(seed)
        rnd.shuffle(aretes)
        aretes = [(b, a) if rnd.random() < 0.5 else (a, b) for a, b in aretes]
    lignes = [f"PIECE|{rep}|{qte}|{nom}", "NORMALE " + " ".join(f"{v:.6f}" for v in normale)]
    for a, b in aretes:
        lignes.append("P " + " ".join(f"{v:.4f}" for v in (*a, *b)).replace(".", ","))  # virgule décimale FR
    return lignes


def _fichier(tmp_path, *blocs):
    f = tmp_path / "echange.txt"
    f.write_text("\n".join(["DECOUPE-ECHANGE 1", *[l for b in blocs for l in b], "FIN"]), encoding="cp1252")
    return f


RECT = [(0, 0), (800, 0), (800, 500), (0, 500)]
TRAPEZE = [(0, 0), (600, 0), (500, 300), (100, 300)]
L = [(0, 0), (400, 0), (400, 150), (150, 150), (150, 400), (0, 400)]


def test_lecture_quantites_et_formes(tmp_path):
    f = _fichier(tmp_path, _piece_3d(RECT, "1", 3, "Isolant A", 1), _piece_3d(L, "2", 1, "Isolant éL", 2),
                 _piece_3d(TRAPEZE, "3", 2, "Isolant C", 3))
    pieces, avert = pieces_depuis_echange(f)
    assert avert == []
    assert [p.nom for p in pieces] == ["1-1", "1-2", "1-3", "2", "3-1", "3-2"]
    assert round(pieces[0].polygone.area) == 800 * 500
    assert round(pieces[3].polygone.area) == 400 * 400 - 250 * 250
    assert round(pieces[4].polygone.area) == (600 + 400) * 300 // 2


def test_chaine_cassee_signalee(tmp_path):
    bloc = _piece_3d(RECT, "9", 1, "Cassée", 5, melanger=False)
    del bloc[-1]                                   # une arête manquante : contour ouvert
    pieces, avert = pieces_depuis_echange(_fichier(tmp_path, bloc))
    assert pieces == [] and any("pas fermé" in a for a in avert)


def test_en_tete_invalide(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("n'importe quoi")
    with pytest.raises(ValueError):
        lire_brut(f)


def test_cli_echange_de_bout_en_bout(tmp_path):
    f = _fichier(tmp_path, _piece_3d(RECT, "1", 4, "A", 1), _piece_3d(TRAPEZE, "2", 6, "B", 2), _piece_3d(L, "3", 2, "C", 3))
    res = tmp_path / "res.txt"
    dxf = tmp_path / "res.dxf"
    code = main(["--echange", str(f), "--resultat-echange", str(res), "-o", str(dxf), "--temps", "3", "--jobs", "1",
                 "--espacement", "3"])
    assert code == 0 and dxf.exists()
    lignes = res.read_text(encoding="cp1252").splitlines()
    assert lignes[0] == "DECOUPE-RESULTAT 2" and lignes[-1] == "FIN"
    assert lignes[1].split()[0] == "PLAQUES" and lignes[1].endswith("1500.000 1000.000")
    assert int(lignes[1].split()[1]) >= 2 and sum(l.startswith("PLAQUE ") for l in lignes) == int(lignes[1].split()[1])
    poses = [l for l in lignes if l.startswith("POSE ")]
    assert len(poses) == 12
    rep, etiq, nom, transfo, reste = poses[0][5:].split("|", 4)
    n = int(reste.split()[0])
    assert len(reste.split()) == 1 + 2 * n and rep == etiq.split("-")[0] and len(transfo.split()) == 3


def test_cli_echange_erreur_ecrite_dans_le_fichier(tmp_path):
    f = _fichier(tmp_path, _piece_3d([(0, 0), (3000, 0), (3000, 2000), (0, 2000)], "1", 1, "Trop grande", 1))
    res = tmp_path / "res.txt"
    assert main(["--echange", str(f), "--resultat-echange", str(res), "-o", str(tmp_path / "s.dxf"),
                 "--temps", "1", "--jobs", "1"]) == 1
    assert "ERREUR" in res.read_text(encoding="cp1252")


def _piece_vue(contour2d, rep, qte, nom, vue, base):
    """Pièce comme l'écrira la macro avec une vue standard : les points 3D sont (x, y, 0) du repère de la pièce."""
    n = len(contour2d)
    lignes = [f"PIECE|{rep}|{qte}|{nom}", "NORMALE 0 0 1", f"VUE {vue}", "BASE " + " ".join(str(v) for v in base)]
    for i in range(n):
        (x1, y1), (x2, y2) = contour2d[i], contour2d[(i + 1) % n]
        lignes.append(f"P {x1} {y1} 0 {x2} {y2} 0")
    return lignes


def _verifie_transformations(res, contours_par_rep):
    """Pour chaque POSE : rotation puis translation du contour d'origine == contour placé."""
    import math
    ecart_max = 0.0
    for l in res.read_text(encoding="cp1252").splitlines():
        if not l.startswith("POSE "):
            continue
        rep, etiq, nom, transfo, reste = l[5:].split("|", 4)
        ang, tx, ty = (float(v) for v in transfo.split())
        t = reste.split()
        placé = [(float(t[1 + 2 * i]), float(t[2 + 2 * i])) for i in range(int(t[0]))]
        c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        origine = contours_par_rep[rep]
        attendu = [(c * x - s * y + tx, s * x + c * y + ty) for x, y in origine]
        # le sommet de départ peut être décalé : on teste toutes les rotations circulaires
        meilleur = min(
            max(math.hypot(attendu[(i + k) % len(attendu)][0] - placé[i][0], attendu[(i + k) % len(attendu)][1] - placé[i][1])
                for i in range(len(placé)))
            for k in range(len(placé))
        )
        ecart_max = max(ecart_max, meilleur)
    return ecart_max


@pytest.mark.parametrize("appariement", [True, False])
def test_transformation_rigide_des_poses(tmp_path, appariement):
    base_face = (1, 0, 0, 0, 1, 0)                       # vue de face : x = X, y = Y
    triangle_a = [(0, 0), (700, 0), (0, 450)]
    triangle_b = [(700, 0), (700, 450), (0, 450)]       # complément : s'apparie avec triangle_a
    f = _fichier(tmp_path,
                 _piece_vue(RECT, "1", 3, "Rect", "Face", base_face),
                 _piece_vue(L, "2", 2, "L", "Face", base_face),
                 _piece_vue(triangle_a, "3", 2, "TriA", "Face", base_face),
                 _piece_vue(triangle_b, "4", 2, "TriB", "Face", base_face))
    res = tmp_path / "res.txt"
    args = ["--echange", str(f), "--resultat-echange", str(res), "-o", str(tmp_path / "s.dxf"), "--temps", "3",
            "--jobs", "1", "--espacement", "3"]
    assert main(args + ([] if appariement else ["--sans-appariement"])) == 0
    pieces, _ = pieces_depuis_echange(f)
    contours = {}
    for p in pieces:
        contours.setdefault(p.nom.rsplit("-", 1)[0], list(p.polygone.exterior.coords)[:-1])
    assert _verifie_transformations(res, contours) < 0.01


def test_base_de_vue_imposee(tmp_path):
    """Avec BASE, les coordonnées 2D sont celles de la vue SolidWorks (ici la vue de dessus : y = -Z)."""
    base_dessus = (1, 0, 0, 0, 0, -1)
    lignes = ["PIECE|1|1|Dessus", "NORMALE 0 1 0", "VUE Dessus", "BASE 1 0 0 0 0 -1"]
    pts = [(0, 0, 0), (300, 0, 0), (300, 0, -200), (0, 0, -200)]       # 3D : Z négatif = vers le haut de la vue
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        lignes.append("P " + " ".join(str(v) for v in (*a, *b)))
    pieces, avert = pieces_depuis_echange(_fichier(tmp_path, lignes))
    assert avert == []
    x0, y0, x1, y1 = pieces[0].polygone.bounds
    assert (round(x0), round(y0), round(x1), round(y1)) == (0, 0, 300, 200)
