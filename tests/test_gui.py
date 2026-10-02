import os
import sys
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    pytest.skip("pas d'affichage (lancer avec xvfb-run)", allow_module_level=True)

import ezdxf  # noqa: E402

from decoupe import gui  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    for nom in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(gui.messagebox, nom, lambda *a, **k: None)
    try:
        a = gui.Application()
    except tk.TclError:
        pytest.skip("tkinter inutilisable ici")
    yield a
    a.destroy()


def _attendre(app, delai=90):
    fin = time.time() + delai
    while app._calcul is not None and (app._calcul.is_alive() or not app._file.empty()) and time.time() < fin:
        app.update()
        time.sleep(0.02)
    for _ in range(20):
        app.update()


def test_parcours_complet(app, tmp_path):
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("CADRE")
    msp.add_lwpolyline([(0, 0), (5000, 0), (5000, 3000), (0, 3000)], close=True, dxfattribs={"layer": "CADRE"})
    for k in range(5):
        msp.add_lwpolyline([(k * 600, 0), (k * 600 + 500, 0), (k * 600 + 500, 400), (k * 600, 400)], close=True,
                           dxfattribs={"layer": "FORT"})
    msp.add_lwpolyline([(0, 800), (400, 800), (400, 830), (0, 830)], close=True, dxfattribs={"layer": "FORT"})  # profil
    f = tmp_path / "plan.dxf"
    doc.saveas(f)

    app.charger(str(f))
    assert len(app.pieces) == 7 and len(app.arbre.get_children()) == 7

    app.v_calque.set("FORT  (6)")
    app.v_profils.set("30")
    app.relire()
    assert len(app.pieces) == 6 and sum(app.garder.values()) == 5

    iid = next(iter(app.garder))                     # on retire une pièce à la main
    app.arbre.focus(iid)
    ev = type("E", (), {"type": tk.EventType.KeyPress, "y": 0})()
    app._basculer(ev)
    assert sum(app.garder.values()) == 4

    app.v_temps.set("2")
    app.calculer()
    _attendre(app)
    assert app.resultat is not None and len(app.resultat.plaques) == 1
    assert sum(len(p.pieces) for p in app.resultat.plaques) == 4
    assert str(app.b_enreg["state"]) == "normal"

    fichiers = app.enregistrer(str(tmp_path / "res.dxf"))
    assert fichiers and Path(fichiers[0]).exists()


def test_parametre_invalide(app):
    app.v_espacement.set("abc")
    with pytest.raises(ValueError):
        app._parametres()
    app.v_espacement.set("2,5")
    assert app._parametres().espacement == 2.5
