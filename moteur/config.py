#!/usr/bin/env python3
"""
Configuration et état global du moteur de traduction.
Contient ConfigMoteur (dataclass validée) + variables d'état partagées.
"""

from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import random
import socket
import re
import threading
import logging
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

logging.getLogger("pdfminer").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
#   DATACLASS DE CONFIGURATION (type-safe)
# ─────────────────────────────────────────────

STYLES_PDF_PAR_DEFAUT: dict[str, Any] = {
    "font_name": "DejaVu Sans",
    "font_size": 11,
    "font_color": "#222222",
    "line_spacing": 17,
    "chapter_font_size": 13,
    "chapter_color": "#222222",
    "margin_top": 2.5,
    "margin_bottom": 2.5,
    "margin_left": 2.5,
    "margin_right": 2.5,
    "page_size": "A4",
    "header_text": "",
    "footer_text": "",
}

FORMATS_EXPORT_VALIDES = ("pdf", "txt", "md", "docx")


@dataclass
class ConfigMoteur:
    """Configuration complète du moteur de traduction, avec validation."""

    # Chemins
    dossier_source: str = "./pdfs_originaux"
    dossier_sortie: str = "./pdfs_traduits"
    dossier_checkpoints: str = "./checkpoints"
    dossier_cache_extraction: str = "./extraction_cache"
    chemin_cache_trad: str = "./translation_cache.db"

    # Langues
    langue_source: str = "en"
    langue_cible: str = "fr"

    # Performance
    taille_bloc: int = 4800
    nb_threads_trad: int = 50
    nb_threads_pdf: int = 5
    rate_limit: int = 50
    max_retries: int = 5
    backoff_cap: int = 30
    pace_min: float = 0.05
    pace_max: float = 0.15

    # Fonctionnalités
    ignorer_deja_traduits: bool = True
    mode_offline: bool = False
    format_export: str = "pdf"
    preserver_images: bool = False
    correction_ortho: bool = False
    langue_ortho: str = "fr"
    merge_enabled: bool = False
    merge_output: str = ""

    # Proxies
    proxies: list[dict[str, str]] = field(default_factory=list)

    # Styles PDF
    styles_pdf: dict[str, Any] = field(default_factory=lambda: dict(STYLES_PDF_PAR_DEFAUT))

    # Sélection de fichiers
    fichiers_selection: Optional[list[str]] = None

    def __post_init__(self) -> None:
        """Valide la configuration après initialisation."""
        assert self.nb_threads_trad > 0, "nb_threads_trad doit être > 0"
        assert self.nb_threads_pdf > 0, "nb_threads_pdf doit être > 0"
        assert self.taille_bloc > 0, "taille_bloc doit être > 0"
        assert self.rate_limit > 0, "rate_limit doit être > 0"
        assert self.format_export in FORMATS_EXPORT_VALIDES, \
            f"format_export doit être l'un de {FORMATS_EXPORT_VALIDES}"
        assert len(self.langue_source) >= 2, "langue_source invalide"
        assert len(self.langue_cible) >= 2, "langue_cible invalide"

    def appliquer_dict(self, d: Optional[dict[str, Any]]) -> None:
        """Applique les valeurs d'un dict (clés en MAJUSCULES ou minuscules)."""
        if not d:
            return
        for cle, valeur in d.items():
            if valeur is None:
                continue
            # Cherche d'abord la clé telle quelle, puis en minuscules
            if hasattr(self, cle):
                setattr(self, cle, valeur)
            elif hasattr(self, cle.lower()):
                setattr(self, cle.lower(), valeur)

    def exporter_dict(self) -> dict[str, Any]:
        """Exporte la config en dict (clés MAJUSCULES pour rétrocompatibilité)."""
        mapping = {
            "DOSSIER_SOURCE": self.dossier_source,
            "DOSSIER_SORTIE": self.dossier_sortie,
            "DOSSIER_CHECKPOINTS": self.dossier_checkpoints,
            "DOSSIER_CACHE_EXTRACTION": self.dossier_cache_extraction,
            "CHEMIN_CACHE_TRAD": self.chemin_cache_trad,
            "LANGUE_SOURCE": self.langue_source,
            "LANGUE_CIBLE": self.langue_cible,
            "TAILLE_BLOC": self.taille_bloc,
            "NB_THREADS_TRAD": self.nb_threads_trad,
            "NB_THREADS_PDF": self.nb_threads_pdf,
            "RATE_LIMIT": self.rate_limit,
            "MAX_RETRIES": self.max_retries,
            "BACKOFF_CAP": self.backoff_cap,
            "PACE_MIN": self.pace_min,
            "PACE_MAX": self.pace_max,
            "IGNORER_DEJA_TRADUITS": self.ignorer_deja_traduits,
            "MODE_OFFLINE": self.mode_offline,
            "FORMAT_EXPORT": self.format_export,
            "PRESERVER_IMAGES": self.preserver_images,
            "CORRECTION_ORTHO": self.correction_ortho,
            "LANGUE_ORTHO": self.langue_ortho,
            "MERGE_ENABLED": self.merge_enabled,
            "MERGE_OUTPUT": self.merge_output,
            "PROXIES": self.proxies,
            "STYLES_PDF": self.styles_pdf,
            "FICHIERS_SELECTION": self.fichiers_selection,
        }
        return mapping


# ─────────────────────────────────────────────
#   ÉTAT GLOBAL PARTAGÉ (runtime)
# ─────────────────────────────────────────────

_config_courante: ConfigMoteur = ConfigMoteur()

# Threading / Lock
print_lock = threading.Lock()
checkpoint_lock = threading.Lock()
data_lock = threading.Lock()
progress_lock = threading.Lock()
cache_lock = threading.Lock()
proxy_lock = threading.Lock()
ortho_lock = threading.Lock()

# État du pipeline
ANNULER: bool = False
HORS_LIGNE: bool = False
extraction_terminee: bool = False
total_done: int = 0
total_tasks: int = 0
futures_pdf: list[Any] = []
executor_pdf: Optional[ThreadPoolExecutor] = None
_current_progress: str = ""

# Compteurs stats
blocs_echoues: int = 0
blocs_caches: int = 0

# Callbacks GUI
PROGRESS_CALLBACK: Optional[Callable[[float, str], None]] = None
LOG_CALLBACK: Optional[Callable[[str], None]] = None

# Cache DB
cache_conn: Any = None

# Proxy rotation
proxy_index: int = 0

# Correction orthographique
ortho_tool: Any = None

# Modèle offline (Argos)
modele_offline_init: bool = False


def configurer(config_dict: Optional[dict[str, Any]] = None) -> None:
    """API publique : réinitialise et configure le moteur (rétrocompatible)."""
    global ANNULER, HORS_LIGNE, blocs_echoues, blocs_caches, \
           proxy_index, cache_conn, ortho_tool, modele_offline_init, _config_courante

    cfg = ConfigMoteur()
    cfg.appliquer_dict(config_dict)
    _config_courante = cfg

    # Réinitialiser l'état
    from threading import Semaphore
    globals()["ANNULER"] = False
    globals()["HORS_LIGNE"] = False
    blocs_echoues = 0
    blocs_caches = 0
    proxy_index = 0
    cache_conn = None
    ortho_tool = None
    modele_offline_init = False

    # Re-créer le rate limiter via Semaphore (nécessaire car RATE_LIMIT a pu changer)
    globals()["_rate_limiter"] = Semaphore(cfg.rate_limit)


# Initialisation silencieuse du rate limiter
from threading import Semaphore
_rate_limiter = Semaphore(50)


def get_config() -> ConfigMoteur:
    """Retourne la configuration courante."""
    return _config_courante
