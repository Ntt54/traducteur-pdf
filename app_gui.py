#!/usr/bin/env python3
"""
=============================================================
  TRADUCTEUR PDF v8 — INTERFACE MODERNE
  Design professionnel, navigation par onglets,
  prévisualisation, statistiques, configuration avancée.
=============================================================
"""

import os, sys, queue, threading, json, re, time, datetime, hashlib, subprocess, shutil, urllib.parse, glob
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinter import font as tkfont
from pathlib import Path

import traduire_pdfs_v2 as moteur
from moteur.editeur import sauvegarder_edits, charger_edits
from moteur.profils import lister_profils, sauvegarder_profil, charger_profil, supprimer_profil
from moteur.traducteur import argos_disponible, modele_offline_installe, init_modele_offline
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
        root.geometry("1140x860")
        root.minsize(920, 720)

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

    # ── INIT STYLES ──
    def _init_styles(self):
        self.f_title = tkfont.Font(family="DejaVu Sans", size=17, weight="bold")
        self.f_sub = tkfont.Font(family="DejaVu Sans", size=10)
        self.f_lbl = tkfont.Font(family="DejaVu Sans", size=10, weight="bold")
        self.f_btn = tkfont.Font(family="DejaVu Sans", size=10, weight="bold")
        self.f_mono = tkfont.Font(family="DejaVu Sans Mono", size=9)
        self.f_small = tkfont.Font(family="DejaVu Sans", size=9)
        self.f_tab = tkfont.Font(family="DejaVu Sans", size=10)
        self.f_big = tkfont.Font(family="DejaVu Sans", size=24, weight="bold")

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
        style.configure("TLabelframe.Label", background=card, foreground=fg, font=self.f_lbl)

        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab",
                       background="#111111", foreground=muted,
                       padding=[18, 8], borderwidth=0,
                       font=self.f_tab)
        style.map("TNotebook.Tab",
                  background=[("selected", accent), ("active", card2)],
                  foreground=[("selected", "#FFFFFF"), ("active", fg)])

        for w in ["TCombobox", "TSpinbox"]:
            style.configure(w, fieldbackground=card2, background=card, foreground=fg,
                           arrowcolor=fg, bordercolor=card2, padding=3, selectbackground=card)
        style.configure("TEntry", fieldbackground=card2, foreground=fg,
                       bordercolor=card2, padding=3)
        style.configure("TCheckbutton", background=bg, foreground=fg, font=self.f_sub)
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("TRadiobutton", background=bg, foreground=fg, font=self.f_sub)
        style.map("TRadiobutton", background=[("active", bg)])

        style.configure("Accent.Horizontal.TProgressbar",
                       troughcolor=card, background=accent,
                       bordercolor=card, lightcolor=accent, darkcolor=accent)

        style.configure("Treeview", background=card, foreground=fg, fieldbackground=card,
                       borderwidth=0, font=self.f_sub, rowheight=26)
        style.configure("Treeview.Heading", background=card2, foreground=fg,
                       font=self.f_lbl, borderwidth=0)
        style.map("Treeview", background=[("selected", accent)],
                 foreground=[("selected", "#FFFFFF")])
        if hasattr(self, "pdf_tree"):
            self.pdf_tree.tag_configure("folder", foreground=accent)
            self.pdf_tree.tag_configure("file", foreground=fg)

        style.configure("Card.TFrame", background=card)
        style.configure("Card2.TFrame", background=card2)
        style.configure("Orange.TFrame", background=accent)
        style.configure("Success.TLabel", foreground=T["green"], font=self.f_lbl)
        style.configure("Warning.TLabel", foreground=T["yellow"], font=self.f_lbl)
        style.configure("Error.TLabel", foreground=T["red"], font=self.f_lbl)

    # ── BOUTON ──
    def _btn(self, parent, text, cmd, bg=None, bg_hover=None, fg="#FFFFFF", width=None):
        T = self._theme
        bg = bg or T["accent"]
        bg_hover = bg_hover or T["accent_h"]
        b = tk.Button(parent, text=text, command=cmd, font=self.f_btn,
                      bg=bg, fg=fg, activebackground=bg_hover, activeforeground=fg,
                      relief="flat", bd=0, padx=18, pady=8, cursor="hand2",
                      highlightthickness=0, width=width)
        b.bind("<Enter>", lambda e, b=b, bg_hover=bg_hover: b.config(bg=bg_hover) if b["state"]=="normal" else None)
        b.bind("<Leave>", lambda e, b=b, bg=bg: b.config(bg=bg) if b["state"]=="normal" else None)
        b._bg, b._bg_hover = bg, bg_hover
        return b

    # ── CONSTRUCTION UI ──
    def _build_ui(self):
        T = self._theme
        p = {"padx": 16}

        # ── Barre d'en-tête ──
        header_outer = tk.Frame(self.root, bg=T["accent"], height=57)
        header_outer.pack(fill="x")
        header_outer.pack_propagate(False)

        header = tk.Frame(header_outer, bg=T["card"], height=56)
        header.pack(fill="both", expand=True)
        header.pack_propagate(False)

        h_inner = tk.Frame(header, bg=T["card"])
        h_inner.pack(fill="both", padx=20)

        tk.Label(h_inner, text="Traducteur PDF", font=self.f_title,
                bg=T["card"], fg=T["accent"]).pack(side="left", anchor="w")

        self.theme_sel_frame = tk.Frame(h_inner, bg=T["card"])
        self.theme_sel_frame.pack(side="right")
        tk.Label(self.theme_sel_frame, text="Thème", font=self.f_small,
                bg=T["card"], fg=T["muted"]).pack(side="left", padx=(0, 6))
        self.var_theme = tk.StringVar(value=self.current_theme_name)
        self.combo_theme = ttk.Combobox(self.theme_sel_frame, textvariable=self.var_theme,
                                        state="readonly", width=18, values=th.THEME_NAMES)
        self.combo_theme.pack(side="left")
        self.combo_theme.bind("<<ComboboxSelected>>", self._changer_theme)

        # ── Profils de configuration (Feature 5) ──
        profil_frame = tk.Frame(h_inner, bg=T["card"])
        profil_frame.pack(side="right", padx=(0, 16))
        tk.Label(profil_frame, text="Profil", font=self.f_small,
                bg=T["card"], fg=T["muted"]).pack(side="left", padx=(0, 4))
        self.var_profil = tk.StringVar()
        self.combo_profil = ttk.Combobox(profil_frame, textvariable=self.var_profil,
                                          state="readonly", width=16, values=[])
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
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(12, 0))

        self._build_tab_traduction()
        self._build_tab_preview()
        self._build_tab_dashboard()
        self._build_tab_history()
        self._build_tab_settings()

    # ── ONGLET 1 : TRADUCTION ──
    def _build_tab_traduction(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Traduction")
        pad = {"padx": 16, "pady": 10}

        # Ligne dossiers
        dir_card = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        dir_card.pack(fill="x", **pad)
        d_inner = tk.Frame(dir_card, bg=T["card"])
        d_inner.pack(fill="x", padx=14, pady=12)
        d_inner.columnconfigure(1, weight=1)

        self.var_dossier = tk.StringVar(value=os.path.abspath("."))
        self._dir_row(d_inner, 0, "Dossier de travail", self.var_dossier)

        tk.Label(d_inner,
                text="Source : pdfs_originaux/  \u2192  Sortie : pdfs_traduits/",
                font=self.f_small, bg=T["card"], fg=T["muted"]).grid(
                row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Sélection fichiers (gauche) + paramètres (droite)
        mid_frame = tk.Frame(tab, bg=T["bg"])
        mid_frame.pack(fill="both", expand=True, **pad)

        # Sélection fichiers
        sel_card = tk.Frame(mid_frame, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        sel_card.pack(side="left", fill="both", expand=True)

        sel_header = tk.Frame(sel_card, bg=T["card"])
        sel_header.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(sel_header, text="Sélection des PDF", font=self.f_lbl,
                bg=T["card"], fg=T["fg"]).pack(side="left")
        self.lbl_pdf_count = tk.Label(sel_header, text="0 fichier(s)", font=self.f_sub,
                                      bg=T["card"], fg=T["muted"])
        self.lbl_pdf_count.pack(side="right")

        self.btn_frame = tk.Frame(sel_card, bg=T["card"])
        self.btn_frame.pack(fill="x", padx=14, pady=(0, 6))
        self._btn(self.btn_frame, "Actualiser", self._refresh_pdf_list, T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 4))
        self._btn(self.btn_frame, "Tout", self._select_all, T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 4))
        self._btn(self.btn_frame, "Aucun", self._deselect_all, T["card2"], T["accent_h"], T["fg"]).pack(side="left", padx=(0, 4))
        self.btn_supprimer = self._btn(self.btn_frame, "Supprimer", self._supprimer_selection, T["red"], T["red_h"], "#FFFFFF")
        self.btn_supprimer.pack(side="left", padx=(0, 4))

        # Arbre dossiers/fichiers
        tree_container = tk.Frame(sel_card, bg=T["card"])
        tree_container.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        tree_toolbar = tk.Frame(tree_container, bg=T["card"])
        tree_toolbar.pack(fill="x", pady=(0, 4))
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
        params_card.pack(side="right", fill="both", padx=(10, 0))
        p_inner = tk.Frame(params_card, bg=T["card"])
        p_inner.pack(fill="both", padx=14, pady=12, expand=True)

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
        self.var_threads = tk.IntVar(value=50)
        ttk.Spinbox(tf, from_=1, to=200, textvariable=self.var_threads, width=5).pack(side="left", padx=(4, 14))
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

        # Statut Argos (hors ligne)
        self.lbl_argos_status = tk.Label(p_inner, text="", font=self.f_small,
                                         bg=T["card"], fg=T["muted"])
        self.lbl_argos_status.pack(anchor="w", padx=(16, 0), pady=(0, 2))
        self._actualiser_statut_offline()

        # Barre d'action
        action_bar = tk.Frame(tab, bg=T["bg"])
        action_bar.pack(fill="x", **pad)

        self.btn_start = self._btn(action_bar, "Démarrer", self._demarrer, T["green"], T["green_h"])
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = self._btn(action_bar, "Arrêter", self._arreter, T["red"], T["red_h"])
        self.btn_stop.pack(side="left")
        self._set_stop_enabled(False)

        # Progression
        prog_frame = tk.Frame(tab, bg=T["bg"])
        prog_frame.pack(fill="x", **pad)

        # Phase badge (Feature 6)
        self.lbl_phase = tk.Label(prog_frame, text="", font=self.f_small,
                                  bg=T["accent"], fg="#FFFFFF", padx=8, pady=2)
        self.lbl_phase.pack(side="left", padx=(0, 8))

        self.pb = ttk.Progressbar(prog_frame, style="Accent.Horizontal.TProgressbar",
                                  mode="determinate", maximum=100)
        self.pb.pack(fill="x", side="left", expand=True)
        self.lbl_pct = tk.Label(prog_frame, text="0%", font=self.f_lbl, bg=T["bg"], fg=T["accent"], width=5)
        self.lbl_pct.pack(side="left", padx=(8, 0))
        self.lbl_status = tk.Label(prog_frame, text="Prêt", font=self.f_sub,
                                  bg=T["bg"], fg=T["muted"], anchor="w")
        self.lbl_status.pack(fill="x", padx=(10, 0))

        # Journal avec recherche
        log_card = tk.Frame(tab, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
        log_card.pack(fill="both", expand=True, **pad)

        log_header = tk.Frame(log_card, bg=T["card"])
        log_header.pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(log_header, text="Journal", font=self.f_lbl, bg=T["card"], fg=T["fg"]).pack(side="left")
        tk.Label(log_header, text="Filtrer :", font=self.f_small, bg=T["card"], fg=T["muted"]).pack(side="left", padx=(16, 4))
        self.var_log_search = tk.StringVar()
        self.var_log_search.trace_add("write", lambda *a: self._filter_log())
        ttk.Entry(log_header, textvariable=self.var_log_search, width=22).pack(side="left")
        self._btn(log_header, "Effacer", self._clear_log, T["card2"], T["accent_h"], T["fg"]).pack(side="right")

        self.log = scrolledtext.ScrolledText(
            log_card, height=8, bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
            font=self.f_mono, relief="flat", bd=0, wrap="word",
            highlightthickness=1, highlightbackground=T["card2"])
        self.log.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        self.log.configure(state="disabled")

        self._refresh_pdf_list()

    # ── ONGLET 2 : APERÇU ──
    def _build_tab_preview(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Aperçu")

        top = tk.Frame(tab, bg=T["bg"])
        top.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(top, text="Fichier :", font=self.f_lbl, bg=T["bg"], fg=T["fg"]).pack(side="left")
        self.preview_file_var = tk.StringVar()
        self.preview_combo = ttk.Combobox(top, textvariable=self.preview_file_var,
                                          state="readonly", width=50)
        self.preview_combo.pack(side="left", padx=(8, 6))
        self.preview_combo.bind("<<ComboboxSelected>>", self._load_preview)
        self._btn(top, "Actualiser", self._refresh_preview_list, T["card2"], T["accent_h"], T["fg"]).pack(side="left")

        # Vue partagée
        panes = tk.Frame(tab, bg=T["bg"])
        panes.pack(fill="both", expand=True, padx=16, pady=(6, 16))

        for side_idx, (side, label_text) in enumerate([("left", "Texte original"), ("right", "Texte traduit (modifiable)")]):
            frame = tk.Frame(panes, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
            frame.pack(side=tk.LEFT if side=="left" else tk.RIGHT,
                      fill="both", expand=True,
                      padx=(0, 6) if side=="left" else (6, 0))
            tk.Label(frame, text=label_text, font=self.f_lbl,
                    bg=T["card"], fg=T["fg"]).pack(anchor="w", padx=10, pady=(8, 4))
            text_widget = scrolledtext.ScrolledText(
                frame, height=20, bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
                font=self.f_mono, relief="flat", bd=0, wrap="word",
                highlightthickness=1, highlightbackground=T["card2"])
            text_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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

    # ── ONGLET 3 : TABLEAU DE BORD ──
    def _build_tab_dashboard(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Tableau de bord")

        top = tk.Frame(tab, bg=T["bg"])
        top.pack(fill="x", padx=16, pady=(12, 6))
        self._btn(top, "Actualiser", self._refresh_dashboard, T["accent"], T["accent_h"]).pack(side="left")

        # Cartes statistiques
        sc = tk.Frame(tab, bg=T["bg"])
        sc.pack(fill="x", padx=16)
        self.stat_labels = {}
        stat_data = [
            ("sessions", "Sessions"),
            ("pages", "Total pages"),
            ("fichiers", "Total fichiers"),
            ("duree", "Temps total"),
        ]
        for i, (key, label) in enumerate(stat_data):
            card = tk.Frame(sc, bg=T["card"], bd=0, highlightthickness=1, highlightbackground=T["card2"])
            card.grid(row=0, column=i, sticky="nsew", padx=4, pady=4, ipady=10)
            sc.columnconfigure(i, weight=1)
            tk.Label(card, text=label, font=self.f_sub, bg=T["card"], fg=T["muted"]).pack()
            lbl_val = tk.Label(card, text="\u2014", font=self.f_big, bg=T["card"], fg=T["accent"])
            lbl_val.pack()
            lbl_val.pack()
            self.stat_labels[key] = lbl_val

        # Sessions récentes
        hist_frame = tk.LabelFrame(tab, text="Sessions récentes", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        hist_frame.pack(fill="both", expand=True, padx=16, pady=(8, 8))

        self.stats_tree = ttk.Treeview(hist_frame,
            columns=("date", "pages", "fichiers", "temps", "langues", "statut"),
            show="headings", height=6)
        cols = [("date", 170), ("pages", 60), ("fichiers", 65), ("temps", 70), ("langues", 80), ("statut", 100)]
        for col, w in cols:
            self.stats_tree.heading(col, text=col.capitalize())
            self.stats_tree.column(col, width=w)
        self.stats_tree.pack(fill="both", expand=True, padx=8, pady=8)

        # Activité hebdomadaire
        hebdo_frame = tk.LabelFrame(tab, text="Activité (14 jours)", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        hebdo_frame.pack(fill="x", padx=16, pady=(0, 16))

        self.hebdo_tree = ttk.Treeview(hebdo_frame,
            columns=("jour", "pages", "fichiers", "temps"),
            show="headings", height=4)
        for col, w in [("jour", 150), ("pages", 70), ("fichiers", 70), ("temps", 70)]:
            self.hebdo_tree.heading(col, text=col.capitalize())
            self.hebdo_tree.column(col, width=w)
        self.hebdo_tree.pack(fill="x", padx=8, pady=8)

    # ── ONGLET 4 : HISTORIQUE ──
    def _build_tab_history(self):
        T = self._theme
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Historique")

        top = tk.Frame(tab, bg=T["bg"])
        top.pack(fill="x", padx=16, pady=(12, 6))
        self._btn(top, "Actualiser", self._refresh_history, T["accent"], T["accent_h"]).pack(side="left")

        self.hist_tree = ttk.Treeview(tab,
            columns=("id", "date", "fichiers", "pages", "temps", "src", "dst", "statut", "format"),
            show="headings", height=24)
        cols = [("id", 35), ("date", 165), ("fichiers", 60), ("pages", 55), ("temps", 65),
                ("src", 50), ("dst", 50), ("statut", 95), ("format", 60)]
        for col, w in cols:
            self.hist_tree.heading(col, text=col.capitalize())
            self.hist_tree.column(col, width=w)
        self.hist_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))

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
        self._build_info_section(scrollable)

    # ── SOUS-SECTIONS CONFIGURATION ──
    def _build_pdf_styles(self, parent):
        T = self._theme
        frame = tk.LabelFrame(parent, text="Styles PDF", font=self.f_lbl,         bd=0, bg=T["card"], fg=T["accent"])
        frame.pack(fill="x", padx=16, pady=8)
        inner = tk.Frame(frame,         bd=0, bg=T["card"])
        inner.pack(fill="x", padx=10, pady=10)

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
            row=row, column=0, sticky="w", pady=3)
        e = ttk.Entry(parent, textvariable=var)
        e.grid(row=row, column=1, sticky="ew", padx=(8, 6), pady=3, ipady=2)
        btn_frame = tk.Frame(parent, bg=T["card"])
        btn_frame.grid(row=row, column=2, pady=3)
        b1 = tk.Button(btn_frame, text="Ouvrir", command=lambda: self._ouvrir_dossier(var),
                       bg=T["accent"], fg="#FFFFFF", activebackground=T["accent_h"],
                       relief="flat", bd=0, padx=12, pady=2, cursor="hand2",
                       font=self.f_sub, highlightthickness=0)
        b1.pack(side="left", padx=(0, 4))
        b2 = tk.Button(btn_frame, text="\u22EF", command=lambda: self._choisir_dossier(var),
                       bg=T["card2"], fg=T["fg"], activebackground=T["accent_h"],
                       relief="flat", bd=0, padx=8, pady=2, cursor="hand2",
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
        if filter_to is not None:
            self._filtered = set(filter_to)
            pdfs = [f for f in pdfs if f in self._filtered]
        else:
            self._filtered = None
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
            self.lbl_pdf_count.config(text=f"{n_folders} dossier(s) \u2022 {n_files} fichier(s)")
        else:
            self.lbl_pdf_count.config(text=f"{n_files} fichier(s)")

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
        for item in self.hebdo_tree.get_children():
            self.hebdo_tree.delete(item)
        hebdo = stats.get_stats_hebdomadaires()
        for row in reversed(hebdo):
            self.hebdo_tree.insert("", "end", values=(row[0], row[1], row[2], f"{row[3]:.0f}s"))

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
        if "mode" in data and data["mode"] in ("extraire", "traduire", "traduire_offline"):
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
        if "mode" in data and data["mode"] in ("extraire", "traduire", "traduire_offline"):
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
        return {
            "DOSSIER_SOURCE": os.path.join(dossier, "pdfs_originaux"),
            "DOSSIER_SORTIE": os.path.join(dossier, "pdfs_traduits"),
            "DOSSIER_CHECKPOINTS": os.path.join(dossier, "checkpoints"),
            "DOSSIER_CACHE_EXTRACTION": os.path.join(dossier, "extraction_cache"),
            "LANGUE_SOURCE": LABEL_VERS_CODE.get(self.var_src_lang.get(), "en"),
            "LANGUE_CIBLE": LABEL_VERS_CODE.get(self.var_tgt_lang.get(), "fr"),
            "NB_THREADS_TRAD": max(1, int(self.var_threads.get())),
            "RATE_LIMIT": max(1, int(self.var_threads.get())),
            "IGNORER_DEJA_TRADUITS": bool(self.var_ignorer.get()),
            "MODE_OFFLINE": mode == "traduire_offline",
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

        status_map = {
            "extraire": "Extraction en cours...",
            "traduire": "Traduction en ligne en cours...",
            "traduire_offline": "Traduction hors ligne en cours...",
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
                elif kind == "d":
                    self._on_done(item[1], item[2])
        except queue.Empty:
            pass
        self.root.after(100, self._pomper_queue)

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
        if moteur.HORS_LIGNE:
            self._set_status("Arrêté : connexion perdue.")
        elif moteur.ANNULER:
            self._set_status("Interrompu.")
        elif etat == "error":
            self._set_status("Erreur survenue (voir le journal).")
        elif mode == "extraire":
            self.pb["value"] = 100
            self.lbl_pct.config(text="100%")
            self._set_status("Extraction terminée.")
        else:
            self.pb["value"] = 100
            self.lbl_pct.config(text="100%")
            self._set_status("Terminé ! PDF générés.")
            self._refresh_dashboard()
            self._refresh_history()
        self._append_log("Terminé.")

    # ── JOURNAL ──
    def _filter_log(self):
        query = self.var_log_search.get().lower()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        if query:
            for line in self._full_log.split("\n"):
                if query in line.lower():
                    self.log.insert("end", line + "\n")
        else:
            self.log.insert("1.0", self._full_log)
        self.log.configure(state="disabled")

    def _append_log(self, msg):
        self._full_log += msg + "\n"
        self.log.configure(state="normal")
        self.log.insert("end", msg.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        # Ne pas re-filtrer après chaque ajout — le filtre s'applique
        # uniquement quand l'utilisateur tape dans le champ de recherche

    def _clear_log(self):
        self._full_log = ""
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

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
        """Met à jour le label de statut Argos (hors ligne)."""
        T = self._theme
        if not argos_disponible():
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
        if self.worker and self.worker.is_alive():
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
