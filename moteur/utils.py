#!/usr/bin/env python3
"""
Utilitaires : journalisation, tri naturel, polices, checkpoints.
"""

from __future__ import annotations

import os
import sys
import json
import re
import time
import hashlib
from typing import Optional, Callable

from . import config as cfg

CHECKPOINT_VERSION = 2


# ─────────────────────────────────────────────
#   JOURNALISATION
# ─────────────────────────────────────────────

def log_dynamique(msg: str) -> None:
    """Message de progression (écrasé à chaque appel)."""
    global cfg
    with cfg.print_lock:
        cfg._current_progress = msg
        sys.stdout.write(f"\r\033[K{msg}")
        sys.stdout.flush()


def log_fixe(msg: str) -> None:
    """Message permanent (avec retour à la ligne)."""
    with cfg.print_lock:
        sys.stdout.write(f"\r\033[K{msg}\n")
        sys.stdout.flush()
    if cfg.LOG_CALLBACK:
        try:
            cfg.LOG_CALLBACK(msg)
        except Exception:
            pass


# ─────────────────────────────────────────────
#   TRI NATUREL
# ─────────────────────────────────────────────

def tri_naturel(nom: str) -> list:
    """Tri alphabétique tenant compte des nombres (fichier2 < fichier10)."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', nom)]


# ─────────────────────────────────────────────
#   POLICES
# ─────────────────────────────────────────────

def charger_police() -> tuple[str, str]:
    """Charge la police DejaVu Sans (fallback Helvetica)."""
    chemins = [
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for chemin in chemins:
        if os.path.exists(chemin):
            bold = chemin.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                pdfmetrics.registerFont(TTFont("UniFont", chemin))
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont("UniFont-Bold", bold))
                else:
                    pdfmetrics.registerFont(TTFont("UniFont-Bold", chemin))
                return "UniFont", "UniFont-Bold"
            except Exception:
                pass
    return "Helvetica", "Helvetica-Bold"


# ─────────────────────────────────────────────
#   CHECKPOINTS
# ─────────────────────────────────────────────

def chemin_checkpoint(nom_fichier: str) -> str:
    """Retourne le chemin du fichier checkpoint pour un fichier donné."""
    conf = cfg.get_config()
    cp = os.path.join(conf.dossier_checkpoints, nom_fichier + ".json")
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    return cp


def hash_texte(texte: str) -> str:
    """Empreinte courte d'un texte, utilisée pour détecter un non-changement."""
    return hashlib.sha1((texte or "").strip().encode("utf-8")).hexdigest()[:16]


def charger_checkpoint(nom_fichier: str) -> tuple[dict, int]:
    """Charge l'état de traduction sauvegardé pour un fichier."""
    cp = chemin_checkpoint(nom_fichier)
    if os.path.exists(cp):
        try:
            with open(cp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}, 0
        return data.get("pages_traduites", {}), data.get("total_pages", 0)
    return {}, 0


def charger_metadonnees_checkpoint(nom_fichier: str) -> dict:
    """Charge les métadonnées d'un checkpoint (version, langue vérifiée, hashes)."""
    cp = chemin_checkpoint(nom_fichier)
    if not os.path.exists(cp):
        return {}
    try:
        with open(cp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        "version": data.get("version", 1),
        "langue_verifiee": data.get("langue_verifiee", False),
        "langue_cible": data.get("langue_cible", ""),
        "hash_original": data.get("hash_original", {}),
        "maj": data.get("maj", 0),
    }


def sauvegarder_checkpoint(
    nom_fichier: str,
    pages_traduites: dict,
    total_pages: int,
    hash_original: Optional[dict] = None,
    langue_verifiee: bool = False,
) -> None:
    """Sauvegarde l'état de traduction pour reprise d'interruption.

    Les métadonnées ``hash_original`` et ``langue_verifiee`` permettent
    de détecter un checkpoint corrompu (pages restées dans la langue source)
    avant tout export.
    """
    conf = cfg.get_config()
    with cfg.checkpoint_lock:
        cp = chemin_checkpoint(nom_fichier)
        tmp = cp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": CHECKPOINT_VERSION,
                    "pages_traduites": pages_traduites,
                    "total_pages": total_pages,
                    "hash_original": hash_original or {},
                    "langue_verifiee": langue_verifiee,
                    "langue_cible": conf.langue_cible,
                    "maj": time.time(),
                },
                f, ensure_ascii=False
            )
        os.replace(tmp, cp)


def supprimer_checkpoint(nom_fichier: str) -> None:
    """Supprime le checkpoint d'un fichier terminé."""
    with cfg.checkpoint_lock:
        cp = chemin_checkpoint(nom_fichier)
        if os.path.exists(cp):
            os.remove(cp)
