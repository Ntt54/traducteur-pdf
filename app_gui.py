#!/usr/bin/env python3
"""
=============================================================
  TRADUCTEUR PDF v8 — INTERFACE MODERNE
  Design professionnel, navigation par onglets,
  prévisualisation, statistiques, configuration avancée.
=============================================================
"""

import os, sys, queue, threading, json, re, time, datetime, hashlib, subprocess, shutil, urllib.parse, glob, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinter import font as tkfont
from pathlib import Path

import traduire_pdfs_v2 as moteur
from moteur.editeur import sauvegarder_edits, charger_edits
from moteur.profils import lister_profils, sauvegarder_profil, charger_profil, supprimer_profil
from moteur.traducteur import argos_disponible, modele_offline_installe, init_modele_offline
from moteur.convertisseur_epub import convertir_epub
from moteur.revision import extraire_nom_base_de_sortie
import stats_manager as stats
import themes as th

# ── Constantes ──
LANGUES = [
    ("Anglais", "en"), ("Fran\u00e7ais", "fr"), ("Espagnol", "es"),
    ("Allemand", "de"), ("Italien", "it"), ("Portugais", "pt"),
    ("Chinois", "zh-CN"), ("Japonais", "ja"), ("Russe", "ru"),
    ("Arabe", "ar"), ("N\u00e9erlandais", "nl"),
]
LABEL_VERS_CODE = {lbl: code for lbl, code in LANGUES}
CODE_VERS_LABEL = {code: lbl for lbl, code in LANGUES}

FORMATS = [("PDF", "pdf"), ("TXT", "txt"), ("Markdown", "md"), ("DOCX", "docx")]

FICHIER_PROJET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projet_sauvegarde.json")
APP_NAME = "Traducteur PDF"
APP_VERSION = "8.0"


class App:
    def __init__(self, root):
        self.root = root
        self.queue = queue.Queue()
        self.worker = None
        self.current_theme_name = th.DEFAULT_THEME
        self._theme = th.get(self.current_theme_name)
        self._selected_pdfs_cache = []
        self._full_log = ""
        self._animation_id = None
        self._session_start = 0
        self._filtered = None

        root.title(f"{APP_NAME} v{APP_VERSION}")
        root.geometry("1200x880")
        root.minsize(960, 740)

        try:
            img = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__),
                                "assets", "icons", "traducteur-pdf-64.png"))
            root.iconphoto(True, img)
        except Exception:
            pass

        self._init_styles()
        self._build_ui()
        self._apply_theme()
        self._setup_dnd()

        self.root.after(100, self._creer_structure_dossier)
        self.root.after(200, self._charger_projet_auto)
        self.root.after(300, self._pomper_queue)
        self.root.after(400, self._setup_clipboard)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── INIT STYLES (modern typography) ──
    def _init_styles(self):
        import platform as _plat
        _sys = _plat.system()
        if _sys == "Darwin":
            _base = "SF Pro Display"
        elif _sys == "Windows":
            _base = "Segoe UI"
        else:
            try:
                tkfont.nametofont("Noto Sans")
                _base = "Noto Sans"
            except tk.TclError:
                _base = "DejaVu Sans"

        try:
            tkfont.nametofont("JetBrains Mono")
            _mono = "JetBrains Mono"
        except tk.TclError:
            try:
                tkfont.nametofont("Noto Sans Mono")
                _mono = "Noto Sans Mono"
            except tk.TclError:
                _mono = "Courier"

        self.f_title     = tkfont.Font(family=_base, size=20, weight="bold")
        self.f_header    = tkfont.Font(family=_base, size=16, weight="bold")
        self.f_subheader = tkfont.Font(family=_base, size=14, weight="bold")
        self.f_body      = tkfont.Font(family=_base, size=12)
        self.f_sub       = tkfont.Font(family=_base, size=11)
        self.f_lbl       = tkfont.Font(family=_base, size=11, weight="bold")
        self.f_btn       = tkfont.Font(family=_base, size=11, weight="bold")
        self.f_mono      = tkfont.Font(family=_mono, size=10)
        self.f_small     = tkfont.Font(family=_base, size=10)
        self.f_tab       = tkfont.Font(family=_base, size=11, weight="bold")
        self.f_big       = tkfont.Font(family=_base, size=32, weight="bold")

    # ── THÈME ──
    def _apply_theme(self):
        T = self._theme
        bg, card, card2, fg, muted, accent = T["bg"], T["card"], T["card2"], T["fg"], T["muted"], T["accent"]
        self.root.configure(bg=bg)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=bg, foreground=fg, font=self.f_sub)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TLabelframe", background=card, foreground=fg, borderwidth=0, relief="flat")
        style.configure("TLabelframe.Label", background=card, foreground=accent, font=self.f_lbl)

        style.configure("TNotebook", background=bg, borderwidth=0, tabmargins=[4, 4, 4, 0])
        style.configure("TNotebook.Tab",
                       background=card, foreground=muted,
                       padding=[24, 12], borderwidth=0,
                       font=self.f_tab)
        style.map("TNotebook.Tab",
                  background=[("selected", accent), ("active", card2)],
                  foreground=[("selected", "#FFFFFF"), ("active", fg)],
                  expand=[("selected", [1, 1, 1, 0])])

        # ── Combobox & Spinbox ──
        style.configure("TCombobox", fieldbackground=card2, background=card, foreground=fg,
                       arrowcolor=fg, bordercolor=card2, padding=5, selectbackground=card)
        style.configure("TSpinbox", fieldbackground=card2, background=card, foreground=fg,
                       arrowcolor=fg, bordercolor=card2, padding=5, selectbackground=card)

        # ── Correction du fond des dropdowns Combobox (popdown listbox) ──
        # La liste déroulante du Combobox est une fenêtre popup native qui ne suit pas
        # le thème ttk. On utilise la sous-partie "Listbox" du style TCombobox.
        style.configure("TCombobox.Listbox",
                       background=card2,
                       foreground=fg,
                       selectbackground=accent,
                       selectforeground="#FFFFFF",
                       fieldbackground=card2,
                       borderwidth=0,
                       font=self.f_sub)

        style.configure("TEntry", fieldbackground=card2, foreground=fg,
                       bordercolor=card2, padding=5)
        style.configure("TCheckbutton", background=bg, foreground=fg, font=self.f_sub)
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("TRadiobutton", background=bg, foreground=fg, font=self.f_sub)
        style.map("TRadiobutton", background=[("active", bg)])

        style.configure("Accent.Horizontal.TProgressbar",
                       troughcolor=card, background=accent,
                       bordercolor=card, lightcolor=accent, darkcolor=accent,
                       thickness=6)

        style.configure("Treeview", background=card, foreground=fg, fieldbackground=card,
                       borderwidth=0, font=self.f_sub, rowheight=32)
        style.configure("Treeview.Heading", background=card2, foreground=fg,
                       font=self.f_lbl, borderwidth=0, padding=[8, 6])
        style.map("Treeview", background=[("selected", accent)],
                 foreground=[("selected", "#FFFFFF")])
        if hasattr(self, "pdf_tree"):
            self.pdf_tree.tag_configure("folder", foreground=accent)
            self.pdf_tree.tag_configure("file", foreground=fg)
        if hasattr(self, "rev_tree"):
            self.rev_tree.tag_configure("ok", foreground=T["green"])
            self.rev_tree.tag_configure("probleme", foreground=T["red"])
        if hasattr(self, "glo_tree"):
            self.glo_tree.tag_configure("valide", foreground=T["green"])
            self.glo_tree.tag_configure("attente", foreground=muted)
        if hasattr(self, "epub_tree"):
            self.epub_tree.tag_configure("nouveau", foreground=accent)
            self.epub_tree.tag_configure("modifie", foreground=T["yellow"])
            self.epub_tree.tag_configure("connu", foreground=muted)
        if hasattr(self, "log"):
            self._configurer_tags_log()
        if hasattr(self, "hebdo_canvas"):
            self.hebdo_canvas.configure(bg=card)
            self._dessiner_hebdo()

        style.configure("Card.TFrame", background=card)
        style.configure("Card2.TFrame", background=card2)
        style.configure("Orange.TFrame", background=accent)
        style.configure("Success.TLabel", foreground=T["green"], font=self.f_lbl)
        style.configure("Warning.TLabel", foreground=T["yellow"], font=self.f_lbl)
        style.configure("Error.TLabel", foreground=T["red"], font=self.f_lbl)

        # ── Appliquer les couleurs du popdown à tous les Combobox existants ──
        self._recolor_all_combobox_popdowns()

    def _recolor_all_combobox_popdowns(self):
        """Recolorie le popdown (liste déroulante) de tous les ttk.Combobox existants.
        Le popdown est une fenêtre Tk native créée à la volée ; on y accède via
        winfo_children() du Combobox ou via l'attribut interne _popdown.
        """
        T = self._theme
        card2, fg, accent = T["card2"], T["fg"], T["accent"]
        for widget in self.root.winfo_children():
            self._recolor_combobox_popdown_recursive(widget, card2, fg, accent)

    def _recolor_combobox_popdown_recursive(self, widget, card2, fg, accent):
        """Parcourt récursivement les widgets et recolore les popdowns Combobox."""
        if isinstance(widget, ttk.Combobox):
            # Recolorer le popdown s'il existe déjà
            self._recolor_single_popdown(widget, card2, fg, accent)
            # Utiliser postcommand : Tk appelle cette fonction juste avant d'afficher
            # le dropdown, garantissant que les couleurs sont appliquées à chaque fois.
            # On utilise une méthode au lieu d'un lambda pour capturer le thème actuel.
            try:
                old_cmd = widget.cget("postcommand")
                if not old_cmd or old_cmd == "":
                    widget.configure(postcommand=lambda w=widget: self._recolor_single_popdown(w, self._theme["card2"], self._theme["fg"], self._theme["accent"]))
            except (tk.TclError, AttributeError):
                pass
        try:
            for child in widget.winfo_children():
                self._recolor_combobox_popdown_recursive(child, card2, fg, accent)
        except (tk.TclError, AttributeError):
            pass

    def _recolor_single_popdown(self, combobox, card2, fg, accent):
        """Recolore le popdown d'un Combobox spécifique."""
        try:
            for child in combobox.winfo_children():
                cls = child.winfo_class()
                # Le popdown peut être une fenêtre TkPopdown ou directement une Listbox
                if cls in ("TkPopdown", "Menu", "Listbox") or "Listbox" in cls:
                    try:
                        child.configure(bg=card2, fg=fg,
                                       selectbackground=accent,
                                       selectforeground="#FFFFFF",
                                       borderwidth=0,
                                       highlightthickness=0,
                                       relief="flat")
                    except (tk.TclError, AttributeError):
                        pass
                for sub in child.winfo_children():
                    if sub.winfo_class() in ("Listbox",) or "Listbox" in sub.winfo_class():
                        try:
                            sub.configure(bg=card2, fg=fg,
                                         selectbackground=accent,
                                         selectforeground="#FFFFFF",
                                         borderwidth=0,
                                         highlightthickness=0,
                                         relief="flat")
                        except (tk.TclError, AttributeError):
                            pass
        except (tk.TclError, AttributeError):
            pass

    # ── BOUTON ──
    def _btn(self, parent, text, cmd, bg=None, bg_hover=None, fg="#FFFFFF", width=None):
        T = self._theme
        bg = bg or T["accent"]
        bg_hover = bg_hover or T["accent_h"]
        b = tk.Button(parent, text=text, command=cmd, font=self.f_btn,
                      bg=bg, fg=fg, activebackground=bg_hover, activeforeground=fg,
                      relief="flat", bd=0, padx=22, pady=10, cursor="hand2",
                      highlightthickness=0, width=width)
        b.bind("<Enter>", lambda e, b=b, bg_hover=bg_hover: b.config(bg=bg_hover) if b["state"]=="normal" else None)
        b.bind("<Leave>", lambda e, b=b, bg=bg: b.config(bg=bg) if b["state"]=="normal" else None)
        b._bg, b._bg_hover = bg, bg_hover
        return b

    # ── CONSTRUCTION UI ──
    def _build_ui(self):
        T = self._theme
        p = {"padx": 20}

        # ── Barre d'en-tête ──
        header_outer = tk.Frame(self.root, bg=T["accent"], height=3)
        header_outer.pack(fill="x")
        header_outer.pack_propagate(False)

        header = tk.Frame(self.root, bg=T["card"], height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        h_inner = tk.Frame(header, bg=T["card"])
        h_inner.pack(fill="both", padx=20)

        tk.Label(h_inner, text="Traducteur PDF", font=self.f_title,
                bg=T["card"], fg=T["fg"]).pack(side="left", anchor="w")

        self.theme_sel_frame = tk.Frame(h_inner, bg=T["card"])
        self.theme_sel_frame.pack(side="right")
        tk.Label(self.theme_sel_frame, text="Thème", font=self.f_small,
                bg=T["card"], fg=T["muted"]).pack(side="left", padx=(0, 6))
        self.var_theme = tk.StringVar(value=self.current_theme_name)
        self.combo_theme = ttk.Combobox(self.theme_sel_frame, textvariable=self.var_theme,
                                        state="readonly", width=16, values=th.THEME_NAMES)
        self.combo_theme.pack(side="left")
        self.combo_theme.bind("<<ComboboxSelected>>", self._changer_theme)

        # ── Profils de configuration (Feature 5) ──
        profil_frame = tk.Frame(h_inner, bg=T["card"])
        profil_frame.pack(side="right", padx=(0, 16))
        tk.Label(profil_frame, text="Profil", font=self.f_small,
                bg=T["card"], fg=T["muted"]).pack(side="left", padx=(0, 4))
        self.var_profil = tk.StringVar()
        self.combo_profil = ttk.Combobox(profil_frame, textvariable=self.var_profil,
                                          state="readonly", width=14, values=[])
        self.combo_profil.pack(side="left")
        self.combo_profil.bind("<<ComboboxSelected>>", self._charger_profil_depuis_combo)
        self._btn(profil_frame, "+", self._sauvegarder_comme_profil,
                  T["card2"], T["accent_h"], T["fg"], width=2).pack(side="left", padx=(2, 0))
        self._btn(profil_frame, "\u2212", self._supprimer_profil_courant,
                  T["card2"], T["accent_h"], T["fg"], width=2).pack(side="left")
        self._rafraichir_liste_profils()

        # Boutons projet
        proj_frame = tk.Frame(h_inner, bg=T["card"])
        proj_frame.pack(side="right", padx=(0, 16))
        self.btn_save_proj = self._btn(proj_frame, "Sauvegarder", self._sauvegarder_projet,
                                       T["card2"], T["accent_h"], "#FFFFFF")
        self.btn_save_proj.pack(side="left", padx=(0, 4))
        self.btn_load_proj = self._btn(proj_frame, "Charger", self._charger_projet,
                                       T["card2"], T["accent_h"], "#FFFFFF")
        self.btn_load_proj.pack(side="left")

        # ── Notebook ──
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(16, 6))

        self._build_tab_traduction()
        self._build_tab_preview()
        self._build_tab_conversion()
        self._build_tab_export_epub()
        self._build_tab_revision()
        self._build_tab_glossaire()
        self._build_tab_dashboard()
        self._build_tab_history()
        self._build_tab_settings()
        self._setup_raccourcis()

    # ── ONGLET 1 : TRADUCTION ──
    def _build_tab_traduction(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Traduction")
        pad = {"padx": 20, "pady": 12}

        # Canvas défilable (même pattern que l'onglet Configuration)
        canvas = tk.Canvas(tab, bg=T["bg"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(tab, orient="vertical", command=canvas.yview, bg=T["card2"])
        scrollable = tk.Frame(canvas, bg=T["bg"])
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _configurer_largeur(e):
            canvas.itemconfigure(window_id, width=e.width)
        canvas.bind("<Configure>", _configurer_largeur)

        def _on_molette(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_molette)
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        scrollable.bind("<MouseWheel>", _on_molette)
        scrollable.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        scrollable.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        # Ligne dossiers
        dir_card = tk.Frame(scrollable, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        dir_card.pack(fill="x", **pad)
        d_inner = tk.Frame(dir_card, bg=T["card"])
        d_inner.pack(fill="x", padx=16, pady=14)
        d_inner.columnconfigure(1, weight=1)

        self.var_dossier = tk.StringVar(value=os.path.abspath("."))
        self._dir_row(d_inner, 0, "Dossier de travail", self.var_dossier)

        tk.Label(d_inner,
                text="Source : pdfs_originaux/  \u2192  Sortie : pdfs_traduits/",
                font=self.f_small, bg=T["card"], fg=T["muted"]).grid(
                row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # Sélection fichiers (gauche) + paramètres (droite)
        mid_frame = tk.Frame(scrollable, bg=T["bg"])
        mid_frame.pack(fill="both", expand=True, **pad)

        # Sélection fichiers
        sel_card = tk.Frame(mid_frame, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        sel_card.pack(side="left", fill="both", expand=True)

        sel_header = tk.Frame(sel_card, bg=T["card"])
        sel_header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(sel_header, text="Sélection des PDF", font=self.f_lbl,
                bg=T["card"], fg=T["fg"]).pack(side="left")
        self.lbl_pdf_count = tk.Label(sel_header, text="0 fichier(s)", font=self.f_sub,
                                      bg=T["card"], fg=T["muted"])
        self.lbl_pdf_count.pack(side="right")

        self.btn_frame = tk.Frame(sel_card, bg=T["card"])
        self.btn_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._btn(self.btn_frame, "Actualiser", self._refresh_pdf_list, T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 4))
        self._btn(self.btn_frame, "Tout", self._select_all, T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 4))
        self._btn(self.btn_frame, "Aucun", self._deselect_all, T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 4))
        self.btn_supprimer = self._btn(self.btn_frame, "Supprimer", self._supprimer_selection, T["red"], T["red_h"], "#FFFFFF")
        self.btn_supprimer.pack(side="left", padx=(0, 4))

        # Arbre dossiers/fichiers
        tree_container = tk.Frame(sel_card, bg=T["card"])
        tree_container.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        tree_toolbar = tk.Frame(tree_container, bg=T["card"])
        tree_toolbar.pack(fill="x", pady=(0, 6))
        self.var_tree_search = tk.StringVar()
        self.var_tree_search.trace_add("write", lambda *a: self._filter_tree())
        ttk.Entry(tree_toolbar, textvariable=self.var_tree_search, width=22).pack(side="left", padx=(0, 6))

        self.pdf_tree = ttk.Treeview(tree_container, show="tree", selectmode="none")
        tree_scrollbar = tk.Scrollbar(tree_container, orient="vertical", command=self.pdf_tree.yview,
                                      bg=T["card2"])
        self.pdf_tree.configure(yscrollcommand=tree_scrollbar.set)
        self.pdf_tree.pack(side="left", fill="both", expand=True)
        tree_scrollbar.pack(side="right", fill="y")

        self.pdf_tree.tag_configure("folder", font=self.f_lbl)
        self.pdf_tree.tag_configure("file", font=self.f_sub)
        self.pdf_tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # Paramètres (droite)
        params_card = tk.Frame(mid_frame, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        params_card.pack(side="right", fill="both", padx=(12, 0))
        p_inner = tk.Frame(params_card, bg=T["card"])
        p_inner.pack(fill="both", padx=16, pady=14, expand=True)

        # Variable pour le dossier source (utilisée par l'onglet Révision)
        self.var_input_dir = tk.StringVar(value=os.path.join(self.var_dossier.get(), "pdfs_originaux"))

        # Langues
        tk.Label(p_inner, text="Langues", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(anchor="w")
        lr = tk.Frame(p_inner, bg=T["card"])
        lr.pack(fill="x", pady=(6, 10))
        self.var_src_lang = tk.StringVar(value="Anglais")
        ttk.Combobox(lr, textvariable=self.var_src_lang, state="readonly",
                     width=12, values=[l for l, _ in LANGUES]).pack(side="left")
        tk.Label(lr, text="\u2192", font=self.f_btn, bg=T["card"], fg=T["accent"]).pack(side="left", padx=4)
        self.var_tgt_lang = tk.StringVar(value="Fran\u00e7ais")
        ttk.Combobox(lr, textvariable=self.var_tgt_lang, state="readonly",
                     width=12, values=[l for l, _ in LANGUES]).pack(side="left")

        tk.Frame(p_inner, bg=T["card2"], height=1).pack(fill="x", pady=8)

        # Moteur
        tk.Label(p_inner, text="Moteur", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(anchor="w")
        tf = tk.Frame(p_inner, bg=T["card"])
        tf.pack(fill="x", pady=6)
        tk.Label(tf, text="Threads :", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_threads = tk.IntVar(value=3)
        ttk.Spinbox(tf, from_=1, to=16, textvariable=self.var_threads, width=5).pack(side="left", padx=(4, 14))
        tk.Label(tf, text="Format :", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_format = tk.StringVar(value="pdf")
        ttk.Combobox(tf, textvariable=self.var_format, state="readonly",
                     width=7, values=[f for f, _ in FORMATS]).pack(side="left", padx=(4, 0))

        tk.Frame(p_inner, bg=T["card2"], height=1).pack(fill="x", pady=8)

        # Options
        tk.Label(p_inner, text="Options", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(anchor="w")
        self.var_ignorer = tk.BooleanVar(value=True)
        ttk.Checkbutton(p_inner, text="Ignorer déjà traduits", variable=self.var_ignorer).pack(anchor="w", pady=2)
        self.var_spell = tk.BooleanVar(value=False)
        ttk.Checkbutton(p_inner, text="Correction orthographique", variable=self.var_spell).pack(anchor="w", pady=2)
        self.var_merge = tk.BooleanVar(value=False)
        ttk.Checkbutton(p_inner, text="Fusionner les PDF", variable=self.var_merge).pack(anchor="w", pady=2)

        tk.Frame(p_inner, bg=T["card2"], height=1).pack(fill="x", pady=8)

        # Mode
        tk.Label(p_inner, text="Mode", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(anchor="w")
        self.var_mode = tk.StringVar(value="traduire")
        ttk.Radiobutton(p_inner, text="Extraire uniquement",
                        variable=self.var_mode, value="extraire").pack(anchor="w", pady=2)
        ttk.Radiobutton(p_inner, text="Traduire + générer (Google)",
                        variable=self.var_mode, value="traduire").pack(anchor="w", pady=2)
        ttk.Radiobutton(p_inner, text="Traduire hors ligne (Argos)",
                        variable=self.var_mode, value="traduire_offline").pack(anchor="w", pady=2)
        ttk.Radiobutton(p_inner, text="Traduire hors ligne (NLLB)",
                        variable=self.var_mode, value="traduire_nllb").pack(anchor="w", pady=2)

        # Statut Argos (hors ligne)
        self.lbl_argos_status = tk.Label(p_inner, text="", font=self.f_small,
                                         bg=T["card"], fg=T["muted"])
        self.lbl_argos_status.pack(anchor="w", padx=(16, 0), pady=(0, 2))
        self._actualiser_statut_offline()

        # Barre d'action
        action_bar = tk.Frame(scrollable, bg=T["bg"])
        action_bar.pack(fill="x", **pad)

        self.btn_start = self._btn(action_bar, "Démarrer", self._demarrer, T["green"], T["green_h"])
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = self._btn(action_bar, "Arrêter", self._arreter, T["red"], T["red_h"])
        self.btn_stop.pack(side="left")
        self._set_stop_enabled(False)

        # Progression
        prog_frame = tk.Frame(scrollable, bg=T["bg"])
        prog_frame.pack(fill="x", **pad)

        # Phase badge (Feature 6)
        self.lbl_phase = tk.Label(prog_frame, text="", font=self.f_small,
                                  bg=T["accent"], fg="#FFFFFF", padx=10, pady=3)
        self.lbl_phase.pack(side="left", padx=(0, 10))

        self.pb = ttk.Progressbar(prog_frame, style="Accent.Horizontal.TProgressbar",
                                  mode="determinate", maximum=100)
        self.pb.pack(fill="x", side="left", expand=True)
        self.lbl_pct = tk.Label(prog_frame, text="0%", font=self.f_lbl, bg=T["bg"], fg=T["accent"], width=5)
        self.lbl_pct.pack(side="left", padx=(10, 0))
        self.lbl_eta = tk.Label(prog_frame, text="", font=self.f_small,
                                bg=T["bg"], fg=T["muted"], anchor="e")
        self.lbl_eta.pack(side="left", padx=(6, 0))

        status_frame = tk.Frame(scrollable, bg=T["bg"])
        status_frame.pack(fill="x", padx=20)
        self.lbl_status = tk.Label(status_frame, text="Prêt", font=self.f_sub,
                                  bg=T["bg"], fg=T["muted"], anchor="w")
        self.lbl_status.pack(fill="x")

        # Journal avec recherche
        log_card = tk.Frame(scrollable, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        log_card.pack(fill="both", expand=True, **pad)

        log_header = tk.Frame(log_card, bg=T["card"])
        log_header.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(log_header, text="Journal", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(side="left")
        tk.Label(log_header, text="Filtrer :", font=self.f_small, bg=T["card"], fg=T["muted"]).pack(side="left", padx=(16, 4))
        self.var_log_search = tk.StringVar()
        self.var_log_search.trace_add("write", lambda *a: self._filter_log())
        ttk.Entry(log_header, textvariable=self.var_log_search, width=22).pack(side="left")

        tk.Label(log_header, text="Niveau :", font=self.f_small,
                 bg=T["card"], fg=T["muted"]).pack(side="left", padx=(14, 4))
        self.var_log_niveau = tk.StringVar(value="Tout")
        combo_niv = ttk.Combobox(log_header, textvariable=self.var_log_niveau,
                                 state="readonly", width=10,
                                 values=["Tout", "Succès", "Avertissement", "Erreur"])
        combo_niv.pack(side="left")
        combo_niv.bind("<<ComboboxSelected>>", lambda e: self._filter_log())

        self._btn(log_header, "Effacer", self._clear_log, T["card2"], T["accent_h"], T["fg"]).pack(side="right")
        self._btn(log_header, "Exporter", self._exporter_log,
                  T["card2"], T["accent_h"], T["fg"]).pack(side="right", padx=(0, 6))

        self.log = scrolledtext.ScrolledText(
            log_card, height=9, bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
            font=self.f_mono, relief="flat", bd=0, wrap="word",
            highlightthickness=1, highlightbackground=T["card2"])
        self.log.pack(fill="both", expand=True, padx=16, pady=(6, 14))
        self._configurer_tags_log()
        self.log.configure(state="disabled")

        self._refresh_pdf_list()

    # ── ONGLET 2 : APERÇU ──
    def _build_tab_preview(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Aperçu")

        top = tk.Frame(tab, bg=T["bg"])
        top.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(top, text="Fichier :", font=self.f_lbl, bg=T["bg"], fg=T["fg"]).pack(side="left")
        self.preview_file_var = tk.StringVar()
        self.preview_combo = ttk.Combobox(top, textvariable=self.preview_file_var,
                                          state="readonly", width=50)
        self.preview_combo.pack(side="left", padx=(8, 6))
        self.preview_combo.bind("<<ComboboxSelected>>", self._load_preview)
        self._btn(top, "Actualiser", self._refresh_preview_list, T["card2"], T["accent_h"], T["fg"]).pack(side="left")

        # Vue partagée
        panes = tk.Frame(tab, bg=T["bg"])
        panes.pack(fill="both", expand=True, padx=20, pady=(6, 20))

        for side_idx, (side, label_text) in enumerate([("left", "Texte original"), ("right", "Texte traduit (modifiable)")]):
            frame = tk.Frame(panes, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
            frame.pack(side=tk.LEFT if side=="left" else tk.RIGHT,
                      fill="both", expand=True,
                      padx=(0, 6) if side=="left" else (6, 0))
            tk.Label(frame, text=label_text, font=self.f_lbl,
                    bg=T["card"], fg=T["fg"]).pack(anchor="w", padx=12, pady=(10, 6))
            text_widget = scrolledtext.ScrolledText(
                frame, height=20, bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
                font=self.f_mono, relief="flat", bd=0, wrap="word",
                highlightthickness=1, highlightbackground=T["card2"])
            text_widget.pack(fill="both", expand=True, padx=12, pady=(0, 12))

            if side == "left":
                self.preview_orig = text_widget
            else:
                self.preview_trad = text_widget
                btn_frame = tk.Frame(frame, bg=T["card"])
                btn_frame.pack(fill="x", padx=10, pady=(0, 10))
                self._btn(btn_frame, "Sauvegarder", self._save_preview_edit,
                         T["accent"], T["accent_h"]).pack(side="left")
                tk.Label(btn_frame, text="Modifiez le texte et sauvegardez localement",
                        font=self.f_small, bg=T["card"], fg=T["muted"]).pack(side="left", padx=(10, 0))

    # ── ONGLET 3 bis : PDF TRADUITS → EPUB ──
    def _build_tab_export_epub(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Traduit → EPUB")

        self.epub_analyse = None
        self._epub_busy = False

        # Dossier source + sortie
        source_card = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1,
                               highlightbackground=T["card2"])
        source_card.pack(fill="x", padx=20, pady=(12, 8))
        inner = tk.Frame(source_card, bg=T["card"])
        inner.pack(fill="x", padx=16, pady=12)
        inner.columnconfigure(1, weight=1)

        self.epub_dossier_var = tk.StringVar(
            value=os.path.join(self.var_dossier.get(), "pdfs_traduits"))
        self.epub_force_var = tk.BooleanVar(value=False)
        self.epub_roman_var = tk.StringVar()
        self._epub_romans: dict[str, str] = {}

        tk.Label(inner, text="Roman", font=self.f_lbl,
                 bg=T["card"], fg=T["fg"]).grid(row=0, column=0, sticky="w", pady=4)
        self.epub_roman_combo = ttk.Combobox(
            inner, textvariable=self.epub_roman_var, state="readonly")
        self.epub_roman_combo.grid(row=0, column=1, sticky="ew",
                                   padx=(8, 6), pady=4)
        self.epub_roman_combo.bind("<<ComboboxSelected>>",
                                   self._epub_choisir_roman)
        self._btn(inner, "Actualiser", self._epub_rafraichir_romans,
                  T["card2"], T["accent_h"], T["fg"], width=9).grid(
                      row=0, column=2, pady=4)

        self._dir_row(inner, 1, "Dossier traduit", self.epub_dossier_var)
        tk.Label(inner, text="Sortie", font=self.f_lbl,
                 bg=T["card"], fg=T["fg"]).grid(row=2, column=0, sticky="w", pady=4)
        tk.Label(inner, text="epubs/<nom-du-roman>.epub (remplacé à chaque mise à jour)",
                 font=self.f_small, bg=T["card"], fg=T["muted"],
                 anchor="w").grid(row=2, column=1, columnspan=2, sticky="w",
                                  padx=(8, 0), pady=4)

        actions = tk.Frame(tab, bg=T["bg"])
        actions.pack(fill="x", padx=20, pady=(0, 8))
        self.epub_btn_scan = self._btn(actions, "Scanner", self._epub_scanner,
                                       T["accent"], T["accent_h"], width=12)
        self.epub_btn_scan.pack(side="left")
        self.epub_btn_creer = self._btn(actions, "Créer / Mettre à jour l'EPUB",
                                        self._epub_generer, T["green"], "#2ecc71", width=26)
        self.epub_btn_creer.pack(side="left", padx=(8, 12))
        ttk.Checkbutton(actions, text="Forcer la ré-analyse",
                        variable=self.epub_force_var).pack(side="left")
        self.epub_resume_lbl = tk.Label(actions, text="Aucun dossier scanné.",
                                        font=self.f_sub, bg=T["bg"], fg=T["muted"])
        self.epub_resume_lbl.pack(side="right")

        # Tableau des chapitres
        table_card = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1,
                              highlightbackground=T["card2"])
        table_card.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        tk.Label(table_card, text="Chapitres détectés", font=self.f_lbl,
                 bg=T["card"], fg=T["accent"]).pack(anchor="w", padx=16, pady=(10, 4))

        colonnes = ("num", "titre", "source", "statut")
        self.epub_tree = ttk.Treeview(table_card, columns=colonnes, show="headings",
                                      selectmode="browse")
        for col, titre, largeur in (
            ("num", "N°", 90), ("titre", "Titre", 430),
            ("source", "Fichier source", 250), ("statut", "Statut", 90),
        ):
            self.epub_tree.heading(col, text=titre)
            self.epub_tree.column(col, width=largeur, anchor="w",
                                  stretch=(col == "titre"))
        scroll = tk.Scrollbar(table_card, orient="vertical",
                              command=self.epub_tree.yview, bg=T["card2"])
        self.epub_tree.configure(yscrollcommand=scroll.set)
        self.epub_tree.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=(0, 12))
        scroll.pack(side="right", fill="y", pady=(0, 12), padx=(0, 8))

        # Log
        self.epub_log = scrolledtext.ScrolledText(
            tab, font=self.f_mono, bg=T["card2"], fg=T["fg"],
            relief="flat", bd=0, height=7, wrap="word",
        )
        self.epub_log.pack(fill="x", padx=20, pady=(0, 12))
        self.epub_log.config(state="disabled")

        self.epub_dossier_var.trace_add("write", lambda *a: self._epub_invalider())
        self.var_dossier.trace_add("write", lambda *a: self._epub_rafraichir_romans())
        self._epub_rafraichir_romans()

    def _epub_compter_pdfs(self, dossier: str) -> int:
        total = 0
        for racine, sous_dossiers, fichiers in os.walk(dossier):
            sous_dossiers[:] = [d for d in sous_dossiers if not d.startswith(".")]
            total += sum(1 for f in fichiers if f.lower().endswith(".pdf"))
        return total

    def _epub_rafraichir_romans(self):
        if not hasattr(self, "epub_roman_combo"):
            return
        base = os.path.join(self.var_dossier.get(), "pdfs_traduits")
        self._epub_romans = {}
        libelles = []
        if os.path.isdir(base):
            try:
                with os.scandir(base) as scan:
                    entrees = sorted(scan, key=lambda e: e.name.lower())
            except OSError:
                entrees = []
            for entree in entrees:
                if not entree.is_dir() or entree.name.startswith("."):
                    continue
                try:
                    nombre = self._epub_compter_pdfs(entree.path)
                except OSError:
                    continue
                if nombre:
                    libelle = f"{entree.name} ({nombre} PDF)"
                    self._epub_romans[libelle] = entree.path
                    libelles.append(libelle)
        self.epub_roman_combo.configure(values=libelles)

        courant = os.path.abspath(self.epub_dossier_var.get().strip() or ".")
        for libelle, chemin in self._epub_romans.items():
            if os.path.abspath(chemin) == courant:
                self.epub_roman_var.set(libelle)
                break
        else:
            self.epub_roman_var.set("")
        if not os.path.isdir(self.epub_dossier_var.get().strip()):
            self.epub_dossier_var.set(base)

    def _epub_choisir_roman(self, _event=None):
        chemin = self._epub_romans.get(self.epub_roman_var.get())
        if chemin:
            self.epub_dossier_var.set(chemin)

    def _epub_invalider(self):
        if getattr(self, "_epub_busy", False):
            return
        self.epub_analyse = None
        for item in self.epub_tree.get_children():
            self.epub_tree.delete(item)
        self.epub_resume_lbl.config(text="Dossier modifié — lancez un scan.")

    def _epub_log_msg(self, msg: str):
        if msg.startswith("[") and ("Extraction" in msg or "Déjà indexé" in msg):
            self.epub_resume_lbl.config(text=msg)
        self.epub_log.config(state="normal")
        self.epub_log.insert("end", msg + "\n")
        self.epub_log.see("end")
        self.epub_log.config(state="disabled")

    def _epub_scanner(self):
        if self._epub_busy:
            return
        dossier = self.epub_dossier_var.get().strip()
        if not os.path.isdir(dossier):
            messagebox.showwarning("Dossier introuvable",
                                   "Choisissez un dossier contenant des PDF traduits.")
            return
        # Évite de lancer l'analyse de tous les romans à la fois : sans PDF
        # directement dans le dossier, plusieurs sous-dossiers = plusieurs
        # romans, qu'il faut traiter séparément.
        if not glob.glob(os.path.join(dossier, "*.pdf")):
            try:
                with os.scandir(dossier) as scan:
                    romans = [
                        d for d in scan
                        if d.is_dir() and not d.name.startswith(".")
                        and self._epub_compter_pdfs(d.path)
                    ]
            except OSError:
                romans = []
            if len(romans) > 1:
                continuer = messagebox.askyesno(
                    "Plusieurs romans détectés",
                    "Ce dossier contient plusieurs romans.\n\n"
                    "Il vaut mieux en sélectionner un dans la liste « Roman ».\n"
                    "Continuer quand même et tout fusionner dans un seul EPUB ?",
                    icon="warning", default=messagebox.NO)
                if not continuer:
                    return
            if not romans and self._epub_compter_pdfs(dossier) == 0:
                messagebox.showwarning(
                    "Aucun PDF",
                    "Aucun PDF traduit n'a été trouvé dans ce dossier.")
                return
        self._epub_busy = True
        self.epub_btn_scan.config(state="disabled")
        self.epub_btn_creer.config(state="disabled")
        for item in self.epub_tree.get_children():
            self.epub_tree.delete(item)
        self.epub_resume_lbl.config(text="Analyse en cours…")
        self._epub_log_msg(f"Scan de {dossier}…")
        force = self.epub_force_var.get()

        def journal(msg):
            self.queue.put(("elog", msg))

        def travail():
            try:
                from moteur import export_epub as ee
                analyse = ee.analyser_dossier(
                    dossier, force=force, on_log=journal)
            except Exception as exc:
                self.queue.put(("eerr", exc))
            else:
                self.queue.put(("edone", analyse))

        threading.Thread(target=travail, daemon=True).start()

    def _epub_afficher(self, analyse):
        self._epub_busy = False
        self.epub_btn_scan.config(state="normal")
        self.epub_btn_creer.config(state="normal")
        self.epub_analyse = analyse
        self.epub_resume_lbl.config(text=analyse.resume())
        libelles = {"nouveau": "nouveau", "modifie": "modifié",
                    "connu": "déjà indexé"}
        limite = 2000
        for chapitre in analyse.chapitres[:limite]:
            tag = chapitre.statut if chapitre.statut in libelles else "connu"
            self.epub_tree.insert("", "end", values=(
                chapitre.numero_affichage, chapitre.titre,
                os.path.basename(chapitre.source),
                libelles.get(chapitre.statut, chapitre.statut),
            ), tags=(tag,))
        if len(analyse.chapitres) > limite:
            self._epub_log_msg(
                f"Affichage limité aux {limite} premiers chapitres ; "
                f"l'EPUB contiendra les {len(analyse.chapitres)}.")
        self._epub_log_msg(analyse.resume())
        if not analyse.chapitres:
            self._epub_log_msg(
                "Aucun chapitre détecté : vérifiez que les PDF contiennent des "
                "entêtes « Chapitre N » ou utilisez un dossier par roman.")

    def _epub_echec(self, exc):
        self._epub_busy = False
        self.epub_btn_scan.config(state="normal")
        self.epub_btn_creer.config(state="normal")
        self.epub_resume_lbl.config(text="Échec de l'opération.")
        self._epub_log_msg(f"Erreur : {exc}")
        messagebox.showerror("Opération impossible", str(exc))

    def _epub_generer(self):
        if self._epub_busy:
            return
        if self.epub_analyse is None:
            messagebox.showinfo("Scanner d'abord",
                                "Lancez un scan du dossier traduit avant de créer l'EPUB.")
            return
        analyse = self.epub_analyse
        self._epub_busy = True
        self.epub_btn_scan.config(state="disabled")
        self.epub_btn_creer.config(state="disabled")
        self._epub_log_msg("Création de l'EPUB…")

        def journal(msg):
            self.queue.put(("elog", msg))

        def travail():
            try:
                from moteur import export_epub as ee
                chemin = ee.generer_epub(analyse, on_log=journal)
            except Exception as exc:
                self.queue.put(("eerr", exc))
            else:
                self.queue.put(("efile", chemin))

        threading.Thread(target=travail, daemon=True).start()

    def _epub_termine(self, chemin):
        self._epub_busy = False
        self.epub_btn_scan.config(state="normal")
        self.epub_btn_creer.config(state="normal")
        if self.epub_analyse:
            self.epub_analyse.chemin_epub = chemin
            self.epub_analyse.epub_existant = chemin
            self.epub_analyse.sources_nouvelles = 0
            self.epub_analyse.sources_modifiees = 0
            self.epub_analyse.sources_connues = len(self.epub_analyse.pdfs)
            for chapitre in self.epub_analyse.chapitres:
                chapitre.statut = "connu"
            for item in self.epub_tree.get_children():
                self.epub_tree.set(item, "statut", "déjà indexé")
                self.epub_tree.item(item, tags=("connu",))
            self.epub_resume_lbl.config(text=self.epub_analyse.resume())
        taille = os.path.getsize(chemin) / 1024 if os.path.exists(chemin) else 0
        self._epub_log_msg(f"EPUB créé : {chemin} ({taille:.0f} Ko)")
        self._notifier("EPUB créé", os.path.basename(chemin))

    # ── ONGLET 3 : CONVERSION EPUB → PDF ──
    def _build_tab_conversion(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Conversion EPUB")

        self.conv_vars = {
            "methode": tk.StringVar(value="script"),
            "mode_split": tk.BooleanVar(value=True),
            "pages_par_partie": tk.StringVar(value="299"),
        }

        # Barre d'outils
        toolbar = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        toolbar.pack(fill="x", padx=20, pady=12)

        self._btn(toolbar, "Scanner EPUBs", self._conv_scanner, T["accent"], T["accent_h"], width=16)\
            .pack(side="left", padx=(16, 6), pady=12)
        self._btn(toolbar, "Tout cocher", self._conv_tout_cocher, T["card2"], T["accent_h"], T["fg"], width=14)\
            .pack(side="left", padx=4, pady=12)
        self._btn(toolbar, "Tout décocher", self._conv_tout_decocher, T["card2"], T["accent_h"], T["fg"], width=14)\
            .pack(side="left", padx=4, pady=12)

        # Options
        opt_frame = tk.Frame(toolbar, bg=T["card"])
        opt_frame.pack(side="right", padx=16, pady=12)

        tk.Label(opt_frame, text="Méthode", font=self.f_small, bg=T["card"], fg=T["muted"])\
            .pack(side="left", padx=(0, 4))
        self.conv_vars["methode_cb"] = ttk.Combobox(opt_frame, textvariable=self.conv_vars["methode"],
                                                     state="readonly", width=10,
                                                     values=["script", "calibre"])
        self.conv_vars["methode_cb"].pack(side="left", padx=(0, 14))

        tk.Label(opt_frame, text="Split", font=self.f_small, bg=T["card"], fg=T["muted"])\
            .pack(side="left", padx=(0, 4))
        ttk.Checkbutton(opt_frame, variable=self.conv_vars["mode_split"])\
            .pack(side="left", padx=(0, 14))

        tk.Label(opt_frame, text="Pages max/PDF", font=self.f_small, bg=T["card"], fg=T["muted"])\
            .pack(side="left", padx=(0, 4))
        self.conv_pages_spin = ttk.Spinbox(
            opt_frame, from_=20, to=299, increment=10,
            textvariable=self.conv_vars["pages_par_partie"], width=6)
        self.conv_pages_spin.pack(side="left")

        self._btn(opt_frame, "Convertir", self._conv_lancer, T["green"], "#2ecc71", width=14)\
            .pack(side="left", padx=(14, 0))

        # Liste des EPUBs
        tk.Label(
            tab,
            text="Découpage optimal : chaque PDF reste sous la limite Google "
                 "(299 pages) et le nombre de fichiers est réduit au minimum.",
            font=self.f_small, bg=T["bg"], fg=T["muted"],
        ).pack(anchor="w", padx=22, pady=(0, 6))

        list_frame = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        tk.Label(list_frame, text="EPUBs trouvés", font=self.f_lbl, bg=T["card"], fg=T["accent"])\
            .pack(anchor="w", padx=16, pady=(10, 4))

        header = tk.Frame(list_frame, bg=T["card2"])
        header.pack(fill="x", padx=16)
        tk.Frame(header, bg=T["card2"], width=26).pack(side="left")
        tk.Label(header, text="Fichier", font=self.f_small, bg=T["card2"], fg=T["muted"], anchor="w")\
            .pack(side="left")
        tk.Frame(header, bg=T["card2"]).pack(side="left", fill="x", expand=True)
        tk.Label(header, text="Pages", font=self.f_small, bg=T["card2"], fg=T["muted"], width=8, anchor="center")\
            .pack(side="left")
        tk.Label(header, text="Parties", font=self.f_small, bg=T["card2"], fg=T["muted"], width=8, anchor="center")\
            .pack(side="left")

        self.conv_listbox = tk.Frame(list_frame, bg=T["card"])
        self.conv_listbox.pack(fill="both", expand=True, padx=16, pady=(6, 10))
        self.conv_epubs: list[dict] = []

        # Log
        self.conv_log = scrolledtext.ScrolledText(
            tab, font=self.f_mono, bg=T["card2"], fg=T["fg"],
            relief="flat", bd=0, height=8, wrap="word",
        )
        self.conv_log.pack(fill="x", padx=20, pady=(0, 12))
        self.conv_log.config(state="disabled")

    def _conv_log_msg(self, msg: str):
        self.conv_log.config(state="normal")
        self.conv_log.insert("end", msg + "\n")
        self.conv_log.see("end")
        self.conv_log.config(state="disabled")
        self.root.update_idletasks()

    def _conv_scanner(self):
        self._conv_log_msg(
            "Scan des EPUBs... (les romans déjà traduits sont masqués)")
        base = os.path.dirname(os.path.abspath(__file__))
        epubs = []
        # Limiter la profondeur pour éviter les boucles infinies via symlinks
        base_depth = base.count(os.sep)
        for root_dir, dirs, files in os.walk(base):
            # Exclure les dossiers courants et limiter la profondeur
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "epub", "epubs", "venv", ".venv", "env", "build", "dist", "node_modules", ".pytest_cache", "__pypackages__")]
            # Limiter la profondeur de parcours (max 5 niveaux sous base)
            if root_dir.count(os.sep) - base_depth > 5:
                dirs.clear()
            for f in files:
                if f.lower().endswith(".epub"):
                    epubs.append(os.path.join(root_dir, f))

        epubs.sort(key=lambda p: os.path.basename(p).lower())
        total_epubs = len(epubs)
        # Filtrage automatique : ne garder que les EPUBs pas encore convertis en PDF
        mode_split = self.conv_vars["mode_split"].get()
        pages_cible = self._conv_pages_cible()
        pdfs_originaux_root = os.path.join(
            self.var_dossier.get(), "pdfs_originaux"
        )
        epubs_non_convertis = []
        for ep in epubs:
            nom_base = os.path.splitext(os.path.basename(ep))[0]
            dossier_sortie = os.path.join(pdfs_originaux_root, nom_base)
            deja_converti = self._conv_a_des_traductions(nom_base)
            if not deja_converti and os.path.isdir(dossier_sortie):
                if mode_split:
                    parts = sorted(glob.glob(
                        os.path.join(dossier_sortie, f"{nom_base}_part*.pdf")))
                    marqueur = self._conv_lire_marqueur(dossier_sortie)
                    if (parts and marqueur
                            and marqueur.get("pages_max") == pages_cible
                            and marqueur.get("parts") == len(parts)):
                        try:
                            if (os.path.getmtime(os.path.join(
                                    dossier_sortie, ".conversion.json"))
                                    >= os.path.getmtime(ep)):
                                deja_converti = True
                        except OSError:
                            pass
                else:
                    unique = os.path.join(dossier_sortie, f"{nom_base}.pdf")
                    if os.path.exists(unique):
                        deja_converti = True
            if not deja_converti:
                epubs_non_convertis.append(ep)
        epubs = epubs_non_convertis
        self.conv_epubs.clear()
        for widget in self.conv_listbox.winfo_children():
            widget.destroy()

        for ep in epubs:
            nom = os.path.basename(ep)
            nom_base = os.path.splitext(nom)[0]
            dossier_sortie = os.path.join(pdfs_originaux_root, nom_base)
            parts = sorted(glob.glob(
                os.path.join(dossier_sortie, f"{nom_base}_part*.pdf")))
            marqueur = self._conv_lire_marqueur(dossier_sortie)
            pages = int(marqueur.get("pages_total", 0) or 0)
            info = {
                "path": ep,
                "selected": tk.BooleanVar(value=True),
                "pages": pages,
                "parts": len(parts),
            }
            row = tk.Frame(self.conv_listbox, bg=self._theme["card"])
            row.pack(fill="x")

            ttk.Checkbutton(row, variable=info["selected"]).pack(side="left")
            lbl = tk.Label(row, text=nom, font=self.f_sub, bg=self._theme["card"],
                           fg=self._theme["fg"], anchor="w")
            lbl.pack(side="left", fill="x", expand=True, padx=(4, 0))
            tk.Label(row, text=str(pages) if pages else "—",
                     font=self.f_small, bg=self._theme["card"],
                     fg=self._theme["muted"], width=8, anchor="center").pack(side="left")
            tk.Label(row, text=str(len(parts)) if parts else "—",
                     font=self.f_small, bg=self._theme["card"],
                     fg=self._theme["muted"], width=8, anchor="center").pack(side="left")

            self.conv_epubs.append(info)

        if total_epubs:
            self._conv_log_msg(
                f"{len(epubs)}/{total_epubs} EPUB(s) à convertir ou à optimiser"
            )
        else:
            self._conv_log_msg("0 EPUB trouvé")

    def _conv_tout_cocher(self):
        for e in self.conv_epubs:
            e["selected"].set(True)

    def _conv_tout_decocher(self):
        for e in self.conv_epubs:
            e["selected"].set(False)

    def _conv_pages_cible(self) -> int:
        try:
            pages = int(self.conv_vars["pages_par_partie"].get())
        except (TypeError, ValueError):
            pages = 299
        return max(20, min(pages, 299))

    def _conv_a_des_traductions(self, nom_base: str) -> bool:
        dossier = os.path.join(
            self.var_dossier.get(), "pdfs_traduits", nom_base)
        try:
            return any(
                n.lower().endswith(".pdf") for n in os.listdir(dossier)
            )
        except OSError:
            return False

    def _conv_lire_marqueur(self, dossier: str) -> dict:
        try:
            with open(os.path.join(dossier, ".conversion.json"), "r",
                      encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _conv_lancer(self):
        selection = [e for e in self.conv_epubs if e["selected"].get()]
        if not selection:
            self._conv_log_msg("Aucun EPUB sélectionné")
            return

        methode = self.conv_vars["methode"].get()
        mode_split = self.conv_vars["mode_split"].get()
        pages_par_partie = self._conv_pages_cible()
        if mode_split:
            self._conv_log_msg(
                f"Découpage : {pages_par_partie} pages maximum par PDF "
                f"(limite Google : 300)"
            )
        else:
            self._conv_log_msg("Conversion en un seul PDF (sans découpage)")

        def travail():
            for idx, info in enumerate(selection, 1):
                ep = info["path"]
                nom_base = os.path.splitext(os.path.basename(ep))[0]
                sortie = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "pdfs_originaux", nom_base,
                )
                self.root.after(0, lambda m=f"[{idx}/{len(selection)}] {nom_base}": self._conv_log_msg(f" {m}"))
                try:
                    pdfs = convertir_epub(
                        ep, sortie, methode=methode,
                        mode_split=mode_split,
                        pages_par_partie=pages_par_partie,
                        on_log=lambda m, idx=idx, total=len(selection): self.root.after(
                            0, lambda m=m: self._conv_log_msg(f"  {m}")
                        ),
                    )
                    self.root.after(0, lambda n=nom_base, p=len(pdfs): self._conv_log_msg(
                        f"{n} : {p} PDF(s)"
                    ))
                except Exception as exc:
                    self.root.after(0, lambda e=exc, n=nom_base: self._conv_log_msg(
                        f"{n} : {e}"
                    ))
            self.root.after(0, lambda: self._conv_log_msg("Conversion terminee"))
            self.root.after(200, self._conv_scanner)

        t = threading.Thread(target=travail, daemon=True)
        t.start()

    # ── ONGLET 4 : RÉVISION ──
    def _build_tab_revision(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Révision")

        # Variables
        dossier_defaut = os.path.join(self.var_dossier.get(), "pdfs_traduits")
        self.rev_dossier = tk.StringVar(value=dossier_defaut if os.path.isdir(dossier_defaut) else self.var_dossier.get())
        self.rev_resultats: list[dict] = []
        self.rev_selection: dict[str, bool] = {}

        # ── Barre d'outils ──
        toolbar = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        toolbar.pack(fill="x", padx=20, pady=12)

        tk.Label(toolbar, text="Dossier de sortie :", bg=T["card"], fg=T["fg"],
                 font=self.f_sub).pack(side="left", padx=(16, 6))
        ent = tk.Entry(toolbar, textvariable=self.rev_dossier, bg=T["input"], fg=T["fg"],
                       insertbackground=T["fg"], relief="flat", font=self.f_sub, width=50)
        ent.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._btn(toolbar, "\u22ef", self._rev_parcourir,
                  T["card2"], T["accent_h"], T["fg"], width=3).pack(side="left", padx=(0, 6))
        self._btn(toolbar, "Analyser", self._rev_analyser,
                  T["green"], T["green_h"]).pack(side="left", padx=(0, 16))

        # ── Panneau principal : liste + actions ──
        main_frame = tk.Frame(tab, bg=T["bg"])
        main_frame.pack(fill="both", expand=True, padx=20)

        # -- Liste des fichiers --
        left_frame = tk.Frame(main_frame, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(left_frame, text="Fichiers traduits", bg=T["card"], fg=T["fg"],
                 font=self.f_lbl).pack(anchor="w", padx=16, pady=(12, 6))

        cols = ("statut", "fichier", "pages")
        self.rev_tree = ttk.Treeview(left_frame, columns=cols, show="headings",
                                     height=12, selectmode="extended")
        self.rev_tree.heading("statut", text="État")
        self.rev_tree.heading("fichier", text="Fichier")
        self.rev_tree.heading("pages", text="Pages")
        self.rev_tree.column("statut", width=100, anchor="center")
        self.rev_tree.column("fichier", width=300)
        self.rev_tree.column("pages", width=80, anchor="center")
        self.rev_tree.tag_configure("ok", foreground=T["green"])
        self.rev_tree.tag_configure("probleme", foreground=T["red"])

        vsb = ttk.Scrollbar(left_frame, orient="vertical", command=self.rev_tree.yview)
        self.rev_tree.configure(yscrollcommand=vsb.set)
        self.rev_tree.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=(0, 12))
        vsb.pack(side="right", fill="y", pady=(0, 12), padx=(0, 16))

        self.rev_tree.bind("<<TreeviewSelect>>", lambda e: self._rev_afficher_detail())

        # -- Actions --
        right_frame = tk.Frame(main_frame, bg=T["card"], width=280, bd=0, highlightthickness=1, highlightbackground=T["card2"])
        right_frame.pack(side="right", fill="y", padx=(8, 0))
        right_frame.pack_propagate(False)

        tk.Label(right_frame, text="Actions", bg=T["card"], fg=T["fg"],
                 font=self.f_lbl).pack(anchor="w", padx=16, pady=(12, 8))

        tk.Label(right_frame,
                 text="Sans sélection, l'action porte sur\ntous les fichiers en échec.",
                 bg=T["card"], fg=T["muted"], font=self.f_small,
                 justify="left").pack(anchor="w", padx=16, pady=(0, 12))

        actions = [
            ("Retraduire (en ligne)", self._rev_retraduire_online, T["blue"], T["accent_h"]),
            ("Retraduire (hors ligne)", self._rev_retraduire_offline, T["orange"], T["accent_h"]),
            ("Marquer comme vérifié", self._rev_marquer_verifie, T["green"], T["green_h"]),
            ("Supprimer la sélection", self._rev_supprimer, T["red"], T["red_h"]),
        ]
        for texte, cmd, couleur, survol in actions:
            self._btn(right_frame, texte, cmd, couleur, survol).pack(fill="x", padx=16, pady=3)

        # ── Détail du fichier sélectionné ──
        detail_frame = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        detail_frame.pack(fill="both", expand=True, padx=20, pady=(12, 12))

        tk.Label(detail_frame, text="Aperçu du texte", bg=T["card"], fg=T["fg"],
                 font=self.f_lbl).pack(anchor="w", padx=16, pady=(10, 4))

        txt_frame = tk.Frame(detail_frame, bg=T["card"])
        txt_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.rev_texte = tk.Text(txt_frame, bg=T["log_bg"], fg=T["fg"],
                                 insertbackground=T["fg"], relief="flat",
                                 font=("JetBrains Mono", 9), wrap="word", state="disabled")
        self.rev_texte.pack(side="left", fill="both", expand=True)

        vsb2 = ttk.Scrollbar(txt_frame, orient="vertical", command=self.rev_texte.yview)
        self.rev_texte.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")

        # ── Barre de statut ──
        self.rev_status = tk.Label(tab, text="", bg=T["bg"], fg=T["muted"],
                                   font=self.f_small, anchor="w")
        self.rev_status.pack(fill="x", padx=20, pady=(0, 8))

    # ── Méthodes de l'onglet Révision ──

    def _rev_parcourir(self):
        dossier = filedialog.askdirectory(title="Dossier de sortie")
        if dossier:
            self.rev_dossier.set(dossier)

    def _rev_analyser(self):
        """Lance l'analyse du dossier de sortie dans un thread dédié.

        Ouvrir plusieurs centaines de PDF bloque l'interface : le travail
        est déporté et les résultats remontent par lots via la file Tk.
        """
        if getattr(self, "_rev_worker", None) and self._rev_worker.is_alive():
            return

        dossier = self.rev_dossier.get()
        if not dossier or not os.path.isdir(dossier):
            self.rev_status.config(text="Dossier invalide")
            return

        for item in self.rev_tree.get_children():
            self.rev_tree.delete(item)
        self.rev_resultats.clear()
        self.rev_selection.clear()
        self.rev_texte.configure(state="normal")
        self.rev_texte.delete("1.0", "end")
        self.rev_texte.configure(state="disabled")
        self.rev_status.config(text="Analyse en cours...")

        self._rev_annuler = False
        self._rev_queue = queue.Queue()
        self._rev_worker = threading.Thread(
            target=self._rev_analyser_travail, args=(dossier,), daemon=True)
        self._rev_worker.start()
        self.root.after(120, self._rev_pomper)

    def _rev_analyser_travail(self, dossier: str):
        """Thread : parcourt le dossier et évalue chaque fichier produit."""
        from moteur.revision import (extraire_nom_base_de_sortie,
                                     extraire_texte_sortie, texte_est_francais)

        fichiers: list[tuple[str, str, str]] = []
        for dirpath, _dirnames, filenames in os.walk(dossier):
            if ".edits" in dirpath.split(os.sep):
                continue
            for f in filenames:
                chemin = os.path.join(dirpath, f)
                chemin_rel = os.path.relpath(chemin, dossier)
                nom_base = extraire_nom_base_de_sortie(chemin_rel)
                if nom_base is not None:
                    fichiers.append((nom_base, chemin, chemin_rel))

        total = len(fichiers)
        self._rev_queue.put(("total", total))
        if not total:
            self._rev_queue.put(("fin", None))
            return

        for i, (nom_base, chemin, chemin_rel) in enumerate(fichiers, 1):
            if self._rev_annuler:
                break
            try:
                texte = extraire_texte_sortie(chemin, max_caracteres=5000)
            except Exception:
                texte = ""
            if not texte.strip():
                statut, est_fr = "illisible", False
            elif texte_est_francais(texte):
                statut, est_fr = "OK", True
            else:
                statut, est_fr = "non traduit", False

            self._rev_queue.put(("item", {
                "nom_base": nom_base,
                "chemin": chemin,
                "chemin_rel": chemin_rel,
                "statut": statut,
                "est_fr": est_fr,
                "texte": texte[:3000],
                "nb_pages": "?",
            }))
            if i % 25 == 0:
                self._rev_queue.put(("progres", (i, total)))
        self._rev_queue.put(("fin", None))

    def _rev_pomper(self):
        """Vide la file de résultats de l'analyse et met à jour la table."""
        fini = False
        try:
            while True:
                genre, charge = self._rev_queue.get_nowait()
                if genre == "total":
                    self._rev_total = charge
                elif genre == "item":
                    self.rev_resultats.append(charge)
                    self.rev_selection[charge["nom_base"]] = False
                    if not self.rev_tree.exists(charge["nom_base"]):
                        self.rev_tree.insert(
                            "", "end", iid=charge["nom_base"],
                            values=(charge["statut"], charge["chemin_rel"],
                                    charge["nb_pages"]),
                            tags=("ok" if charge["est_fr"] else "probleme",),
                        )
                elif genre == "progres":
                    i, total = charge
                    self.rev_status.config(text=f"Analyse : {i}/{total} fichier(s)...")
                elif genre == "fin":
                    fini = True
        except queue.Empty:
            pass

        if fini:
            nb_ok = sum(1 for r in self.rev_resultats if r["est_fr"])
            nb_pb = len(self.rev_resultats) - nb_ok
            if not self.rev_resultats:
                self.rev_status.config(text="Aucun fichier traduit trouvé")
            else:
                self.rev_status.config(
                    text=f"{nb_ok} correct(s)  |  {nb_pb} à retraduire  |  "
                         f"{len(self.rev_resultats)} fichier(s) au total"
                )
            return
        self.root.after(120, self._rev_pomper)

    def _rev_afficher_detail(self):
        T = self._theme
        sel = self.rev_tree.selection()
        if not sel:
            return
        nom_base = sel[0]
        resultat = next((r for r in self.rev_resultats if r["nom_base"] == nom_base), None)
        if not resultat:
            return

        # Le nombre de pages est calculé à la demande : ouvrir chaque PDF
        # lors de l'analyse coûterait plusieurs minutes sur un gros corpus.
        if resultat["nb_pages"] == "?" and resultat["chemin"].lower().endswith(".pdf"):
            try:
                import pdfplumber
                with pdfplumber.open(resultat["chemin"]) as pdf:
                    resultat["nb_pages"] = str(len(pdf.pages))
            except Exception:
                resultat["nb_pages"] = "n/a"
            if self.rev_tree.exists(nom_base):
                self.rev_tree.set(nom_base, "pages", resultat["nb_pages"])

        self.rev_texte.configure(state="normal")
        self.rev_texte.delete("1.0", "end")

        texte = resultat["texte"]
        if not texte.strip():
            self.rev_texte.insert("end", "(Impossible d'extraire le texte)")
        else:
            # Afficher avec indication des parties non françaises
            from moteur.revision import texte_est_francais
            lignes = texte.split("\n")
            for ligne in lignes:
                if ligne.strip() and not texte_est_francais(ligne):
                    self.rev_texte.insert("end", ligne + "\n", "anglais")
                else:
                    self.rev_texte.insert("end", ligne + "\n")

        self.rev_texte.tag_configure("anglais", foreground=T.get("red", "#E06C75"),
                                     font=("Courier", 9, "bold"))
        self.rev_texte.configure(state="disabled")

    def _rev_marquer_verifie(self):
        sel = self.rev_tree.selection()
        if not sel:
            self.rev_status.config(text="Sélectionnez un fichier")
            return
        dossier = self.rev_dossier.get()
        from moteur.revision import marquer_verifie
        T = self._theme
        for nom_base in sel:
            marquer_verifie(nom_base, dossier)
            if self.rev_tree.exists(nom_base):
                self.rev_tree.item(
                    nom_base,
                    values=("vérifié", self._get_chemin_rel(nom_base),
                            self._get_nb_pages(nom_base)),
                    tags=("ok",),
                )
        self.rev_status.config(text=f"{len(sel)} fichier(s) marqué(s) comme vérifié")

    def _get_chemin_rel(self, nom_base):
        r = next((x for x in self.rev_resultats if x["nom_base"] == nom_base), None)
        return r["chemin_rel"] if r else nom_base

    def _get_nb_pages(self, nom_base):
        r = next((x for x in self.rev_resultats if x["nom_base"] == nom_base), None)
        return r["nb_pages"] if r else "?"

    def _rev_supprimer(self):
        sel = self.rev_tree.selection()
        if not sel:
            self.rev_status.config(text="Sélectionnez un fichier")
            return
        if not messagebox.askyesno("Confirmer", f"Supprimer {len(sel)} fichier(s) ?"):
            return
        for nom_base in sel:
            r = next((x for x in self.rev_resultats if x["nom_base"] == nom_base), None)
            if r and os.path.exists(r["chemin"]):
                try:
                    os.remove(r["chemin"])
                    self.rev_tree.delete(nom_base)
                    self.rev_resultats = [x for x in self.rev_resultats if x["nom_base"] != nom_base]
                except OSError as e:
                    self.rev_status.config(text=f"Erreur : {e}")
        self.rev_status.config(text=f"{len(sel)} fichier(s) supprimé(s)")

    def _rev_retraduire(self, mode_online: bool):
        """Relance réellement la traduction des fichiers sélectionnés.

        Supprime la sortie et le checkpoint corrompus, coche les PDF sources
        correspondants dans l'onglet Traduction, puis démarre le pipeline.
        """
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Retraduction", "Un traitement est déjà en cours.")
            return

        sel = self.rev_tree.selection()
        if sel:
            cibles = [r for r in self.rev_resultats if r["nom_base"] in sel]
        else:
            cibles = [r for r in self.rev_resultats if not r["est_fr"]]
        if not cibles:
            self.rev_status.config(text="Aucun fichier à retraduire")
            return

        mode = "en ligne (Google)" if mode_online else "hors ligne (Argos)"
        if not messagebox.askyesno(
            "Confirmer la retraduction",
            f"Retraduire {len(cibles)} fichier(s) en mode {mode} ?\n\n"
            f"Les fichiers de sortie actuels et leurs checkpoints seront supprimés.",
        ):
            return

        dossier = self.var_dossier.get()
        sources_dir = os.path.join(dossier, "pdfs_originaux")
        checkpoints_dir = os.path.join(dossier, "checkpoints")

        a_traduire: list[str] = []
        introuvables: list[str] = []
        for r in cibles:
            nom_base = r["nom_base"]
            # Supprimer la sortie corrompue
            if os.path.exists(r["chemin"]):
                try:
                    os.remove(r["chemin"])
                except OSError as e:
                    self._append_log(f"❌ Suppression impossible ({r['chemin_rel']}) : {e}")
            # Supprimer le checkpoint associé
            cp = os.path.join(checkpoints_dir, nom_base + ".json")
            if os.path.exists(cp):
                try:
                    os.remove(cp)
                except OSError:
                    pass
            # Retrouver le PDF source
            source_rel = nom_base + ".pdf"
            if os.path.exists(os.path.join(sources_dir, source_rel)):
                a_traduire.append(source_rel)
            else:
                introuvables.append(nom_base)

        if introuvables:
            self._append_log(
                f"⚠️ {len(introuvables)} source(s) introuvable(s) dans pdfs_originaux/ : "
                + ", ".join(introuvables[:5])
                + (" ..." if len(introuvables) > 5 else "")
            )
        if not a_traduire:
            self.rev_status.config(text="❌ Aucun PDF source correspondant trouvé")
            return

        # Préparer l'onglet Traduction : mode + sélection exacte
        self.var_mode.set("traduire" if mode_online else "traduire_offline")
        self.var_ignorer.set(False)
        self._refresh_pdf_list()
        self._deselect_all()
        self._cocher_fichiers(a_traduire)
        self._actualiser_statut_offline()
        self.notebook.select(0)

        self._append_log(f"🔄 Retraduction de {len(a_traduire)} fichier(s) — mode {mode}")
        self.rev_status.config(
            text=f"🔄 Retraduction lancée pour {len(a_traduire)} fichier(s)"
        )
        self._demarrer()

    def _cocher_fichiers(self, chemins_relatifs: list[str]):
        """Coche dans l'arborescence les fichiers dont le chemin est fourni."""
        cibles = set(chemins_relatifs)
        for item in self._get_all_items():
            tags = self.pdf_tree.item(item, "tags")
            if "file" not in tags or item not in cibles:
                continue
            txt = self.pdf_tree.item(item, "text")
            self.pdf_tree.item(item, text=txt.replace("\u2610", "\u2611"))

    def _rev_retraduire_online(self):
        self._rev_retraduire(mode_online=True)

    def _rev_retraduire_offline(self):
        self._rev_retraduire(mode_online=False)

    # ── ONGLET 5 : TABLEAU DE BORD ──
    # ── ONGLET : GLOSSAIRE ──
    def _build_tab_glossaire(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Glossaire")

        self._glo_db: dict = {}
        self._glo_modifie = False

        # Barre supérieure : roman + recherche
        top = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        top.pack(fill="x", padx=20, pady=12)

        top_inner = tk.Frame(top, bg=T["card"])
        top_inner.pack(fill="x", padx=16, pady=12)

        tk.Label(top_inner, text="Roman :", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_glo_roman = tk.StringVar()
        self.combo_glo_roman = ttk.Combobox(top_inner, textvariable=self.var_glo_roman,
                                            state="readonly", width=42)
        self.combo_glo_roman.pack(side="left", padx=(8, 12))
        self.combo_glo_roman.bind("<<ComboboxSelected>>", lambda e: self._glo_rafraichir_table())

        tk.Label(top_inner, text="Rechercher :", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_glo_filtre = tk.StringVar()
        ent = ttk.Entry(top_inner, textvariable=self.var_glo_filtre, width=22)
        ent.pack(side="left", padx=(6, 12))
        self.var_glo_filtre.trace_add("write", lambda *_: self._glo_rafraichir_table())

        self.var_glo_valides = tk.BooleanVar(value=False)
        tk.Checkbutton(top_inner, text="Validés uniquement", variable=self.var_glo_valides,
                       command=self._glo_rafraichir_table, font=self.f_sub,
                       bg=T["card"], fg=T["fg"], selectcolor=T["card2"],
                       activebackground=T["card"], activeforeground=T["fg"],
                       highlightthickness=0, bd=0).pack(side="left")

        self._btn(top_inner, "Recharger", self._glo_charger,
                  T["card2"], T["accent_h"], T["fg"]).pack(side="right")

        # Table des termes
        table_frame = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        table_frame.pack(fill="both", expand=True, padx=20)

        self.glo_tree = ttk.Treeview(table_frame, columns=("terme", "traduction", "etat"),
                                     show="headings", height=18)
        for col, titre, largeur in [("terme", "Terme source", 300),
                                    ("traduction", "Traduction", 300),
                                    ("etat", "État", 110)]:
            self.glo_tree.heading(col, text=titre)
            self.glo_tree.column(col, width=largeur)
        self.glo_tree.tag_configure("valide", foreground=T["green"])
        self.glo_tree.tag_configure("attente", foreground=T["muted"])
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.glo_tree.yview)
        self.glo_tree.configure(yscrollcommand=vsb.set)
        self.glo_tree.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=12)
        vsb.pack(side="right", fill="y", pady=12, padx=(0, 16))
        self.glo_tree.bind("<<TreeviewSelect>>", lambda e: self._glo_selectionner())
        self.glo_tree.bind("<Double-1>", lambda e: self._glo_selectionner())

        # Édition d'une entrée
        edit = tk.Frame(tab, bg=T["card"], highlightthickness=1, highlightbackground=T["card2"])
        edit.pack(fill="x", padx=20, pady=(8, 12))
        e_inner = tk.Frame(edit, bg=T["card"])
        e_inner.pack(fill="x", padx=16, pady=12)

        tk.Label(e_inner, text="Terme", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_glo_terme = tk.StringVar()
        ttk.Entry(e_inner, textvariable=self.var_glo_terme, width=28).pack(side="left", padx=(6, 14))

        tk.Label(e_inner, text="Traduction", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_glo_trad = tk.StringVar()
        entree_trad = ttk.Entry(e_inner, textvariable=self.var_glo_trad, width=28)
        entree_trad.pack(side="left", padx=(6, 14))
        entree_trad.bind("<Return>", lambda e: self._glo_enregistrer_terme())

        self._btn(e_inner, "Enregistrer", self._glo_enregistrer_terme,
                  T["green"], T["green_h"]).pack(side="left", padx=(0, 6))
        self._btn(e_inner, "Supprimer", self._glo_supprimer_terme,
                  T["red"], T["red_h"]).pack(side="left")

        # Barre du bas : import/export + statut
        bas = tk.Frame(tab, bg=T["bg"])
        bas.pack(fill="x", padx=20, pady=(0, 16))
        self._btn(bas, "Écrire sur le disque", self._glo_sauvegarder,
                  T["accent"], T["accent_h"]).pack(side="left", padx=(0, 6))
        self._btn(bas, "Exporter CSV", self._glo_exporter,
                  T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 6))
        self._btn(bas, "Importer CSV", self._glo_importer,
                  T["card2"], T["accent_h"], T["fg"]).pack(side="left")

        self.glo_status = tk.Label(bas, text="", font=self.f_small,
                                   bg=T["bg"], fg=T["muted"], anchor="e")
        self.glo_status.pack(side="right")

        self.root.after(600, self._glo_charger)

    # ── Méthodes de l'onglet Glossaire ──

    def _glo_chemin(self) -> str:
        from moteur import glossaire as glo
        return glo.chemin_db(self.var_dossier.get() or os.getcwd())

    def _glo_charger(self):
        from moteur import glossaire as glo
        self._glo_db = glo.charger(self._glo_chemin())
        self._glo_modifie = False
        noms = glo.romans(self._glo_db)
        self.combo_glo_roman.configure(values=noms)
        if noms and self.var_glo_roman.get() not in noms:
            self.var_glo_roman.set(noms[0])
        self._glo_rafraichir_table()

    def _glo_rafraichir_table(self):
        from moteur import glossaire as glo
        for item in self.glo_tree.get_children():
            self.glo_tree.delete(item)
        roman = self.var_glo_roman.get()
        if not roman:
            self.glo_status.config(text="Aucun glossaire chargé.")
            return
        entrees = glo.termes(self._glo_db, roman, self.var_glo_filtre.get(),
                             self.var_glo_valides.get())
        # Limite d'affichage : les glossaires dépassent 20 000 entrées.
        limite = 500
        for terme, trad in entrees[:limite]:
            valide = trad != terme
            self.glo_tree.insert(
                "", "end", values=(terme, trad, "validé" if valide else "en attente"),
                tags=("valide" if valide else "attente",),
            )
        st = glo.statistiques(self._glo_db, roman)
        suffixe = f" — {limite} premiers affichés" if len(entrees) > limite else ""
        marque = " *" if self._glo_modifie else ""
        self.glo_status.config(
            text=f"{len(entrees)} résultat(s) | {st['valides']} validé(s) / "
                 f"{st['total']} terme(s){suffixe}{marque}"
        )

    def _glo_selectionner(self):
        sel = self.glo_tree.selection()
        if not sel:
            return
        terme, trad, _ = self.glo_tree.item(sel[0], "values")
        self.var_glo_terme.set(terme)
        self.var_glo_trad.set(trad)

    def _glo_enregistrer_terme(self):
        from moteur import glossaire as glo
        roman = self.var_glo_roman.get()
        if not roman:
            messagebox.showwarning("Glossaire", "Sélectionnez d'abord un roman.")
            return
        terme = self.var_glo_terme.get().strip()
        if not terme:
            messagebox.showwarning("Glossaire", "Le terme ne peut pas être vide.")
            return
        glo.definir_terme(self._glo_db, roman, terme, self.var_glo_trad.get())
        self._glo_modifie = True
        self._glo_rafraichir_table()

    def _glo_supprimer_terme(self):
        from moteur import glossaire as glo
        roman = self.var_glo_roman.get()
        terme = self.var_glo_terme.get().strip()
        if not roman or not terme:
            return
        if not glo.supprimer_terme(self._glo_db, roman, terme):
            messagebox.showinfo("Glossaire", f"Terme introuvable : {terme}")
            return
        self._glo_modifie = True
        self.var_glo_terme.set("")
        self.var_glo_trad.set("")
        self._glo_rafraichir_table()

    def _glo_sauvegarder(self):
        from moteur import glossaire as glo
        try:
            glo.sauvegarder(self._glo_db, self._glo_chemin())
        except OSError as e:
            messagebox.showerror("Glossaire", f"Écriture impossible : {e}")
            return
        self._glo_modifie = False
        self._append_log(f"Glossaire enregistré : {self._glo_chemin()}")
        self._glo_rafraichir_table()

    def _glo_exporter(self):
        from moteur import glossaire as glo
        roman = self.var_glo_roman.get()
        if not roman:
            return
        chemin = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile=f"{roman}.csv",
            filetypes=[("CSV", "*.csv")])
        if not chemin:
            return
        nb = glo.exporter_csv(self._glo_db, roman, chemin)
        self._append_log(f"Glossaire exporté : {nb} terme(s) → {chemin}")

    def _glo_importer(self):
        from moteur import glossaire as glo
        roman = self.var_glo_roman.get()
        if not roman:
            messagebox.showwarning("Glossaire", "Sélectionnez d'abord un roman.")
            return
        chemin = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not chemin:
            return
        ecraser = messagebox.askyesno(
            "Import CSV", "Écraser les termes déjà présents ?")
        nb = glo.importer_csv(self._glo_db, roman, chemin, ecraser)
        self._glo_modifie = True
        self._append_log(f"Glossaire importé : {nb} terme(s) depuis {chemin}")
        self._glo_rafraichir_table()

    def _build_tab_dashboard(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Tableau de bord")

        top = tk.Frame(tab, bg=T["bg"])
        top.pack(fill="x", padx=20, pady=(14, 8))
        self._btn(top, "Actualiser", self._refresh_dashboard, T["accent"], T["accent_h"]).pack(side="left")

        # Cartes statistiques
        sc = tk.Frame(tab, bg=T["bg"])
        sc.pack(fill="x", padx=20)
        self.stat_labels = {}
        stat_data = [
            ("sessions", "Sessions"),
            ("pages", "Total pages"),
            ("fichiers", "Total fichiers"),
            ("duree", "Temps total"),
        ]
        for i, (key, label) in enumerate(stat_data):
            card = tk.Frame(sc, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
            card.grid(row=0, column=i, sticky="nsew", padx=4, pady=4, ipady=12)
            sc.columnconfigure(i, weight=1)
            tk.Label(card, text=label, font=self.f_sub, bg=T["card"], fg=T["muted"]).pack()
            lbl_val = tk.Label(card, text="\u2014", font=self.f_big, bg=T["card"], fg=T["accent"])
            lbl_val.pack()
            self.stat_labels[key] = lbl_val

        # Sessions récentes
        hist_frame = tk.LabelFrame(tab, text="Sessions récentes", font=self.f_lbl,
                                   bd=0, bg=T["card"], fg=T["accent"])
        hist_frame.pack(fill="both", expand=True, padx=20, pady=(12, 8))

        self.stats_tree = ttk.Treeview(hist_frame,
            columns=("date", "pages", "fichiers", "temps", "langues", "statut"),
            show="headings", height=6)
        cols = [("date", 170), ("pages", 60), ("fichiers", 65), ("temps", 70), ("langues", 80), ("statut", 100)]
        for col, w in cols:
            self.stats_tree.heading(col, text=col.capitalize())
            self.stats_tree.column(col, width=w)
        self.stats_tree.pack(fill="both", expand=True, padx=10, pady=10)

        # Activité hebdomadaire — histogramme
        hebdo_frame = tk.LabelFrame(tab, text="Pages traduites (14 derniers jours)",
                                    font=self.f_lbl, bd=0, bg=T["card"], fg=T["accent"])
        hebdo_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.hebdo_canvas = tk.Canvas(hebdo_frame, height=150, bg=T["card"],
                                      highlightthickness=0, bd=0)
        self.hebdo_canvas.pack(fill="x", padx=10, pady=10)
        self.hebdo_canvas.bind("<Configure>", lambda e: self._dessiner_hebdo())
        self._hebdo_data: list = []

    def _dessiner_hebdo(self):
        """Dessine l'histogramme d'activité des 14 derniers jours."""
        T = self._theme
        c = self.hebdo_canvas
        c.delete("all")
        largeur = c.winfo_width()
        hauteur = c.winfo_height()
        if largeur < 50 or hauteur < 40:
            return

        donnees = self._hebdo_data
        if not donnees:
            c.create_text(largeur // 2, hauteur // 2,
                          text="Aucune activité enregistrée",
                          fill=T["muted"], font=self.f_sub)
            return

        marge_g, marge_d = 44, 12
        marge_h, marge_b = 14, 26
        zone_l = max(largeur - marge_g - marge_d, 10)
        zone_h = max(hauteur - marge_h - marge_b, 10)

        maxi = max((d[1] for d in donnees), default=0) or 1
        n = len(donnees)
        pas = zone_l / n
        largeur_barre = max(min(pas * 0.62, 46), 3)

        # Lignes de repère horizontales
        for frac in (0, 0.5, 1.0):
            y = marge_h + zone_h * (1 - frac)
            c.create_line(marge_g, y, largeur - marge_d, y,
                          fill=T["card2"], width=1)
            c.create_text(marge_g - 6, y, text=str(int(maxi * frac)),
                          anchor="e", fill=T["muted"], font=self.f_small)

        for i, (jour, pages, fichiers, duree) in enumerate(donnees):
            x_centre = marge_g + pas * (i + 0.5)
            h_barre = (pages / maxi) * zone_h if maxi else 0
            y0 = marge_h + zone_h - h_barre
            y1 = marge_h + zone_h
            couleur = T["accent"] if pages else T["card2"]
            c.create_rectangle(x_centre - largeur_barre / 2, y0,
                               x_centre + largeur_barre / 2, y1,
                               fill=couleur, outline="")
            if pages:
                c.create_text(x_centre, y0 - 7, text=str(pages),
                              fill=T["fg"], font=self.f_small)
            # Étiquette du jour (JJ/MM), une sur deux si serré
            if pas > 34 or i % 2 == 0:
                try:
                    etiquette = f"{jour[8:10]}/{jour[5:7]}"
                except (IndexError, TypeError):
                    etiquette = str(jour)
                c.create_text(x_centre, marge_h + zone_h + 12, text=etiquette,
                              fill=T["muted"], font=self.f_small)

    # ── ONGLET 4 : HISTORIQUE ──
    def _build_tab_history(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Historique")

        top = tk.Frame(tab, bg=T["bg"])
        top.pack(fill="x", padx=20, pady=(14, 8))
        self._btn(top, "Actualiser", self._refresh_history, T["accent"], T["accent_h"]).pack(side="left")

        # History in a card
        hist_card = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        hist_card.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.hist_tree = ttk.Treeview(hist_card,
            columns=("id", "date", "fichiers", "pages", "temps", "src", "dst", "statut", "format"),
            show="headings", height=24)
        cols = [("id", 35), ("date", 165), ("fichiers", 60), ("pages", 55), ("temps", 65),
                ("src", 50), ("dst", 50), ("statut", 95), ("format", 60)]
        for col, w in cols:
            self.hist_tree.heading(col, text=col.capitalize())
            self.hist_tree.column(col, width=w)
        self.hist_tree.pack(fill="both", expand=True, padx=16, pady=16)

    # ── ONGLET 5 : CONFIGURATION ──
    def _build_tab_settings(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Configuration")

        canvas = tk.Canvas(tab, bg=T["bg"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(tab, orient="vertical", command=canvas.yview, bg=T["card2"])
        scrollable = tk.Frame(canvas, bg=T["bg"])
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._build_pdf_styles(scrollable)
        self._build_proxy_section(scrollable)
        self._build_spell_section(scrollable)
        self._build_merge_section(scrollable)
        self._build_maintenance_section(scrollable)
        self._build_info_section(scrollable)

    # ── SOUS-SECTIONS CONFIGURATION ──
    def _build_pdf_styles(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="Styles PDF", font=self.f_lbl,
                              bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=20, pady=10)
        inner = tk.Frame(frame, bd=0, bg=T["card"])
        inner.pack(fill="x", padx=12, pady=12)

        self.style_vars = {}
        fields = [
            ("Taille police", "font_size", 11, 1, 50),
            ("Taille chapitre", "chapter_font_size", 13, 1, 50),
            ("Interlignage", "line_spacing", 17, 8, 50),
            ("Marge haute (cm)", "margin_top", 2.5, 0, 10),
            ("Marge basse (cm)", "margin_bottom", 2.5, 0, 10),
            ("Marge gauche (cm)", "margin_left", 2.5, 0, 10),
            ("Marge droite (cm)", "margin_right", 2.5, 0, 10),
        ]
        for i, (label, key, default, f, t) in enumerate(fields):
            tk.Label(inner, text=label, font=self.f_sub, bg=T["card"], fg=T["fg"]).grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(default))
            w = ttk.Spinbox(inner, from_=f, to=t, textvariable=var, width=7)
            w.grid(row=i, column=1, padx=(10, 20), pady=3)
            self.style_vars[key] = var

        tk.Label(inner, text="Police :", font=self.f_sub, bg=T["card"], fg=T["fg"]).grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.var_font_style = tk.StringVar(value="DejaVu Sans")
        ttk.Combobox(inner, textvariable=self.var_font_style, state="readonly", width=16,
                     values=["DejaVu Sans", "Helvetica", "Courier"]).grid(row=0, column=3, padx=(8, 0))

        tk.Label(inner, text="Couleur texte :", font=self.f_sub, bg=T["card"], fg=T["fg"]).grid(row=1, column=2, sticky="w", padx=(20, 0))
        self.var_font_color = tk.StringVar(value="#222222")
        ttk.Combobox(inner, textvariable=self.var_font_color, state="readonly", width=16,
                     values=["#222222", "#333333", "#111111", "#000000"]).grid(row=1, column=3, padx=(8, 0))

        tk.Label(inner, text="Format page :", font=self.f_sub, bg=T["card"], fg=T["fg"]).grid(row=2, column=2, sticky="w", padx=(20, 0))
        self.var_page_size = tk.StringVar(value="A4")
        ttk.Combobox(inner, textvariable=self.var_page_size, state="readonly", width=16,
                     values=["A4", "Letter"]).grid(row=2, column=3, padx=(8, 0))

    def _build_proxy_section(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="Rotation de proxys", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=16, pady=8)
        inner = tk.Frame(frame,         bd=0, bg=T["card"])
        inner.pack(fill="x", padx=10, pady=10)

        tk.Label(inner, text="Un proxy par ligne :", font=self.f_sub,
                bg=T["card"], fg=T["fg"]).pack(anchor="w")
        tk.Label(inner, text="http://ip:port ou http://user:pass@ip:port",
                font=self.f_small, bg=T["card"], fg=T["muted"]).pack(anchor="w")
        self.var_proxies = tk.Text(inner, height=3, bg=T["card2"], fg=T["fg"],
                                  insertbackground=T["fg"], font=self.f_mono,
                                  relief="flat", bd=4, highlightthickness=0)
        self.var_proxies.pack(fill="x", pady=(4, 0))

    def _build_spell_section(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="Correction orthographique", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=16, pady=8)
        inner = tk.Frame(frame,         bd=0, bg=T["card"])
        inner.pack(fill="x", padx=10, pady=10)

        tk.Label(inner, text="Langue :", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_ortho_lang = tk.StringVar(value="fr")
        ttk.Combobox(inner, textvariable=self.var_ortho_lang, state="readonly", width=6,
                     values=["fr", "en", "es", "de", "it"]).pack(side="left", padx=(8, 0))
        tk.Label(inner, text="Nécessite : pip install language-tool-python",
                font=self.f_small, bg=T["card"], fg=T["muted"]).pack(side="left", padx=(20, 0))

    def _build_merge_section(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="Fusion PDF", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=16, pady=8)
        inner = tk.Frame(frame,         bd=0, bg=T["card"])
        inner.pack(fill="x", padx=10, pady=10)

        tk.Label(inner, text="Fusionner tous les PDF générés en un seul fichier",
                font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(anchor="w")
        mr = tk.Frame(inner, bg=T["card"])
        mr.pack(fill="x", pady=(8, 0))
        tk.Label(mr, text="Fichier sortie :", font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        self.var_merge_name = tk.StringVar(value="traduction_complete.pdf")
        ttk.Entry(mr, textvariable=self.var_merge_name, width=35).pack(side="left", padx=(8, 6))
        self._btn(mr, "Parcourir", self._choose_merge_path, T["card2"], T["accent_h"], T["fg"]).pack(side="left")

    def _build_maintenance_section(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="Maintenance et espace disque", font=self.f_lbl,
                              bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=16, pady=8)
        inner = tk.Frame(frame, bd=0, bg=T["card"])
        inner.pack(fill="x", padx=10, pady=10)

        tk.Label(inner,
                 text="Le cache d'extraction et la base de traductions grossissent "
                      "à chaque exécution.",
                 font=self.f_small, bg=T["card"], fg=T["muted"]).pack(anchor="w")

        grid = tk.Frame(inner, bg=T["card"])
        grid.pack(fill="x", pady=(8, 8))
        self.maint_labels = {}
        lignes = [
            ("extraction", "Cache d'extraction"),
            ("cache_traduction", "Cache de traduction"),
            ("checkpoints", "Checkpoints"),
            ("sortie", "Documents traduits"),
        ]
        for i, (cle, libelle) in enumerate(lignes):
            tk.Label(grid, text=libelle, font=self.f_sub, bg=T["card"],
                     fg=T["fg"], anchor="w").grid(row=i, column=0, sticky="w", pady=1)
            lbl = tk.Label(grid, text="\u2014", font=self.f_mono, bg=T["card"],
                           fg=T["accent"], anchor="e")
            lbl.grid(row=i, column=1, sticky="e", padx=(20, 0), pady=1)
            self.maint_labels[cle] = lbl
        grid.columnconfigure(1, weight=1)

        opts = tk.Frame(inner, bg=T["card"])
        opts.pack(fill="x", pady=(0, 8))
        self.var_maint_jours = tk.StringVar(value="30")
        tk.Label(opts, text="Purger le cache d'extraction plus vieux que",
                 font=self.f_sub, bg=T["card"], fg=T["fg"]).pack(side="left")
        ttk.Combobox(opts, textvariable=self.var_maint_jours, state="readonly", width=6,
                     values=["0", "7", "30", "90"]).pack(side="left", padx=6)
        tk.Label(opts, text="jours (0 = tout)", font=self.f_small,
                 bg=T["card"], fg=T["muted"]).pack(side="left")

        actions = tk.Frame(inner, bg=T["card"])
        actions.pack(fill="x")
        self._btn(actions, "Analyser", self._maint_analyser,
                  T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 6))
        self._btn(actions, "Nettoyer", self._maint_nettoyer,
                  T["accent"], T["accent_h"]).pack(side="left", padx=(0, 6))
        self._btn(actions, "Vider le cache de traduction", self._maint_vider_cache,
                  T["red"], T["red_h"]).pack(side="left")

        self.maint_status = tk.Label(inner, text="", font=self.f_small,
                                     bg=T["card"], fg=T["muted"], anchor="w",
                                     justify="left")
        self.maint_status.pack(fill="x", pady=(8, 0))

    def _maint_analyser(self):
        """Recalcule l'inventaire disque et met à jour l'affichage."""
        from moteur import maintenance as mnt

        self.maint_status.config(text="Analyse en cours...")
        self.root.update_idletasks()
        moteur.configurer(self._config_moteur())
        try:
            inv = mnt.inventaire()
        except Exception as e:
            self.maint_status.config(text=f"Erreur : {e}")
            return
        for cle, lbl in self.maint_labels.items():
            info = inv.get(cle, {})
            taille = mnt.formater_taille(info.get("taille", 0))
            nb = info.get("nb", 0)
            unite = "entrées" if cle == "cache_traduction" else "fichiers"
            lbl.config(text=f"{taille}  ({nb} {unite})")
        suspects = mnt.checkpoints_suspects()
        total = sum(i.get("taille", 0) for i in inv.values())
        msg = f"Total occupé : {mnt.formater_taille(total)}"
        if suspects:
            msg += f"  |  {len(suspects)} checkpoint(s) à revoir"
        self.maint_status.config(text=msg)

    def _maint_nettoyer(self):
        """Purge le cache d'extraction, les checkpoints orphelins, compacte la DB."""
        from moteur import maintenance as mnt

        jours = int(self.var_maint_jours.get() or 0)
        libelle = "tout le cache d'extraction" if jours == 0 else \
            f"le cache d'extraction de plus de {jours} jours"
        if not messagebox.askyesno(
            "Nettoyage",
            f"Supprimer {libelle}, les checkpoints orphelins, "
            f"et compacter la base de traduction ?\n\n"
            f"Les documents traduits ne sont pas touchés.",
        ):
            return

        moteur.configurer(self._config_moteur())
        self.maint_status.config(text="Nettoyage en cours...")
        self.root.update_idletasks()
        try:
            rapport = mnt.nettoyage_complet(
                jours_extraction=jours or None,
                callback=self._append_log,
            )
        except Exception as e:
            self.maint_status.config(text=f"Erreur : {e}")
            return
        self.maint_status.config(
            text=f"Terminé — {mnt.formater_taille(rapport['libere'])} libéré(s)."
        )
        self._maint_analyser()

    def _maint_vider_cache(self):
        """Vide entièrement la base SQLite des traductions."""
        from moteur import maintenance as mnt

        if not messagebox.askyesno(
            "Vider le cache",
            "Supprimer TOUTES les traductions mises en cache ?\n\n"
            "Les prochaines traductions devront être refaites intégralement.",
        ):
            return
        moteur.configurer(self._config_moteur())
        try:
            nb = mnt.vider_cache_traduction()
        except Exception as e:
            self.maint_status.config(text=f"Erreur : {e}")
            return
        self._append_log(f"Cache de traduction vidé : {nb} entrée(s).")
        self._maint_analyser()

    def _build_info_section(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="À propos", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=16, pady=8)
        inner = tk.Frame(frame,         bd=0, bg=T["card"])
        inner.pack(fill="x", padx=10, pady=10)

        tk.Label(inner, text=f"{APP_NAME} v{APP_VERSION}",
                font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(anchor="w")
        tk.Label(inner, text="Outil de traduction PDF avec 12 fonctionnalités intégrées :\n"
                "Rotation de proxys, export multi-format, correction orthographique,\n"
                "fusion de PDF, thèmes visuels, statistiques, et plus.",
                font=self.f_sub, bg=T["card"], fg=T["muted"], justify="left").pack(anchor="w", pady=(4, 0))

    # ── AIDES ──
    def _dir_row(self, parent, row, label, var):
        T = self._theme
        tk.Label(parent, text=label, font=self.f_lbl, bg=T["card"], fg=T["fg"]).grid(
            row=row, column=0, sticky="w", pady=4)
        e = ttk.Entry(parent, textvariable=var)
        e.grid(row=row, column=1, sticky="ew", padx=(8, 6), pady=4, ipady=3)
        btn_frame = tk.Frame(parent, bg=T["card"])
        btn_frame.grid(row=row, column=2, pady=4)
        b1 = tk.Button(btn_frame, text="Ouvrir", command=lambda: self._ouvrir_dossier(var),
                       bg=T["accent"], fg="#FFFFFF", activebackground=T["accent_h"],
                       relief="flat", bd=0, padx=14, pady=4, cursor="hand2",
                       font=self.f_sub, highlightthickness=0)
        b1.pack(side="left", padx=(0, 4))
        b2 = tk.Button(btn_frame, text="\u22EF", command=lambda: self._choisir_dossier(var),
                       bg=T["card2"], fg=T["fg"], activebackground=T["accent_h"],
                       relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                       font=self.f_sub, highlightthickness=0)
        b2.pack(side="left")

    def _creer_structure_dossier(self):
        dossier = self.var_dossier.get()
        if not dossier:
            return
        sous_dossiers = ["pdfs_originaux", "pdfs_traduits", "extraction_cache", "checkpoints"]
        crees = []
        for nom in sous_dossiers:
            chemin = os.path.join(dossier, nom)
            if not os.path.exists(chemin):
                try:
                    os.makedirs(chemin, exist_ok=True)
                    crees.append(nom)
                except Exception:
                    continue
        if crees:
            self._append_log(f"Dossiers créés : {', '.join(crees)}")

    def _choisir_dossier(self, var):
        try:
            result = subprocess.run(
                ["zenity", "--file-selection", "--directory",
                 f"--filename={var.get() or '.'}/"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                var.set(result.stdout.strip())
                self._creer_structure_dossier()
        except Exception:
            d = filedialog.askdirectory(initialdir=var.get() or ".")
            if d:
                var.set(d)
                self._creer_structure_dossier()

    def _ouvrir_dossier(self, var):
        chemin = var.get() or os.getcwd()
        if os.path.isdir(chemin):
            subprocess.Popen(["xdg-open", chemin])

    def _choose_merge_path(self):
        d = filedialog.asksaveasfilename(defaultextension=".pdf",
                                          initialfile=self.var_merge_name.get(),
                                          filetypes=[("PDF", "*.pdf")])
        if d:
            self.var_merge_name.set(d)

    # ── DND / CLIPBOARD ──
    def _setup_dnd(self):
        try:
            self.pdf_tree.drop_target_register("*")
            self.pdf_tree.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _setup_clipboard(self):
        self.root.bind("<Control-v>", self._on_paste)

    def _on_drop(self, event):
        files = []
        raw = getattr(event, "data", "")
        for item in raw.split():
            item = item.strip("{}")
            if item.startswith("file://"):
                item = urllib.parse.unquote(item[7:])
            if item.lower().endswith(".pdf") and os.path.isfile(item):
                files.append(item)
        if files:
            self._import_files(files)

    def _on_paste(self, event=None):
        try:
            raw = self.root.clipboard_get()
        except tk.TclError:
            return
        files = []
        for line in raw.split():
            line = line.strip()
            if line.startswith("file://"):
                line = urllib.parse.unquote(line[7:])
            if line.lower().endswith(".pdf") and os.path.isfile(line):
                files.append(line)
        if files:
            self._import_files(files)

    def _import_files(self, files):
        originaux_dir = os.path.join(self.var_dossier.get(), "pdfs_originaux")
        if not os.path.isdir(originaux_dir):
            try:
                os.makedirs(originaux_dir, exist_ok=True)
            except Exception as e:
                self._append_log(f"Impossible de créer {originaux_dir} : {e}")
                return
        imported = []
        for src_path in files:
            basename = os.path.basename(src_path)
            dest = os.path.join(originaux_dir, basename)
            name, ext = os.path.splitext(basename)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(originaux_dir, f"{name}_{counter}{ext}")
                counter += 1
            try:
                shutil.copy2(src_path, dest)
                imported.append(os.path.relpath(dest, originaux_dir))
            except Exception:
                continue
        if imported:
            self._append_log(f"{len(imported)} PDF(s) importé(s)")
            self._refresh_pdf_list(filter_to=imported)

    def _supprimer_selection(self):
        selected = self._get_selected_pdfs()
        if not selected:
            return
        tous = list(self.all_pdfs)
        restants = [f for f in tous if f not in selected]
        self._refresh_pdf_list(filter_to=restants)
        self._append_log(f"{len(selected)} fichier(s) retiré(s) de la liste")

    def _update_filter_ui(self):
        T = self._theme
        try:
            self.btn_tout_afficher.pack_forget()
            self.btn_tout_afficher.destroy()
        except Exception:
            pass
        if self._filtered is not None:
            self.btn_tout_afficher = self._btn(
                self.btn_frame, "Tout afficher", self._refresh_pdf_list,
                T["accent"], T["accent_h"], "#FFFFFF")
            self.btn_tout_afficher.pack(side="left", padx=(4, 0))

    # ── ARBRE PDF ──
    def _collecter_noms_bases_traduits(self, dossier_traduits: str) -> set[str]:
        """Parcourt `dossier_traduits` et retourne l'ensemble des `nom_base`
        (chemin relatif sans extension ni suffixe `_traduit_xx`) déjà traduits."""
        traduits: set[str] = set()
        if not os.path.isdir(dossier_traduits):
            return traduits
        try:
            for p in glob.iglob(
                os.path.join(dossier_traduits, "**", "*_traduit_*.*"),
                recursive=True,
            ):
                if not os.path.isfile(p):
                    continue
                rel = os.path.relpath(p, dossier_traduits)
                nom_base = extraire_nom_base_de_sortie(rel)
                if nom_base:
                    traduits.add(nom_base.replace("\\", "/"))
        except (PermissionError, OSError):
            pass
        return traduits

    def _refresh_pdf_list(self, filter_to=None):
        for item in self.pdf_tree.get_children():
            self.pdf_tree.delete(item)
        self.all_pdfs = []
        src_originaux = os.path.join(self.var_dossier.get(), "pdfs_originaux")
        if not os.path.isdir(src_originaux):
            self.lbl_pdf_count.config(text="pdfs_originaux/ introuvable")
            return
        try:
            exclus = {"traduits", "extraction_cache", "checkpoints"}
            pdfs = []
            pattern = os.path.join(src_originaux, "**", "*.pdf")
            for p in glob.iglob(pattern, recursive=True):
                r = os.path.relpath(p, src_originaux)
                parties = r.split(os.sep)
                if not any(ex in parties for ex in exclus):
                    pdfs.append(r)
            pdfs.sort(key=moteur.tri_naturel)
        except (PermissionError, OSError) as e:
            self.lbl_pdf_count.config(text=f"Erreur : {e}")
            return
        total_originaux = len(pdfs)
        if filter_to is not None:
            self._filtered = set(filter_to)
            pdfs = [f for f in pdfs if f in self._filtered]
        else:
            self._filtered = None
            # Filtrage automatique : ne garder que les PDFs pas encore traduits
            dossier_traduits = os.path.join(self.var_dossier.get(), "pdfs_traduits")
            traduits = self._collecter_noms_bases_traduits(dossier_traduits)
            if traduits:
                filtres = []
                for p in pdfs:
                    nom_base = os.path.splitext(p)[0].replace("\\", "/")
                    if nom_base not in traduits:
                        filtres.append(p)
                pdfs = filtres
        self._pdfs_total_originaux = total_originaux
        self._pdfs_total_apres_filtre = len(pdfs)
        self._folder_enfants = {}
        self.all_pdfs = pdfs
        self._build_pdf_tree(pdfs)
        self._update_filter_ui()

    def _build_pdf_tree(self, pdfs):
        groupes = {}
        racine = []
        for pdf in pdfs:
            if os.sep in pdf:
                dossier = pdf.split(os.sep)[0]
                groupes.setdefault(dossier, []).append(pdf)
            else:
                racine.append(pdf)
        n_folders = len(groupes)
        n_files = len(pdfs)
        # Dossiers triés puis fichiers racine
        for dossier in sorted(groupes.keys(), key=moteur.tri_naturel):
            enfants = sorted(groupes[dossier], key=moteur.tri_naturel)
            display = f"\u2611 \U0001f4c1 {dossier} ({len(enfants)})"
            self.pdf_tree.insert("", "end", iid=f"dossier:{dossier}",
                                 text=display, tags=("folder",))
            self._folder_enfants[f"dossier:{dossier}"] = enfants
        for pdf in racine:
            self.pdf_tree.insert("", "end", iid=pdf,
                                 text=f"\u2611 {pdf}",
                                 tags=("file",))
        if n_folders:
            self.lbl_pdf_count.config(
                text=f"{n_folders} dossier(s) \u2022 {n_files} fichier(s)"
            )
        else:
            self.lbl_pdf_count.config(text=f"{n_files} fichier(s)")
        # Indique le nombre de fichiers non traduits / total si filtre actif
        total_orig = getattr(self, "_pdfs_total_originaux", None)
        if (
            self._filtered is None
            and total_orig is not None
            and total_orig != n_files
        ):
            if n_folders:
                self.lbl_pdf_count.config(
                    text=f"{n_folders} dossier(s) \u2022 {n_files}/{total_orig} "
                         f"fichier(s) non traduit(s)"
                )
            else:
                self.lbl_pdf_count.config(
                    text=f"{n_files}/{total_orig} fichier(s) non traduit(s)"
                )

    def _get_all_items(self, parent=""):
        items = []
        for item in self.pdf_tree.get_children(parent):
            items.append(item)
            items.extend(self._get_all_items(item))
        return items

    def _on_tree_click(self, event):
        item = self.pdf_tree.identify_row(event.y)
        if not item:
            return
        tags = self.pdf_tree.item(item, "tags")
        if "folder" in tags:
            self._toggle_folder(item)
        elif "file" in tags:
            self._toggle_file(item)

    def _toggle_file(self, item):
        text = self.pdf_tree.item(item, "text")
        if "\u2611" in text:
            self.pdf_tree.item(item, text=text.replace("\u2611", "\u2610"))
        else:
            self.pdf_tree.item(item, text=text.replace("\u2610", "\u2611"))

    def _toggle_folder(self, item):
        text = self.pdf_tree.item(item, "text")
        enfants = self._folder_enfants.get(item, [])
        if not enfants:
            return
        # Bascule le dossier et tous ses fichiers enfants
        is_checked = "\u2611" in text
        new_state = "\u2610" if is_checked else "\u2611"
        self.pdf_tree.item(item, text=text.replace("\u2611", new_state).replace("\u2610", new_state))
        for child_path in enfants:
            if self.pdf_tree.exists(child_path):
                old = self.pdf_tree.item(child_path, "text")
                if new_state == "\u2611":
                    self.pdf_tree.item(child_path, text=old.replace("\u2610", "\u2611"))
                else:
                    self.pdf_tree.item(child_path, text=old.replace("\u2611", "\u2610"))

    def _expand_all(self):
        pass

    def _collapse_all(self):
        pass

    def _filter_tree(self):
        query = self.var_tree_search.get().strip().lower()
        for item in list(self._get_all_items()):
            try:
                self.pdf_tree.move(item, "", "end")
            except tk.TclError:
                pass
        if not query:
            return
        for item in self._get_all_items():
            txt = self.pdf_tree.item(item, "text").lower()
            if query not in txt:
                self.pdf_tree.detach(item)

    def _select_all(self):
        for item in self._get_all_items():
            txt = self.pdf_tree.item(item, "text")
            self.pdf_tree.item(item, text=txt.replace("\u2610", "\u2611"))

    def _deselect_all(self):
        for item in self._get_all_items():
            txt = self.pdf_tree.item(item, "text")
            self.pdf_tree.item(item, text=txt.replace("\u2611", "\u2610"))

    def _get_selected_pdfs(self):
        selected = []
        for item in self._get_all_items():
            tags = self.pdf_tree.item(item, "tags")
            txt = self.pdf_tree.item(item, "text")
            if "file" in tags and "\u2611" in txt:
                selected.append(item)
            elif "folder" in tags and "\u2611" in txt:
                selected.extend(self._folder_enfants.get(item, []))
        return selected

    # ── APERÇU ──
    def _refresh_preview_list(self):
        src = os.path.join(self.var_dossier.get(), "pdfs_originaux")
        if not os.path.isdir(src):
            self.preview_combo["values"] = []
            return
        try:
            pdfs = sorted(
                (os.path.relpath(p, src) for p in glob.iglob(
                    os.path.join(src, "**", "*.pdf"), recursive=True)),
                key=moteur.tri_naturel
            )
        except (PermissionError, OSError):
            self.preview_combo["values"] = []
            return
        self.preview_combo["values"] = pdfs
        if pdfs:
            self.preview_combo.current(0)
            self._load_preview()

    def _load_preview(self, event=None):
        try:
            nom = self.preview_file_var.get()
            if not nom:
                return
            nom_base = os.path.splitext(nom)[0]
            pages = None
            try:
                pages = moteur.charger_cache_extraction(nom_base)
            except Exception:
                pass
            if pages is None:
                chemin = os.path.join(self.var_dossier.get(), "pdfs_originaux", nom)
                if os.path.exists(chemin):
                    try:
                        pages = moteur.extraire_texte_pdf(chemin)
                    except Exception:
                        pages = None

            self.preview_orig.delete("1.0", "end")
            self.preview_trad.delete("1.0", "end")
            if pages:
                self.preview_orig.insert("1.0", "\n\n".join(pages))
                trad_lines = []
                for txt in pages:
                    try:
                        cached = moteur.cache_get(txt)
                        trad_lines.append(cached if cached else "")
                    except Exception:
                        trad_lines.append("")
                trad_text = "\n\n".join(trad_lines)
                if trad_text.strip():
                    self.preview_trad.insert("1.0", trad_text)
                else:
                    self.preview_trad.insert("1.0", "(Aucune traduction en cache)")
            else:
                self.preview_orig.insert("1.0", "(Impossible de lire le fichier)")
        except Exception:
            self.preview_orig.delete("1.0", "end")
            self.preview_orig.insert("1.0", "(Erreur d'aperçu)")

    def _save_preview_edit(self):
        """Sauvegarde les modifications utilisateur dans le dossier .edits/."""
        nom = self.preview_file_var.get()
        if not nom:
            return
        nom_base = os.path.splitext(nom)[0]
        texte_modifie = self.preview_trad.get("1.0", "end-1c").strip()
        dossier_sortie = os.path.join(self.var_dossier.get(), "pdfs_traduits")
        if texte_modifie:
            chemin = sauvegarder_edits(nom_base, texte_modifie, dossier_sortie)
            self._append_log(f"\U0001f4be \u00c9ditions sauvegard\u00e9es : {nom_base}")
            self.lbl_status.config(text="\u00c9ditions enregistr\u00e9es")
        else:
            # Si vide, supprimer les éditions
            from moteur.editeur import supprimer_edits
            supprimer_edits(nom_base, dossier_sortie)
            self._append_log(f"\u274c \u00c9ditions supprim\u00e9es : {nom_base}")

    # ── TABLEAU DE BORD ──
    def _refresh_dashboard(self):
        sg = stats.get_stats_globales()
        self.stat_labels["sessions"].config(text=str(sg["total_sessions"]))
        self.stat_labels["pages"].config(text=str(sg["total_pages"]))
        self.stat_labels["fichiers"].config(text=str(sg["total_fichiers"]))
        d = sg["total_duree"]
        if d >= 3600:
            self.stat_labels["duree"].config(text=f"{d/3600:.1f}h")
        elif d >= 60:
            self.stat_labels["duree"].config(text=f"{d/60:.0f}min")
        else:
            self.stat_labels["duree"].config(text=f"{d:.0f}s")

        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        for row in sg["dernieres"]:
            self.stats_tree.insert("", "end", values=(
                row[0][:19] if row[0] else "", row[1], row[2],
                f"{row[3]:.0f}s", f"{row[4]}\u2192{row[5]}", row[6]
            ))
        self._hebdo_data = list(reversed(stats.get_stats_hebdomadaires()))
        self._dessiner_hebdo()

    def _refresh_history(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        for row in stats.get_historique(200):
            self.hist_tree.insert("", "end", values=row)

    # ── PROJET ──
    def _sauvegarder_projet(self):
        data = self._export_project_data()
        chemin = filedialog.asksaveasfilename(defaultextension=".json",
                                               initialfile="projet_traduction.json",
                                               filetypes=[("JSON", "*.json")])
        if chemin:
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._append_log(f"Projet sauvegardé : {chemin}")

    def _charger_projet(self):
        chemin = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], initialdir=".")
        if chemin:
            self._apply_project(chemin)

    def _charger_projet_auto(self):
        if os.path.exists(FICHIER_PROJET):
            self._apply_project(FICHIER_PROJET, silent=True)

    def _apply_project(self, chemin, silent=False):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            if not silent:
                messagebox.showerror("Erreur", f"Impossible de charger le projet : {e}")
            return
        self.var_dossier.set(data.get("dossier", self.var_dossier.get()))
        self._creer_structure_dossier()
        if data.get("langue_source") in LABEL_VERS_CODE:
            self.var_src_lang.set(data["langue_source"])
        if data.get("langue_cible") in LABEL_VERS_CODE:
            self.var_tgt_lang.set(data["langue_cible"])
        self.var_threads.set(data.get("threads", 50))
        self.var_format.set(data.get("format", "pdf"))
        self.var_ignorer.set(data.get("ignorer", True))
        self.var_spell.set(data.get("spell", False))
        self.var_merge.set(data.get("merge", False))
        if "mode" in data and data["mode"] in ("extraire", "traduire", "traduire_offline", "traduire_nllb"):
            self.var_mode.set(data["mode"])
        if data.get("theme") in th.THEMES:
            self._changer_theme_to(data["theme"])
        for k, v in data.get("styles", {}).items():
            if k in self.style_vars:
                self.style_vars[k].set(v)
        if "font_style" in data:
            self.var_font_style.set(data["font_style"])
        if "font_color" in data:
            self.var_font_color.set(data["font_color"])
        if "page_size" in data:
            self.var_page_size.set(data["page_size"])
        if "proxies" in data:
            self.var_proxies.delete("1.0", "end")
            self.var_proxies.insert("1.0", data["proxies"])
        if "ortho_lang" in data:
            self.var_ortho_lang.set(data["ortho_lang"])
        if "merge_name" in data:
            self.var_merge_name.set(data["merge_name"])
        if not silent:
            self._append_log(f"Projet chargé : {chemin}")

    def _appliquer_donnees_profil(self, data: dict) -> None:
        """Applique les données d'un profil à l'interface (sans fichier)."""
        self.var_dossier.set(data.get("dossier", self.var_dossier.get()))
        self._creer_structure_dossier()
        if data.get("langue_source") in LABEL_VERS_CODE:
            self.var_src_lang.set(data["langue_source"])
        if data.get("langue_cible") in LABEL_VERS_CODE:
            self.var_tgt_lang.set(data["langue_cible"])
        self.var_threads.set(data.get("threads", 50))
        self.var_format.set(data.get("format", "pdf"))
        self.var_ignorer.set(data.get("ignorer", True))
        self.var_spell.set(data.get("spell", False))
        self.var_merge.set(data.get("merge", False))
        if "mode" in data and data["mode"] in ("extraire", "traduire", "traduire_offline", "traduire_nllb"):
            self.var_mode.set(data["mode"])
        if data.get("theme") in th.THEMES:
            self._changer_theme_to(data["theme"])
        for k, v in data.get("styles", {}).items():
            if k in self.style_vars:
                self.style_vars[k].set(v)
        if "font_style" in data:
            self.var_font_style.set(data["font_style"])
        if "font_color" in data:
            self.var_font_color.set(data["font_color"])
        if "page_size" in data:
            self.var_page_size.set(data["page_size"])
        if "proxies" in data:
            self.var_proxies.delete("1.0", "end")
            self.var_proxies.insert("1.0", data["proxies"])
        if "ortho_lang" in data:
            self.var_ortho_lang.set(data["ortho_lang"])
        if "merge_name" in data:
            self.var_merge_name.set(data["merge_name"])
        self._append_log(f"Profil appliqué")

    def _export_project_data(self):
        return {
            "dossier": self.var_dossier.get(),
            "langue_source": self.var_src_lang.get(),
            "langue_cible": self.var_tgt_lang.get(),
            "threads": self.var_threads.get(),
            "format": self.var_format.get(),
            "ignorer": self.var_ignorer.get(),
            "mode": self.var_mode.get(),
            "spell": self.var_spell.get(),
            "merge": self.var_merge.get(),
            "theme": self.current_theme_name,
            "styles": {k: v.get() for k, v in self.style_vars.items()},
            "font_style": self.var_font_style.get(),
            "font_color": self.var_font_color.get(),
            "page_size": self.var_page_size.get(),
            "proxies": self.var_proxies.get("1.0", "end-1c"),
            "ortho_lang": self.var_ortho_lang.get(),
            "merge_name": self.var_merge_name.get(),
        }

    # ── PROFILS (Feature 5) ──
    def _rafraichir_liste_profils(self) -> None:
        """Met à jour la liste déroulante des profils."""
        noms = lister_profils()
        self.combo_profil["values"] = noms

    def _sauvegarder_comme_profil(self) -> None:
        """Sauvegarde la configuration actuelle comme profil nommé."""
        from tkinter import simpledialog
        nom = simpledialog.askstring("Nouveau profil", "Nom du profil :",
                                      parent=self.root)
        if nom and nom.strip():
            data = self._export_project_data()
            sauvegarder_profil(nom.strip(), data)
            self._rafraichir_liste_profils()
            self.var_profil.set(nom.strip())
            self._append_log(f"Profil sauvegardé : {nom.strip()}")

    def _supprimer_profil_courant(self) -> None:
        """Supprime le profil sélectionné."""
        nom = self.var_profil.get()
        if nom and supprimer_profil(nom):
            self.var_profil.set("")
            self._rafraichir_liste_profils()
            self._append_log(f"Profil supprimé : {nom}")

    def _charger_profil_depuis_combo(self, event=None) -> None:
        """Charge le profil sélectionné dans la combo."""
        nom = self.var_profil.get()
        if nom:
            data = charger_profil(nom)
            if data:
                self._appliquer_donnees_profil(data)
                self._append_log(f"Profil chargé : {nom}")

    # ── THÈME ──
    def _changer_theme(self, event=None):
        self._changer_theme_to(self.var_theme.get())

    def _changer_theme_to(self, name):
        if name in th.THEMES:
            self.current_theme_name = name
            self._theme = th.get(name)
            self._apply_theme()

    # ── MOTEUR ──
    def _config_moteur(self):
        selected = self._get_selected_pdfs()
        proxies_txt = self.var_proxies.get("1.0", "end-1c").strip()
        proxy_list = []
        if proxies_txt:
            proxy_list = [{"http": p.strip(), "https": p.strip()}
                          for p in proxies_txt.split("\n") if p.strip()]
        styles = {k: float(v.get()) if v.get().replace(".", "").replace("-", "").isdigit() else v.get()
                  for k, v in self.style_vars.items()}
        styles["font_name"] = self.var_font_style.get()
        styles["font_color"] = self.var_font_color.get()
        styles["page_size"] = self.var_page_size.get()
        merge_output = self.var_merge_name.get() if self.var_merge.get() else ""
        dossier = self.var_dossier.get()
        selected = self._get_selected_pdfs()
        mode = self.var_mode.get()
        threads = max(1, int(self.var_threads.get()))
        if mode == "traduire_nllb":
            # NLLB utilise déjà tous les cœurs à l'intérieur d'une inférence :
            # un seul worker évite la sur-souscription CPU/RAM.
            threads = 1
        return {
            "DOSSIER_SOURCE": os.path.join(dossier, "pdfs_originaux"),
            "DOSSIER_SORTIE": os.path.join(dossier, "pdfs_traduits"),
            "DOSSIER_CHECKPOINTS": os.path.join(dossier, "checkpoints"),
            "DOSSIER_CACHE_EXTRACTION": os.path.join(dossier, "extraction_cache"),
            "LANGUE_SOURCE": LABEL_VERS_CODE.get(self.var_src_lang.get(), "en"),
            "LANGUE_CIBLE": LABEL_VERS_CODE.get(self.var_tgt_lang.get(), "fr"),
            "NB_THREADS_TRAD": threads,
            "RATE_LIMIT": max(1, threads),
            "IGNORER_DEJA_TRADUITS": bool(self.var_ignorer.get()),
            "MODE_OFFLINE": mode == "traduire_offline",
            "MODE_NLLB": mode == "traduire_nllb",
            "FORMAT_EXPORT": self.var_format.get(),
            "STYLES_PDF": styles,
            "CORRECTION_ORTHO": bool(self.var_spell.get()),
            "LANGUE_ORTHO": self.var_ortho_lang.get(),
            "PROXIES": proxy_list,
            "MERGE_ENABLED": bool(self.var_merge.get()),
            "MERGE_OUTPUT": merge_output,
            "FICHIERS_SELECTION": selected,
        }

    def _demarrer(self):
        if self.worker and self.worker.is_alive():
            return
        selected = self._get_selected_pdfs()
        if not selected:
            messagebox.showwarning("Aucun fichier", "Sélectionnez au moins un fichier PDF.")
            return
        src = self.var_dossier.get()
        if not os.path.isdir(src):
            messagebox.showerror("Dossier introuvable", f"Dossier introuvable :\n{src}")
            return

        mode = self.var_mode.get()
        config = self._config_moteur()
        self._clear_log()
        self.pb["value"] = 0
        self.lbl_pct.config(text="0%")
        self._set_start_enabled(False)
        self._set_stop_enabled(True)
        self._session_start = time.time()

        moteur.ANNULER = False
        moteur.HORS_LIGNE = False

        status_map = {
            "extraire": "Extraction en cours...",
            "traduire": "Traduction en ligne en cours...",
            "traduire_offline": "Traduction hors ligne en cours...",
            "traduire_nllb": "Traduction hors ligne (NLLB) en cours...",
        }
        self._set_status(status_map.get(mode, "Traitement en cours..."))
        cible = moteur.extraire_seulement if mode == "extraire" else moteur.lancer

        def travail():
            try:
                cible(config,
                      on_progress=lambda frac, msg="": self.queue.put(("p", frac, msg)),
                      on_log=lambda m: self.queue.put(("l", m)))
                duree = time.time() - self._session_start
                if mode != "extraire":
                    stats.enregistrer_session(
                        duration=duree,
                        fichiers=len(selected),
                        pages=int(self.pb["value"] or 0),
                        source=config.get("LANGUE_SOURCE", "?"),
                        cible=config.get("LANGUE_CIBLE", "?"),
                        statut="terminé" if not moteur.ANNULER and not moteur.HORS_LIGNE else "interrompu",
                        format_export=config.get("FORMAT_EXPORT", "pdf"),
                        cache_hit=moteur.blocs_caches,
                        fallback_en=moteur.blocs_echoues,
                        pages_par_seconde=0,
                    )
                self.queue.put(("d", "ok" if not moteur.ANNULER else "cancel", mode))
            except Exception as e:
                self.queue.put(("l", f"Erreur : {e}"))
                self.queue.put(("l", traceback.format_exc()))
                self.queue.put(("d", "error", mode))

        self.worker = threading.Thread(target=travail, daemon=True)
        self.worker.start()

    def _arreter(self):
        moteur.ANNULER = True
        self._set_status("Arrêt en cours...")

    # ── FILE ──
    def _pomper_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "l":
                    self._append_log(item[1])
                elif kind == "p":
                    frac, msg = item[1], item[2]
                    self.pb["value"] = max(0, min(100, int(frac * 100)))
                    self.lbl_pct.config(text=f"{int(frac*100)}%")
                    # Détection de la phase (Feature 6)
                    phase = self._detecter_phase(msg)
                    if phase:
                        self.lbl_phase.config(text=phase)
                    if msg:
                        self._set_status(msg)
                        self._maj_eta(msg)
                elif kind == "d":
                    self._on_done(item[1], item[2])
                elif kind == "elog":
                    self._epub_log_msg(item[1])
                elif kind == "edone":
                    self._epub_afficher(item[1])
                elif kind == "efile":
                    self._epub_termine(item[1])
                elif kind == "eerr":
                    self._epub_echec(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._pomper_queue)

    def _maj_eta(self, msg: str):
        """Extrait le débit et l'ETA du message moteur pour l'afficher à part."""
        correspondance = re.search(r"\|\s*([\d.]+ p/min)\s*\|\s*ETA\s+(\S+)", msg)
        if correspondance:
            self.lbl_eta.config(
                text=f"{correspondance.group(1)} · reste {correspondance.group(2)}"
            )

    def _notifier(self, titre: str, corps: str, urgence: str = "normal"):
        """Envoie une notification de bureau (silencieux si indisponible)."""
        if not shutil.which("notify-send"):
            return
        icone = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "icons", "traducteur-pdf-64.png")
        commande = ["notify-send", "-u", urgence, "-a", APP_NAME]
        if os.path.exists(icone):
            commande += ["-i", icone]
        commande += [titre, corps]
        try:
            subprocess.Popen(commande, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def _setup_raccourcis(self):
        """Raccourcis clavier globaux."""
        raccourcis = {
            "<F5>": lambda e: self._demarrer(),
            "<Escape>": lambda e: self._arreter(),
            "<Control-s>": lambda e: self._sauvegarder_projet(),
            "<Control-o>": lambda e: self._charger_projet(),
            "<Control-r>": lambda e: self._refresh_pdf_list(),
            "<Control-l>": lambda e: self._clear_log(),
            "<Control-a>": lambda e: self._select_all(),
            "<Control-d>": lambda e: self._deselect_all(),
        }
        for touche, action in raccourcis.items():
            self.root.bind_all(touche, lambda e, a=action: (a(e), "break")[1])

    def _detecter_phase(self, msg: str) -> str:
        """Extrait la phase du message de progression."""
        if not msg:
            return ""
        msg_lower = msg.lower()
        if "extraction" in msg_lower or "extrait" in msg_lower:
            return "EXTRACTION"
        elif "traduit" in msg_lower or "traduction" in msg_lower or "page" in msg_lower:
            return "TRADUCTION"
        elif "génération" in msg_lower or "generation" in msg_lower or "export" in msg_lower or "fusion" in msg_lower:
            return "EXPORT"
        elif "arrêt" in msg_lower or "stop" in msg_lower or "interrompu" in msg_lower:
            return "ARRET"
        elif "terminé" in msg_lower or "termine" in msg_lower:
            return "TERMINE"
        return ""

    def _on_done(self, etat, mode):
        self._set_start_enabled(True)
        self._set_stop_enabled(False)
        self.lbl_eta.config(text="")
        duree = time.time() - self._session_start if self._session_start else 0
        resume = f"Durée : {duree/60:.1f} min" if duree else ""

        if moteur.HORS_LIGNE:
            self._set_status("Arrêté : connexion perdue.")
            self._notifier("Traduction interrompue",
                           "Connexion Internet perdue.", "critical")
        elif moteur.ANNULER:
            self._set_status("Interrompu.")
            self._notifier("Traduction interrompue", resume or "Arrêt demandé.")
        elif etat == "error":
            self._set_status("Erreur survenue (voir le journal).")
            self._notifier("Erreur de traduction",
                           "Consultez le journal pour le détail.", "critical")
        elif mode == "extraire":
            self.pb["value"] = 100
            self.lbl_pct.config(text="100%")
            self._set_status("Extraction terminée.")
            self._notifier("Extraction terminée", resume)
        else:
            self.pb["value"] = 100
            self.lbl_pct.config(text="100%")
            self._set_status("Terminé ! PDF générés.")
            self._refresh_dashboard()
            self._refresh_history()
            echecs = getattr(moteur, "blocs_echoues", 0)
            details = resume
            if echecs:
                details += f" — {echecs} bloc(s) en échec"
            self._notifier("Traduction terminée", details or "Documents générés.")
        self._append_log("Terminé.")

    # ── JOURNAL ──
    NIVEAUX_LOG = {
        "Succès": "succes",
        "Avertissement": "avert",
        "Erreur": "erreur",
    }

    def _configurer_tags_log(self):
        """Associe une couleur à chaque niveau de message du journal."""
        T = self._theme
        self.log.tag_configure("erreur", foreground=T["red"])
        self.log.tag_configure("avert", foreground=T.get("yellow", T["orange"]))
        self.log.tag_configure("succes", foreground=T["green"])
        self.log.tag_configure("info", foreground=T["fg"])

    def _niveau_log(self, ligne: str) -> str:
        """Déduit le niveau d'un message à partir de son contenu."""
        bas = ligne.lower()
        if "❌" in ligne or "erreur" in bas or "échec" in bas or "impossible" in bas:
            return "erreur"
        if "⚠️" in ligne or "avertissement" in bas or "ignoré" in bas or "annulé" in bas:
            return "avert"
        if "✅" in ligne or "terminé" in bas or "succès" in bas or "installé" in bas:
            return "succes"
        return "info"

    def _filter_log(self):
        query = self.var_log_search.get().lower()
        niveau_choisi = self.NIVEAUX_LOG.get(
            getattr(self, "var_log_niveau", None) and self.var_log_niveau.get() or "Tout"
        )
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        for ligne in self._full_log.split("\n"):
            if not ligne:
                continue
            if query and query not in ligne.lower():
                continue
            niveau = self._niveau_log(ligne)
            if niveau_choisi and niveau != niveau_choisi:
                continue
            self.log.insert("end", ligne + "\n", niveau)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _append_log(self, msg):
        self._full_log += msg + "\n"
        ligne = msg.rstrip()
        niveau = self._niveau_log(ligne)
        niveau_choisi = self.NIVEAUX_LOG.get(
            getattr(self, "var_log_niveau", None) and self.var_log_niveau.get() or "Tout"
        )
        if niveau_choisi and niveau != niveau_choisi:
            return
        query = self.var_log_search.get().lower() if hasattr(self, "var_log_search") else ""
        if query and query not in ligne.lower():
            return
        self.log.configure(state="normal")
        self.log.insert("end", ligne + "\n", niveau)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self._full_log = ""
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _exporter_log(self):
        """Enregistre le journal complet dans un fichier texte."""
        if not self._full_log.strip():
            messagebox.showinfo("Journal", "Le journal est vide.")
            return
        horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin = filedialog.asksaveasfilename(
            defaultextension=".log", initialfile=f"traducteur_{horodatage}.log",
            filetypes=[("Journal", "*.log"), ("Texte", "*.txt")])
        if not chemin:
            return
        try:
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(self._full_log)
        except OSError as e:
            messagebox.showerror("Journal", f"Écriture impossible : {e}")
            return
        self._append_log(f"Journal exporté : {chemin}")

    def _set_status(self, txt):
        self.lbl_status.config(text=txt)

    def _set_start_enabled(self, on):
        T = self._theme
        s, bg, fg = ("normal", T["green"], "#FFFFFF") if on else ("disabled", T["card2"], T["muted"])
        self.btn_start.config(state=s, bg=bg, fg=fg, cursor="hand2" if on else "arrow")

    def _set_stop_enabled(self, on):
        T = self._theme
        s, bg, fg = ("normal", T["red"], "#FFFFFF") if on else ("disabled", T["card2"], T["muted"])
        self.btn_stop.config(state=s, bg=bg, fg=fg, cursor="hand2" if on else "arrow")

    def _actualiser_statut_offline(self):
        """Met à jour le label de statut Argos/NLLB (hors ligne)."""
        T = self._theme
        if self.var_mode.get() == "traduire_nllb":
            try:
                from moteur.nllb import nllb_disponible, modele_nllb_installe
                if not nllb_disponible():
                    self.lbl_argos_status.config(
                        text="⚠️ NLLB non installé (pip install ctranslate2 sentencepiece)",
                        fg=T.get("red", "#E06C75"))
                elif modele_nllb_installe():
                    self.lbl_argos_status.config(
                        text="✓ Modèle NLLB-200 prêt (hors ligne)",
                        fg=T.get("green", "#98C379"))
                else:
                    self.lbl_argos_status.config(
                        text="Modèle NLLB introuvable (models/nllb-200-distilled-600M-int8)",
                        fg=T.get("orange", "#D19A66"))
            except Exception:
                pass
        elif not argos_disponible():
            self.lbl_argos_status.config(
                text="⚠️ Argos non installé (pip install argostranslate)",
                fg=T.get("red", "#E06C75"))
        elif self.var_mode.get() == "traduire_offline":
            src = LABEL_VERS_CODE.get(self.var_src_lang.get(), "en")
            dst = LABEL_VERS_CODE.get(self.var_tgt_lang.get(), "fr")
            if modele_offline_installe(src, dst):
                self.lbl_argos_status.config(
                    text=f"✓ Modèle {src}→{dst} installé — prêt (hors ligne)",
                    fg=T.get("green", "#98C379"))
            else:
                self.lbl_argos_status.config(
                    text=f"Modèle {src}→{dst} non installé — besoin Internet pour 1er téléchargement",
                    fg=T.get("orange", "#D19A66"))
        else:
            self.lbl_argos_status.config(text="", fg=T["muted"])

        # Re-vérifier périodiquement
        self.root.after(5000, self._actualiser_statut_offline)

    def _on_close(self):
        if (self.worker and self.worker.is_alive()) or self._epub_busy:
            if not messagebox.askokcancel("Quitter", "Une tâche est en cours. Quitter quand même ?"):
                return
            moteur.ANNULER = True
        try:
            data = self._export_project_data()
            with open(FICHIER_PROJET, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
        self.root.destroy()


def main():
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
