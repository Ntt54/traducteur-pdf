#!/usr/bin/env python3
"""
Traduction : cache SQLite, proxy rotation, worker threads, rate limiting.
"""

from __future__ import annotations

import os
import time
import random
import socket
import hashlib
import sqlite3
from threading import Lock, Thread, Semaphore
from typing import Optional, Any, Callable

from deep_translator import GoogleTranslator

# Argos Translate (offline) — optionnel
try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_DISPONIBLE = True
except ImportError:
    ARGOS_DISPONIBLE = False

from . import config as cfg
from . import extracteur as ext
from . import exportateur as exp
from . import correcteur as corr
from .utils import log_dynamique, log_fixe, charger_checkpoint, \
    sauvegarder_checkpoint, supprimer_checkpoint


# ─────────────────────────────────────────────
#   CONSTANTES ERREURS RÉSEAU
# ─────────────────────────────────────────────

_MOTS_RESEAU = (
    "connection", "connexion", "getaddrinfo", "name resolution",
    "temporary failure", "failed to establish", "max retries",
    "timed out", "timeout", "unreachable", "network", "ssl",
    "remote end closed", "connection reset", "connection aborted",
)


def _est_erreur_reseau(msg: str) -> bool:
    return any(m in msg for m in _MOTS_RESEAU)


# ─────────────────────────────────────────────
#   MODE HORS LIGNE — ARGOS TRANSLATE
# ─────────────────────────────────────────────

def argos_disponible() -> bool:
    """Vérifie si la bibliothèque Argos Translate est installée."""
    return ARGOS_DISPONIBLE


def modele_offline_installe(langue_source: str, langue_cible: str) -> bool:
    """Vérifie si le modèle Argos est déjà installé pour la paire de langues."""
    if not ARGOS_DISPONIBLE:
        return False
    return any(
        pkg.from_code == langue_source and pkg.to_code == langue_cible
        for pkg in argostranslate.package.get_installed_packages()
    )


def init_modele_offline(
    langue_source: str,
    langue_cible: str,
    callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Télécharge et installe le modèle Argos si nécessaire.
    
    Retourne un message d'état (succès ou erreur).
    """
    if not ARGOS_DISPONIBLE:
        msg = "argostranslate n'est pas installé. pip install argostranslate"
        if callback:
            callback(msg)
        return msg

    if cfg.modele_offline_init:
        return "Modèle déjà chargé."

    if modele_offline_installe(langue_source, langue_cible):
        cfg.modele_offline_init = True
        # Warmup
        try:
            argostranslate.translate.translate("Hello", langue_source, langue_cible)
        except Exception:
            pass
        msg = f"Modèle {langue_source}→{langue_cible} déjà installé."
        if callback:
            callback(msg)
        return msg

    try:
        if callback:
            callback("Téléchargement de l'index des packages...")
        argostranslate.package.update_package_index()
    except Exception as e:
        msg = f"Impossible de télécharger l'index Argos (Internet requis) : {e}"
        if callback:
            callback(msg)
        return msg

    try:
        pkg = next(
            (p for p in argostranslate.package.get_available_packages()
             if p.from_code == langue_source and p.to_code == langue_cible),
            None,
        )
        if not pkg:
            msg = f"Modèle {langue_source}→{langue_cible} introuvable dans l'index Argos."
            if callback:
                callback(msg)
            return msg
    except Exception as e:
        msg = f"Erreur lors de la recherche du modèle : {e}"
        if callback:
            callback(msg)
        return msg

    try:
        if callback:
            callback(f"Téléchargement du modèle {langue_source}→{langue_cible}...")
        pkg.install()
        cfg.modele_offline_init = True
        msg = f"Modèle {langue_source}→{langue_cible} installé avec succès."
        if callback:
            callback(msg)
        return msg
    except Exception as e:
        msg = f"Échec de l'installation du modèle : {e}"
        if callback:
            callback(msg)
        return msg


def traduire_bloc_offline(bloc: str, langue_source: str, langue_cible: str) -> str:
    """Traduit un bloc avec Argos Translate (offline)."""
    if not bloc.strip():
        return ""
    try:
        return argostranslate.translate.translate(bloc, langue_source, langue_cible) or bloc
    except Exception:
        return bloc


def internet_disponible(timeout: int = 3) -> bool:
    """Vérifie rapidement la connectivité Internet."""
    for hote, port in (("translate.google.com", 443), ("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((hote, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


class HorsLigneError(Exception):
    """Levée quand la connexion Internet est perdue."""
    pass


# ─────────────────────────────────────────────
#   PROXY ROTATION
# ─────────────────────────────────────────────

def get_next_proxy() -> Optional[dict[str, str]]:
    """Retourne le prochain proxy (round-robin)."""
    conf = cfg.get_config()
    if not conf.proxies:
        return None
    with cfg.proxy_lock:
        idx = cfg.proxy_index % len(conf.proxies)
        cfg.proxy_index += 1
        return conf.proxies[idx]


# ─────────────────────────────────────────────
#   CACHE SQLITE
# ─────────────────────────────────────────────

def init_cache() -> None:
    """Initialise la base SQLite de cache des traductions."""
    conf = cfg.get_config()
    if cfg.cache_conn is not None:
        return
    cfg.cache_conn = sqlite3.connect(conf.chemin_cache_trad, check_same_thread=False)
    cfg.cache_conn.execute("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")
    cfg.cache_conn.commit()


def _cle_cache(bloc: str) -> str:
    conf = cfg.get_config()
    return hashlib.sha1(
        f"{conf.langue_source}:{conf.langue_cible}:{bloc}".encode("utf-8")
    ).hexdigest()


def _ensure_cache() -> None:
    if cfg.cache_conn is None:
        init_cache()


def cache_get(bloc: str) -> Optional[str]:
    """Récupère une traduction depuis le cache."""
    _ensure_cache()
    with cfg.cache_lock:
        r = cfg.cache_conn.execute(
            "SELECT v FROM t WHERE k=?", (_cle_cache(bloc),)
        ).fetchone()
    return r[0] if r else None


def cache_put(bloc: str, trad: str) -> None:
    """Stocke une traduction dans le cache."""
    _ensure_cache()
    with cfg.cache_lock:
        cfg.cache_conn.execute(
            "INSERT OR REPLACE INTO t VALUES (?,?)", (_cle_cache(bloc), trad)
        )
        cfg.cache_conn.commit()


# ─────────────────────────────────────────────
#   DÉCOUPAGE EN BLOCS
# ─────────────────────────────────────────────

def decouper_blocs(texte: str, taille_max: Optional[int] = None) -> list[str]:
    """Découpe un texte en blocs de taille maximale donnée."""
    conf = cfg.get_config()
    taille = taille_max or conf.taille_bloc
    blocs: list[str] = []
    while len(texte) > taille:
        coupe = texte.rfind('\n\n', 0, taille)
        if coupe == -1:
            coupe = texte.rfind('\n', 0, taille)
        if coupe == -1:
            coupe = texte.rfind('. ', 0, taille)
        if coupe == -1:
            coupe = taille
        blocs.append(texte[:coupe + 1])
        texte = texte[coupe + 1:]
    if texte:
        blocs.append(texte)
    return blocs


# ─────────────────────────────────────────────
#   TRADUCTION D'UN BLOC
# ─────────────────────────────────────────────

def traduire_bloc(
    bloc: str,
    langue_source: str,
    langue_cible: str,
    translator: GoogleTranslator,
) -> str:
    """Traduit un bloc de texte avec retry et cache."""
    if not bloc.strip():
        return ""
    hit = cache_get(bloc)
    if hit is not None:
        with cfg.progress_lock:
            cfg.blocs_caches += 1
        return hit

    conf = cfg.get_config()
    with cfg._rate_limiter:
        proxy = get_next_proxy()
        for tentative in range(conf.max_retries):
            try:
                if proxy and hasattr(translator, 'session'):
                    translator.session.proxies.update(proxy)
                result = translator.translate(bloc) or bloc
                cache_put(bloc, result)
                time.sleep(random.uniform(conf.pace_min, conf.pace_max))
                return result
            except Exception as e:
                msg = str(e).lower()
                if "429" in msg or "too many" in msg or "rate" in msg:
                    time.sleep(min(conf.backoff_cap, 2 ** tentative) + random.uniform(0, 1))
                elif _est_erreur_reseau(msg):
                    if not internet_disponible():
                        raise HorsLigneError()
                    time.sleep(1 + random.uniform(0, 0.5))
                else:
                    time.sleep(1 + random.uniform(0, 0.5))
    if not internet_disponible():
        raise HorsLigneError()
    with cfg.progress_lock:
        cfg.blocs_echoues += 1
    return bloc


# ─────────────────────────────────────────────
#   WORKER THREAD
# ─────────────────────────────────────────────

def worker_traduction(
    translator: Optional[GoogleTranslator],
    task_queue: Any,
    fichiers_data: dict,
    police: str,
    police_bold: str,
) -> None:
    """Thread worker : pioche dans la queue, traduit, checkpoint, déclenche l'export.
    
    En mode offline (conf.mode_offline=True), translator peut être None
    et la traduction utilise Argos Translate.
    """
    conf = cfg.get_config()
    while True:
        if cfg.ANNULER:
            try:
                while True:
                    task_queue.get_nowait()
                    task_queue.task_done()
            except Exception:
                pass
            break
        try:
            nom_base, index, texte = task_queue.get(timeout=0.5)
        except Exception:
            with cfg.progress_lock:
                if cfg.extraction_terminee and task_queue.empty():
                    break
            continue

        blocs = decouper_blocs(texte)
        try:
            if conf.mode_offline:
                traduits = [
                    traduire_bloc_offline(b, conf.langue_source, conf.langue_cible)
                    for b in blocs
                ]
            else:
                traduits = [
                    traduire_bloc(b, conf.langue_source, conf.langue_cible, translator)  # type: ignore[arg-type]
                    for b in blocs
                ]
        except HorsLigneError:
            cfg.HORS_LIGNE = True
            cfg.ANNULER = True
            log_fixe("\U0001f4f5 Connexion Internet perdue \u2014 arr\u00eat automatique.")
            task_queue.task_done()
            continue

        texte_traduit = "\n\n".join(traduits)
        if conf.correction_ortho:
            texte_traduit = corr.corriger_texte(texte_traduit)

        with cfg.data_lock:
            data = fichiers_data[nom_base]
            data["pages_traduites"][str(index)] = texte_traduit
            data["compteur_local"] += 1

            if data["compteur_local"] % 15 == 0:
                sauvegarder_checkpoint(nom_base, data["pages_traduites"], data["total_pages"])

            if data["compteur_local"] == data["total_pages"] and not data["deja_exporte"]:
                fichiers_termines = sum(1 for d in fichiers_data.values() if d["deja_exporte"])
                total_fichiers = len(fichiers_data)
                pct = (fichiers_termines / total_fichiers * 100) if total_fichiers > 0 else 0
                log_fixe(
                    f" \u2705 {pct:.1f}% | G\u00e9n\u00e9ration ({fichiers_termines}/{total_fichiers}) : {nom_base}"
                )
                cfg.futures_pdf.append(
                    cfg.executor_pdf.submit(
                        exp.exporter_document,
                        data["pages_traduites"].copy(),
                        data["total_pages"],
                        data["sortie"],
                        police,
                        police_bold,
                        nom_base,
                    )
                )
                supprimer_checkpoint(nom_base)
                data["deja_exporte"] = True

        with cfg.progress_lock:
            cfg.total_done += 1
            pct = (cfg.total_done / cfg.total_tasks * 100) if cfg.total_tasks > 0 else 0
            log_dynamique(f" \u23f3 {pct:.1f}% | {cfg.total_done}/{cfg.total_tasks} pages traduites")
            if cfg.PROGRESS_CALLBACK:
                try:
                    cfg.PROGRESS_CALLBACK(
                        cfg.total_done / cfg.total_tasks if cfg.total_tasks else 0.0,
                        f"{cfg.total_done}/{cfg.total_tasks} pages traduites",
                    )
                except Exception:
                    pass
        task_queue.task_done()
