import math

import ezdxf

from decoupe.dxf_io import ecrire_dxf, lire_dxf
from decoupe.modeles import Parametres
from decoupe.nesting import optimiser


def _doc():
    doc = ezdxf.new("R2010")
    return doc, doc.modelspace()


def test_lecture_polylignes_cercle_et_segments(tmp_path):
    doc, msp = _doc()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    msp.add_circle((300, 300), 40)
    # triangle fait de 3 LINE séparées, dessinées dans le désordre et dans des sens variés
    msp.add_line((500, 0), (600, 0))
    msp.add_line((550, 80), (600, 0))
    msp.add_line((500, 0), (550, 80))
    # contour ouvert : doit être signalé et ignoré
    msp.add_line((900, 0), (950, 0))
    msp.add_text("annotation")
    f = tmp_path / "e.dxf"
    doc.saveas(f)

    lecture = lire_dxf(f)
    aires = sorted(round(p.polygone.area) for p in lecture.pieces)
    assert len(lecture.pieces) == 3
    assert aires[0] == 4000                       # triangle 100 x 80 / 2
    assert aires[1] == 5000                       # rectangle
    assert abs(aires[2] - math.pi * 40**2) < 15   # cercle discrétisé
    assert any("ouvert" in a for a in lecture.avertissements)


def test_lecture_arc_et_bulge(tmp_path):
    doc, msp = _doc()
    # demi-disque : un arc + sa corde
    msp.add_arc((0, 0), 50, 0, 180)
    msp.add_line((-50, 0), (50, 0))
    # rectangle arrondi via bulge (quart de cercle aux coins)
    k = math.tan(math.radians(90) / 4)
    msp.add_lwpolyline([(10, 0, 0, 0, 0), (90, 0, 0, 0, k), (100, 10, 0, 0, 0), (100, 90, 0, 0, k),
                        (90, 100, 0, 0, 0), (10, 100, 0, 0, k), (0, 90, 0, 0, 0), (0, 10, 0, 0, k)],
                       format="xyseb", close=True)
    f = tmp_path / "e.dxf"
    doc.saveas(f)
    pieces = lire_dxf(f).pieces
    assert len(pieces) == 2
    aires = sorted(p.polygone.area for p in pieces)
    assert abs(aires[0] - math.pi * 50**2 / 2) < 10
    assert abs(aires[1] - (100 * 100 - (4 - math.pi) * 10**2)) < 10


def test_filtre_calque_et_blocs(tmp_path):
    doc, msp = _doc()
    doc.layers.add("A")
    doc.layers.add("B")
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "A"})
    msp.add_lwpolyline([(0, 0), (20, 0), (20, 20), (0, 20)], close=True, dxfattribs={"layer": "B"})
    bloc = doc.blocks.new("B1")
    bloc.add_lwpolyline([(0, 0), (30, 0), (30, 30), (0, 30)], close=True)
    msp.add_blockref("B1", (500, 500), dxfattribs={"layer": "A"})
    f = tmp_path / "e.dxf"
    doc.saveas(f)
    assert len(lire_dxf(f).pieces) == 3
    assert [round(p.polygone.area) for p in lire_dxf(f, calques=["b"]).pieces] == [400]


def test_ecriture_dxf(tmp_path):
    doc, msp = _doc()
    for k in range(3):
        msp.add_lwpolyline([(k * 600, 0), (k * 600 + 500, 0), (k * 600 + 500, 400), (k * 600, 400)], close=True)
    f = tmp_path / "e.dxf"
    doc.saveas(f)
    pieces = lire_dxf(f).pieces
    res = optimiser(pieces, Parametres(temps=1, essais_max=1))
    sortie = tmp_path / "s.dxf"
    assert ecrire_dxf(sortie, res) == [sortie]
    relu = ezdxf.readfile(sortie)
    decoupes = [e for e in relu.modelspace() if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "DECOUPES"]
    plaques = [e for e in relu.modelspace() if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "PLAQUE"]
    assert len(decoupes) == 3 and len(plaques) == len(res.plaques)

    fichiers = ecrire_dxf(tmp_path / "p.dxf", res, separe=True)
    assert [x.name for x in fichiers][0] == "p_plaque1.dxf"
