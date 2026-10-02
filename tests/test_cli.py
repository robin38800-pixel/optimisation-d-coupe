import sys
from pathlib import Path

import ezdxf

from decoupe.cli import main

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "exemples"))
import generer_exemple  # noqa: E402


def test_cli_de_bout_en_bout(tmp_path, capsys):
    entree = tmp_path / "pieces.dxf"
    generer_exemple.main(str(entree), n=14, graine=5)
    sortie = tmp_path / "res.dxf"
    code = main([str(entree), "-o", str(sortie), "--temps", "3", "--jobs", "1", "--espacement", "3",
                 "--apercu", str(tmp_path / "a.svg")])
    assert code == 0
    texte = capsys.readouterr().out
    assert "plaque(s)" in texte and "remplissage" in texte
    msp = ezdxf.readfile(sortie).modelspace()
    assert sum(1 for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "DECOUPES") == 14
    assert (tmp_path / "a.svg").read_text().startswith("<svg")


def test_cli_dxf_sans_contour(tmp_path):
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (10, 0))
    f = tmp_path / "vide.dxf"
    doc.saveas(f)
    assert main([str(f), "-o", str(tmp_path / "s.dxf")]) == 2


def test_cli_lister_et_ignorer_profils(tmp_path, capsys):
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300)], close=True)
    msp.add_lwpolyline([(0, 500), (400, 500), (400, 530), (0, 530)], close=True)  # profil 30 mm
    f = tmp_path / "plan.dxf"
    doc.saveas(f)
    assert main([str(f), "--lister"]) == 0
    assert "2 contour(s)" in capsys.readouterr().out
    sortie = tmp_path / "s.dxf"
    assert main([str(f), "-o", str(sortie), "--ignorer-profils", "30", "--temps", "1", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 pièces lues" in out and "P002" in out
