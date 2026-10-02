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
