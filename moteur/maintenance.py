#!/usr/bin/env python3
"""
Maintenance : inspection et nettoyage des caches, checkpoints et sorties.

Le pipeline accumule trois artefacts volumineux :
  - ``extraction_cache/``   : JSON du texte extrait de chaque PDF
  - ``translation_cache.db``: base SQLite des blocs déjà traduits
  - ``checkpoints/``        : état de reprise par fichier

Ce module fournit un inventaire chiffré et des opérations de purge sûres.
"""

from __future__ import annotations

import os
import json
import time
import shutil
import sqlite3
from typing import Optional, Callable

from . import config as cfg
from .utils import charger_metadonnees_checkpoint


# ─────────────────────────────────────────────
#   MESURES
# ─────────────────────────────────────────────

def formater_taille(octets: float) -> str:
    """Formate une taille en octets de façon lisible (Ko, Mo, Go)."""
    for unite in ("o", "Ko", "Mo", "Go"):
        if abs(octets) < 1024.0:
            return f"{octets:.1f} {unite}"
        octets /= 1024.0
    return f"{octets:.1f} To"


def taille_dossier(chemin: str) -> tuple[int, int]:
    """Retourne (taille totale en octets, nombre de fichiers) d'un dossier."""
    total = 0
    nb = 0
    if not os.path.isdir(chemin):
        return 0, 0
    for racine, _, fichiers in os.walk(chemin):
        for f in fichiers:
            try:
                total += os.path.getsize(os.path.join(racine, f))
                nb += 1
            except OSError:
                continue
    return total, nb


def inventaire() -> dict:
    """Retourne un inventaire complet des artefacts de travail."""
    conf = cfg.get_config()

    taille_ext, nb_ext = taille_dossier(conf.dossier_cache_extraction)
    taille_cp, nb_cp = taille_dossier(conf.dossier_checkpoints)
    taille_out, nb_out = taille_dossier(conf.dossier_sortie)

    taille_db = 0
    nb_entrees_db = 0
    if os.path.exists(conf.chemin_cache_trad):
        taille_db = os.path.getsize(conf.chemin_cache_trad)
        try:
            conn = sqlite3.connect(conf.chemin_cache_trad)
            nb_entrees_db = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            conn.close()
        except sqlite3.Error:
            nb_entrees_db = -1

    return {
        "extraction": {
            "chemin": conf.dossier_cache_extraction,
            "taille": taille_ext,
            "nb": nb_ext,
        },
        "checkpoints": {
            "chemin": conf.dossier_checkpoints,
            "taille": taille_cp,
            "nb": nb_cp,
        },
        "cache_traduction": {
            "chemin": conf.chemin_cache_trad,
            "taille": taille_db,
            "nb": nb_entrees_db,
        },
        "sortie": {
            "chemin": conf.dossier_sortie,
            "taille": taille_out,
            "nb": nb_out,
        },
    }


# ─────────────────────────────────────────────
#   PURGES
# ─────────────────────────────────────────────

def purger_cache_extraction(jours: Optional[int] = None) -> tuple[int, int]:
    """Supprime les JSON du cache d'extraction.

    Args:
        jours: si fourni, ne supprime que les fichiers plus vieux que N jours.

    Returns:
        (nombre de fichiers supprimés, octets libérés)
    """
    conf = cfg.get_config()
    dossier = conf.dossier_cache_extraction
    if not os.path.isdir(dossier):
        return 0, 0

    limite = time.time() - jours * 86400 if jours else None
    nb = 0
    octets = 0
    for racine, _, fichiers in os.walk(dossier):
        for f in fichiers:
            if not f.endswith(".json"):
                continue
            chemin = os.path.join(racine, f)
            try:
                if limite is not None and os.path.getmtime(chemin) >= limite:
                    continue
                taille = os.path.getsize(chemin)
                os.remove(chemin)
                nb += 1
                octets += taille
            except OSError:
                continue
    _supprimer_dossiers_vides(dossier)
    return nb, octets


def purger_checkpoints(seulement_orphelins: bool = True) -> tuple[int, int]:
    """Supprime les checkpoints.

    Args:
        seulement_orphelins: ne supprimer que les checkpoints dont le PDF
            source n'existe plus, ou dont le fichier de sortie existe déjà.

    Returns:
        (nombre supprimés, octets libérés)
    """
    conf = cfg.get_config()
    dossier = conf.dossier_checkpoints
    if not os.path.isdir(dossier):
        return 0, 0

    nb = 0
    octets = 0
    for racine, _, fichiers in os.walk(dossier):
        for f in fichiers:
            if not f.endswith(".json"):
                continue
            chemin = os.path.join(racine, f)
            if seulement_orphelins:
                rel = os.path.relpath(chemin, dossier)[: -len(".json")]
                source = os.path.join(conf.dossier_source, rel + ".pdf")
                if os.path.exists(source):
                    continue
            try:
                taille = os.path.getsize(chemin)
                os.remove(chemin)
                nb += 1
                octets += taille
            except OSError:
                continue
    _supprimer_dossiers_vides(dossier)
    return nb, octets


def compacter_cache_traduction() -> tuple[int, int]:
    """Exécute un VACUUM sur la base SQLite de traductions.

    Returns:
        (taille avant, taille après) en octets.
    """
    conf = cfg.get_config()
    chemin = conf.chemin_cache_trad
    if not os.path.exists(chemin):
        return 0, 0

    avant = os.path.getsize(chemin)
    # Fermer la connexion partagée pour éviter un verrou.
    if cfg.cache_conn is not None:
        try:
            cfg.cache_conn.close()
        except sqlite3.Error:
            pass
        cfg.cache_conn = None

    conn = sqlite3.connect(chemin)
    try:
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    return avant, os.path.getsize(chemin)


def vider_cache_traduction() -> int:
    """Vide entièrement la table de cache des traductions.

    Returns:
        Nombre d'entrées supprimées.
    """
    conf = cfg.get_config()
    chemin = conf.chemin_cache_trad
    if not os.path.exists(chemin):
        return 0

    if cfg.cache_conn is not None:
        try:
            cfg.cache_conn.close()
        except sqlite3.Error:
            pass
        cfg.cache_conn = None

    conn = sqlite3.connect(chemin)
    try:
        nb = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        conn.execute("DELETE FROM t")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return nb


def checkpoints_suspects() -> list[dict]:
    """Liste les checkpoints incomplets ou non vérifiés linguistiquement."""
    conf = cfg.get_config()
    dossier = conf.dossier_checkpoints
    resultats: list[dict] = []
    if not os.path.isdir(dossier):
        return resultats

    for racine, _, fichiers in os.walk(dossier):
        for f in fichiers:
            if not f.endswith(".json"):
                continue
            chemin = os.path.join(racine, f)
            nom = os.path.relpath(chemin, dossier)[: -len(".json")]
            try:
                with open(chemin, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                resultats.append({"nom": nom, "raison": "illisible", "pages": 0, "total": 0})
                continue
            pages = len(data.get("pages_traduites", {}))
            total = data.get("total_pages", 0)
            meta = charger_metadonnees_checkpoint(nom)
            if meta.get("version", 1) < 2:
                raison = "format ancien (sans contrôle de langue)"
            elif total and pages < total:
                raison = f"incomplet ({pages}/{total})"
            else:
                continue
            resultats.append(
                {"nom": nom, "raison": raison, "pages": pages, "total": total}
            )
    return sorted(resultats, key=lambda d: d["nom"])


def _supprimer_dossiers_vides(racine: str) -> None:
    """Supprime récursivement les sous-dossiers vides."""
    for chemin, dossiers, fichiers in os.walk(racine, topdown=False):
        if chemin == racine:
            continue
        if not dossiers and not fichiers:
            try:
                os.rmdir(chemin)
            except OSError:
                pass


def nettoyage_complet(
    purger_extraction: bool = True,
    jours_extraction: Optional[int] = 30,
    purger_cp_orphelins: bool = True,
    compacter_db: bool = True,
    callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """Exécute une passe de nettoyage complète et retourne un rapport."""
    def _log(msg: str) -> None:
        if callback:
            callback(msg)

    rapport: dict = {"libere": 0, "details": []}

    if purger_extraction:
        nb, octets = purger_cache_extraction(jours_extraction)
        rapport["libere"] += octets
        detail = (
            f"Cache d'extraction : {nb} fichier(s) supprimé(s) "
            f"({formater_taille(octets)})"
        )
        rapport["details"].append(detail)
        _log(detail)

    if purger_cp_orphelins:
        nb, octets = purger_checkpoints(seulement_orphelins=True)
        rapport["libere"] += octets
        detail = (
            f"Checkpoints orphelins : {nb} supprimé(s) ({formater_taille(octets)})"
        )
        rapport["details"].append(detail)
        _log(detail)

    if compacter_db:
        avant, apres = compacter_cache_traduction()
        gain = max(avant - apres, 0)
        rapport["libere"] += gain
        detail = (
            f"Cache de traduction compacté : {formater_taille(avant)} → "
            f"{formater_taille(apres)} (gain {formater_taille(gain)})"
        )
        rapport["details"].append(detail)
        _log(detail)

    _log(f"Espace total libéré : {formater_taille(rapport['libere'])}")
    return rapport
