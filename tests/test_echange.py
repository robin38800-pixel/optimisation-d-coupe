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
    assert lignes[0] == "DECOUPE-RESULTAT 1" and lignes[-1] == "FIN"
    assert lignes[1].split()[0] == "PLAQUES" and lignes[1].endswith("1500.000 1000.000")
    assert int(lignes[1].split()[1]) >= 2 and sum(l.startswith("PLAQUE ") for l in lignes) == int(lignes[1].split()[1])
    poses = [l for l in lignes if l.startswith("POSE ")]
    assert len(poses) == 12
    rep, etiq, nom, reste = poses[0][5:].split("|", 3)
    n = int(reste.split()[0])
    assert len(reste.split()) == 1 + 2 * n and rep == etiq.split("-")[0]


def test_cli_echange_erreur_ecrite_dans_le_fichier(tmp_path):
    f = _fichier(tmp_path, _piece_3d([(0, 0), (3000, 0), (3000, 2000), (0, 2000)], "1", 1, "Trop grande", 1))
    res = tmp_path / "res.txt"
    assert main(["--echange", str(f), "--resultat-echange", str(res), "-o", str(tmp_path / "s.dxf"),
                 "--temps", "1", "--jobs", "1"]) == 1
    assert "ERREUR" in res.read_text(encoding="cp1252")
