"""Interface graphique (tkinter) : choisir un DXF, régler les paramètres, calculer, enregistrer."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import __version__
from .dxf_io import ecrire_dxf, filtrer_pieces, lire_dxf, lister_calques, petit_cote
from .modeles import Parametres, Piece, Resultat
from .nesting import ErreurPlacement, optimiser, verifier

TOUS_CALQUES = "(tous les calques)"
COULEURS = ["#9ecae1", "#a1d99b", "#fdd0a2", "#bcbddc", "#fcbba1", "#c7e9c0", "#dadaeb", "#fdae6b"]
ROTATIONS = {"Libre (tout angle utile)": "libre", "Multiples de 90°": "90", "Aucune": "aucune"}


def _nombre(texte: str, nom: str, minimum: Optional[float] = None) -> float:
    try:
        v = float(texte.replace(",", ".").strip())
    except ValueError:
        raise ValueError(f"« {nom} » doit être un nombre") from None
    if minimum is not None and v < minimum:
        raise ValueError(f"« {nom} » doit être supérieur ou égal à {minimum:g}")
    return v


class Application(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Découpe isolant {__version__} - optimisation de plaques")
        self.geometry("1180x760")
        self.minsize(980, 620)

        self.pieces: list[Piece] = []
        self.garder: dict[str, bool] = {}
        self.resultat: Optional[Resultat] = None
        self._file: "queue.Queue[tuple]" = queue.Queue()
        self._calcul: Optional[threading.Thread] = None
        self._debut = 0.0

        self.v_fichier = tk.StringVar()
        self.v_calque = tk.StringVar(value=TOUS_CALQUES)
        self.v_profils = tk.StringVar(value="0")
        self.v_largeur = tk.StringVar(value="1500")
        self.v_hauteur = tk.StringVar(value="1000")
        self.v_espacement = tk.StringVar(value="2")
        self.v_marge = tk.StringVar(value="0")
        self.v_rotations = tk.StringVar(value=list(ROTATIONS)[0])
        self.v_temps = tk.StringVar(value="30")
        self.v_appariement = tk.BooleanVar(value=True)
        self.v_separe = tk.BooleanVar(value=False)
        self.v_etat = tk.StringVar(value="Choisissez un fichier DXF contenant les découpes.")

        self._construire()
        self.bind("<Configure>", lambda e: self._redessiner_plus_tard())
        self._redessin = None

    # ------------------------------------------------------------------ interface
    def _construire(self) -> None:
        pad = {"padx": 6, "pady": 3}
        haut = ttk.Frame(self)
        haut.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(haut, text="Fichier DXF :").pack(side="left")
        ttk.Entry(haut, textvariable=self.v_fichier).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(haut, text="Parcourir…", command=self.parcourir).pack(side="left")

        corps = ttk.Frame(self)
        corps.pack(fill="both", expand=True, padx=8, pady=4)
        gauche = ttk.Frame(corps)
        gauche.pack(side="left", fill="y")
        droite = ttk.Frame(corps)
        droite.pack(side="left", fill="both", expand=True, padx=(10, 0))

        # -- lecture du DXF
        lec = ttk.LabelFrame(gauche, text="1. Contours à découper")
        lec.pack(fill="x")
        ttk.Label(lec, text="Calque :").grid(row=0, column=0, sticky="w", **pad)
        self.cb_calque = ttk.Combobox(lec, textvariable=self.v_calque, state="readonly", width=24,
                                      values=[TOUS_CALQUES])
        self.cb_calque.grid(row=0, column=1, sticky="we", **pad)
        self.cb_calque.bind("<<ComboboxSelected>>", lambda e: self.relire())
        ttk.Label(lec, text="Ignorer les profils ≤ (mm) :").grid(row=1, column=0, sticky="w", **pad)
        e = ttk.Entry(lec, textvariable=self.v_profils, width=8)
        e.grid(row=1, column=1, sticky="w", **pad)
        e.bind("<Return>", lambda ev: self.relire())
        e.bind("<FocusOut>", lambda ev: self.relire())
        ttk.Label(lec, text="(épaisseur de l'isolant : écarte les vues de profil d'un plan)",
                  foreground="#666").grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        cols = ("garder", "nom", "dim", "aire")
        self.arbre = ttk.Treeview(lec, columns=cols, show="headings", height=11, selectmode="browse")
        for c, t, w in (("garder", "Garder", 55), ("nom", "Nom", 55), ("dim", "Dimensions (mm)", 130), ("aire", "Aire cm²", 70)):
            self.arbre.heading(c, text=t)
            self.arbre.column(c, width=w, anchor="center")
        defil = ttk.Scrollbar(lec, orient="vertical", command=self.arbre.yview)
        self.arbre.configure(yscrollcommand=defil.set)
        self.arbre.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=(6, 22), pady=3)
        defil.grid(row=3, column=1, sticky="nse", padx=(0, 6), pady=3)
        self.arbre.bind("<Double-1>", self._basculer)
        self.arbre.bind("<space>", self._basculer)
        ttk.Label(lec, text="Double-clic sur une ligne pour garder / ignorer la pièce.",
                  foreground="#666").grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))
        lec.columnconfigure(1, weight=1)

        # -- paramètres
        par = ttk.LabelFrame(gauche, text="2. Paramètres")
        par.pack(fill="x", pady=(8, 0))
        lignes = [("Plaque : largeur (mm)", self.v_largeur), ("Plaque : hauteur (mm)", self.v_hauteur),
                  ("Espacement entre pièces (mm)", self.v_espacement), ("Marge au bord de plaque (mm)", self.v_marge),
                  ("Durée de recherche (s)", self.v_temps)]
        for i, (t, v) in enumerate(lignes):
            ttk.Label(par, text=t).grid(row=i, column=0, sticky="w", **pad)
            ttk.Entry(par, textvariable=v, width=10).grid(row=i, column=1, sticky="w", **pad)
        ttk.Label(par, text="Rotations").grid(row=len(lignes), column=0, sticky="w", **pad)
        ttk.Combobox(par, textvariable=self.v_rotations, values=list(ROTATIONS), state="readonly",
                     width=24).grid(row=len(lignes), column=1, sticky="w", **pad)
        ttk.Checkbutton(par, text="Regrouper les pièces complémentaires (ex. 2 triangles)",
                        variable=self.v_appariement).grid(row=len(lignes) + 1, column=0, columnspan=2, sticky="w", **pad)

        # -- actions
        act = ttk.Frame(gauche)
        act.pack(fill="x", pady=8)
        self.b_calcul = ttk.Button(act, text="3. Calculer", command=self.calculer)
        self.b_calcul.pack(side="left", fill="x", expand=True)
        self.b_enreg = ttk.Button(act, text="4. Enregistrer le DXF…", command=self.enregistrer, state="disabled")
        self.b_enreg.pack(side="left", fill="x", expand=True, padx=(6, 0))
        ttk.Checkbutton(gauche, text="Un fichier DXF par plaque", variable=self.v_separe).pack(anchor="w")

        # -- résultat
        self.zone = tk.Canvas(droite, background="white", highlightthickness=1, highlightbackground="#bbb")
        self.zone.pack(fill="both", expand=True)
        self.barre = ttk.Progressbar(droite, mode="indeterminate")
        self.barre.pack(fill="x", pady=(6, 0))
        ttk.Label(droite, textvariable=self.v_etat, wraplength=760, justify="left").pack(fill="x", pady=(4, 0))
        self._message_vide()

    # ------------------------------------------------------------------ lecture
    def parcourir(self) -> None:
        chemin = filedialog.askopenfilename(title="Choisir le DXF des découpes",
                                            filetypes=[("Fichiers DXF", "*.dxf *.DXF"), ("Tous les fichiers", "*.*")])
        if chemin:
            self.charger(chemin)

    def charger(self, chemin: str) -> None:
        self.v_fichier.set(chemin)
        try:
            calques = lister_calques(chemin)
        except Exception as exc:  # fichier illisible
            messagebox.showerror("Lecture impossible", f"Impossible de lire ce DXF :\n{exc}")
            return
        self.cb_calque["values"] = [TOUS_CALQUES] + [f"{n}  ({k})" for n, k in calques.items()]
        self.v_calque.set(TOUS_CALQUES)
        self.relire()

    def _calque_choisi(self) -> Optional[list[str]]:
        v = self.v_calque.get()
        if v == TOUS_CALQUES or not v:
            return None
        return [v.rsplit("  (", 1)[0]]

    def relire(self) -> None:
        chemin = self.v_fichier.get().strip()
        if not chemin or not Path(chemin).exists():
            return
        try:
            profils = _nombre(self.v_profils.get() or "0", "Ignorer les profils", 0)
            self.config(cursor="watch")
            self.update_idletasks()
            lecture = lire_dxf(chemin, calques=self._calque_choisi())
        except Exception as exc:
            self.config(cursor="")
            messagebox.showerror("Lecture impossible", str(exc))
            return
        self.config(cursor="")
        self.pieces = lecture.pieces
        gardees, _ = filtrer_pieces(self.pieces, ignorer_profils=profils)
        noms_gardes = {p.nom for p in gardees}
        self.garder = {p.nom: p.nom in noms_gardes for p in self.pieces}
        self._remplir_tableau()
        self.resultat = None
        self.b_enreg.config(state="disabled")
        self._message_vide()
        n = sum(self.garder.values())
        texte = f"{len(self.pieces)} contour(s) fermé(s) détecté(s), {n} retenu(s)."
        if len(self.pieces) > 40 or any(max(p.polygone.bounds[2] - p.polygone.bounds[0],
                                            p.polygone.bounds[3] - p.polygone.bounds[1]) > 3000 for p in self.pieces):
            texte += " Ce plan semble contenir cadre / vues multiples : choisissez le calque des découpes."
        if lecture.avertissements:
            texte += "\n" + " ".join(lecture.avertissements[:3])
        self.v_etat.set(texte)

    def _remplir_tableau(self) -> None:
        self.arbre.delete(*self.arbre.get_children())
        for p in self.pieces:
            x0, y0, x1, y1 = p.polygone.bounds
            self.arbre.insert("", "end", iid=p.nom, values=(
                "✔" if self.garder[p.nom] else "✘", p.nom, f"{x1 - x0:.0f} x {y1 - y0:.0f}", f"{p.polygone.area / 100:.0f}"))

    def _basculer(self, event) -> None:
        iid = self.arbre.identify_row(event.y) if event.type == tk.EventType.ButtonPress else self.arbre.focus()
        if iid and iid in self.garder:
            self.garder[iid] = not self.garder[iid]
            v = list(self.arbre.item(iid, "values"))
            v[0] = "✔" if self.garder[iid] else "✘"
            self.arbre.item(iid, values=v)

    # ------------------------------------------------------------------ calcul
    def _parametres(self) -> Parametres:
        return Parametres(
            largeur=_nombre(self.v_largeur.get(), "Largeur", 1),
            hauteur=_nombre(self.v_hauteur.get(), "Hauteur", 1),
            espacement=_nombre(self.v_espacement.get(), "Espacement", 0),
            marge=_nombre(self.v_marge.get(), "Marge", 0),
            temps=_nombre(self.v_temps.get(), "Durée de recherche", 1),
            rotations=ROTATIONS[self.v_rotations.get()],
            appariement=self.v_appariement.get(),
            jobs=0,
        )

    def calculer(self) -> None:
        if self._calcul and self._calcul.is_alive():
            return
        choisies = [p for p in self.pieces if self.garder.get(p.nom)]
        if not choisies:
            messagebox.showwarning("Aucune pièce", "Choisissez d'abord un DXF contenant des contours à découper.")
            return
        try:
            params = self._parametres()
        except ValueError as exc:
            messagebox.showwarning("Paramètre invalide", str(exc))
            return
        self.resultat = None
        self.b_calcul.config(state="disabled")
        self.b_enreg.config(state="disabled")
        self.barre.start(12)
        self._debut = time.time()
        self._suivre_calcul(params)

        def travail() -> None:
            try:
                self._file.put(("ok", optimiser(choisies, params)))
            except ErreurPlacement as exc:
                self._file.put(("erreur", str(exc)))
            except Exception as exc:  # ne jamais laisser l'interface figée
                self._file.put(("erreur", f"Erreur inattendue : {exc}"))

        self._calcul = threading.Thread(target=travail, daemon=True)
        self._calcul.start()
        self.after(200, self._attendre)

    def _suivre_calcul(self, params: Parametres) -> None:
        self._temps_prevu = params.temps
        self.v_etat.set(f"Calcul en cours… (environ {params.temps:g} s)")

    def _attendre(self) -> None:
        try:
            genre, valeur = self._file.get_nowait()
        except queue.Empty:
            ecoule = time.time() - self._debut
            self.v_etat.set(f"Calcul en cours… {ecoule:.0f} s / environ {self._temps_prevu:g} s")
            self.after(250, self._attendre)
            return
        self.barre.stop()
        self.b_calcul.config(state="normal")
        if genre == "erreur":
            self.v_etat.set(valeur)
            messagebox.showerror("Placement impossible", valeur)
            return
        self.resultat = valeur
        self.b_enreg.config(state="normal")
        self._afficher_resume(valeur)
        self.dessiner()

    def _afficher_resume(self, r: Resultat) -> None:
        lignes = [f"{len(r.plaques)} plaque(s) - remplissage global {100 * r.taux_remplissage:.1f} % "
                  f"(chute {100 * (1 - r.taux_remplissage):.1f} %) - {r.essais} essais en {r.duree:.0f} s"]
        for pl in r.plaques:
            l, h = pl.zone_utilisee()
            lignes.append(f"Plaque {pl.index + 1} : {len(pl.pieces)} pièce(s), {100 * r.taux_plaque(pl):.1f} % "
                          f"(zone utilisée {l:.0f} x {h:.0f} mm)")
        pb = verifier(r)
        if pb:
            lignes.append("ATTENTION - contrôle : " + " ; ".join(pb[:3]))
        self.v_etat.set("\n".join(lignes))

    # ------------------------------------------------------------------ dessin
    def _message_vide(self) -> None:
        self.zone.delete("all")
        self.zone.create_text(20, 20, anchor="nw", fill="#888", font=("TkDefaultFont", 11),
                              text="Le plan de découpe s'affichera ici après le calcul.")

    def _redessiner_plus_tard(self) -> None:
        if self.resultat is None:
            return
        if self._redessin:
            self.after_cancel(self._redessin)
        self._redessin = self.after(150, self.dessiner)

    def dessiner(self) -> None:
        r = self.resultat
        self.zone.delete("all")
        if r is None:
            self._message_vide()
            return
        L, H = r.parametres.largeur, r.parametres.hauteur
        n = len(r.plaques)
        W = max(self.zone.winfo_width(), 300)
        Hc = max(self.zone.winfo_height(), 200)
        cols = 1 if n == 1 else 2
        lignes = (n + cols - 1) // cols
        marge, titre = 12, 22
        echelle = min((W - marge * (cols + 1)) / (cols * L), (Hc - (marge + titre) * lignes - marge) / (lignes * H))
        echelle = max(echelle, 0.01)
        for pl in r.plaques:
            ox = marge + (pl.index % cols) * (L * echelle + marge)
            oy = marge + (pl.index // cols) * (H * echelle + marge + titre) + titre

            def pt(x, y):
                return ox + x * echelle, oy + (H - y) * echelle

            self.zone.create_text(ox, oy - 4, anchor="sw", text=f"Plaque {pl.index + 1} - {100 * r.taux_plaque(pl):.1f} %",
                                  font=("TkDefaultFont", 10, "bold"))
            self.zone.create_rectangle(ox, oy, ox + L * echelle, oy + H * echelle, fill="#f4f4f4", outline="#444", width=2)
            for k, pp in enumerate(pl.pieces):
                pts = [c for xy in pp.polygone.exterior.coords for c in pt(*xy)]
                self.zone.create_polygon(pts, fill=COULEURS[k % len(COULEURS)], outline="#222")
                c = pp.polygone.representative_point()
                self.zone.create_text(*pt(c.x, c.y), text=pp.piece.nom, font=("TkDefaultFont", 8))

    # ------------------------------------------------------------------ enregistrement
    def enregistrer(self, chemin: Optional[str] = None) -> list[Path]:
        if self.resultat is None:
            return []
        if chemin is None:
            base = Path(self.v_fichier.get()).stem or "decoupe"
            chemin = filedialog.asksaveasfilename(title="Enregistrer le plan de découpe", defaultextension=".dxf",
                                                  initialfile=f"{base}_plaques.dxf",
                                                  filetypes=[("Fichiers DXF", "*.dxf")])
            if not chemin:
                return []
        try:
            fichiers = ecrire_dxf(chemin, self.resultat, separe=self.v_separe.get())
        except OSError as exc:
            messagebox.showerror("Enregistrement impossible", str(exc))
            return []
        messagebox.showinfo("DXF enregistré", "\n".join(str(f) for f in fichiers))
        return fichiers


def main() -> None:
    Application().mainloop()
