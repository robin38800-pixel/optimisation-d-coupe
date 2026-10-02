import pytest
from shapely.geometry import Polygon

from decoupe.modeles import Parametres, Piece
from decoupe.nesting import ErreurPlacement, optimiser, verifier


def rect(w, h):
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


def pieces(*polys):
    return [Piece(i, f"P{i + 1:03d}", p) for i, p in enumerate(polys)]


def rapide(**kw):
    base = dict(temps=2, essais_max=3, jobs=1)
    base.update(kw)
    return Parametres(**base)


def test_pavage_parfait_sans_espacement():
    res = optimiser(pieces(*[rect(500, 500)] * 6), rapide(espacement=0))
    assert len(res.plaques) == 1
    assert res.taux_remplissage == pytest.approx(0.5, rel=1e-6) or res.taux_remplissage > 0.49
    assert verifier(res) == []


def test_deux_plaques_necessaires():
    res = optimiser(pieces(*[rect(740, 490)] * 5), rapide(espacement=2))
    # 5 pièces de 740 x 490 : 2 par rangée x 2 rangées = 4 par plaque
    assert len(res.plaques) == 2
    assert verifier(res) == []


def test_espacement_et_marge_respectes():
    ps = pieces(*[rect(300, 200)] * 12, Polygon([(0, 0), (400, 0), (0, 250)]))
    for esp, marge in [(5, 0), (0, 10), (12, 20)]:
        res = optimiser(ps, rapide(espacement=esp, marge=marge))
        assert verifier(res) == [], (esp, marge)


def test_rotation_necessaire():
    grande = pieces(rect(800, 1400))  # ne tient que tournée (1400 <= 1500, 800 <= 1000)
    with pytest.raises(ErreurPlacement):
        optimiser(grande, rapide(rotations="aucune"))
    res = optimiser(grande, rapide(rotations="libre"))
    assert len(res.plaques) == 1 and res.plaques[0].pieces[0].angle in (90.0, 270.0)


def test_piece_trop_grande():
    with pytest.raises(ErreurPlacement):
        optimiser(pieces(rect(2000, 2000)), rapide())


def test_aires_et_formes_conservees():
    polys = [Polygon([(0, 0), (400, 0), (0, 300)]), rect(250, 130), Polygon([(0, 0), (300, 0), (300, 100), (100, 100), (100, 300), (0, 300)])]
    res = optimiser(pieces(*polys), rapide())
    places = sorted((pp.piece.id, round(pp.polygone.area, 3), pp.polygone.is_valid) for pl in res.plaques for pp in pl.pieces)
    assert places == [(i, round(p.area, 3), True) for i, p in enumerate(polys)]


def test_appariement_de_triangles_complementaires():
    # 4 rectangles de 740 x 490 découpés en diagonale : 8 triangles. Avec appariement ils tiennent sur 1 plaque.
    tri = []
    for _ in range(4):
        tri += [Polygon([(0, 0), (740, 0), (0, 490)]), Polygon([(740, 0), (740, 490), (0, 490)])]
    res = optimiser(pieces(*tri), rapide(espacement=2, temps=5, essais_max=10))
    assert len(res.plaques) == 1
    assert verifier(res) == []
    res2 = optimiser(pieces(*tri), rapide(espacement=2, appariement=False))
    assert verifier(res2) == []


def test_reproductibilite():
    ps = pieces(*[rect(130 + 17 * i, 90 + 11 * i) for i in range(10)])
    a = optimiser(ps, rapide(graine=3))
    b = optimiser(ps, rapide(graine=3))
    assert [len(p.pieces) for p in a.plaques] == [len(p.pieces) for p in b.plaques]
    assert [pp.polygone.bounds for pp in a.plaques[0].pieces] == [pp.polygone.bounds for pp in b.plaques[0].pieces]


def test_plusieurs_processus():
    res = optimiser(pieces(*[rect(300, 200)] * 8), Parametres(temps=2, jobs=2))
    assert len(res.plaques) == 1 and verifier(res) == []
