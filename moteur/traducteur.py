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
# Ajoute le venv local si présent (venvargos au même niveau que traducteur.py)
_VENV_ARgos = os.path.join(os.path.dirname(os.path.dirname(__file__)), "venvargos")
if os.path.isdir(_VENV_ARgos):
    import sys
    _pkg_path = os.path.join(_VENV_ARgos, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if _pkg_path not in sys.path:
        sys.path.insert(0, _pkg_path)

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
from .revision import texte_est_francais as _est_francais
from .utils import log_dynamique, log_fixe, charger_checkpoint, \
    sauvegarder_checkpoint, supprimer_checkpoint, hash_texte


def _patch_stanza_offline() -> None:
    """Désactive le téléchargement en ligne des ressources Stanza.

    Le ``StanzaSentencizer`` d'Argos Translate crée un ``stanza.Pipeline``
    avec le ``download_method`` par défaut (``DOWNLOAD_RESOURCES``) qui tente
    de récupérer *resources.json* depuis GitHub à chaque initialisation.
    En mode hors ligne, l'absence de DNS rend cela impossible et toutes les
    pages échouent.  Ce monkey-patch force ``DownloadMethod.NONE`` pour
    utiliser les ressources déjà embarquées dans le paquet Argos.
    """
    try:
        import stanza
    except ImportError:
        return
    from argostranslate.sbd import StanzaSentencizer

    def _lazy_pipeline_offline(self):
        if self.stanza_pipeline is None:
            self.stanza_pipeline = stanza.Pipeline(
                lang=self.stanza_lang_code,
                dir=str(self.pkg.package_path / "stanza"),
                processors="tokenize",
                use_gpu=False,
                logging_level="WARNING",
                download_method=stanza.DownloadMethod.NONE,
            )
        return self.stanza_pipeline

    StanzaSentencizer.lazy_pipeline = _lazy_pipeline_offline


if ARGOS_DISPONIBLE:
    _patch_stanza_offline()


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
#   ANTI RATE-LIMIT GOOGLE (compteur global)
# ─────────────────────────────────────────────

_blocages_consecutifs: int = 0
_blocages_lock = Lock()


def _blocage_signale_et_pause_longue_si_seuil(conf) -> None:
    """Incrémente le compteur de blocages ; pause longue après N consécutifs."""
    global _blocages_consecutifs
    with _blocages_lock:
        _blocages_consecutifs += 1
        n = _blocages_consecutifs
    if n % max(1, conf.seuil_pause_longue) == 0:
        log_fixe(
            f" 🛑 {n} blocages Google consécutifs — pause longue "
            f"de {conf.pause_longue_sec:.0f}s pour laisser retomber le rate-limit…"
        )
        time.sleep(conf.pause_longue_sec)


def _succes_reinitialise_blocages() -> None:
    global _blocages_consecutifs
    with _blocages_lock:
        _blocages_consecutifs = 0


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
    """Traduit un bloc avec Argos Translate (offline).

    En cas d'échec, lève ``TraductionEchoueeError`` afin que le texte source
    non traduit ne soit jamais enregistré comme une traduction valide.
    """
    if not bloc.strip():
        return ""
    try:
        resultat = argostranslate.translate.translate(bloc, langue_source, langue_cible)
    except Exception as e:
        raise TraductionEchoueeError(f"Argos offline : {e}") from e
    if not resultat or resultat == bloc:
        raise TraductionEchoueeError("Argos a renvoyé un texte vide ou identique")
    return resultat


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


class TraductionEchoueeError(Exception):
    """Levée quand la traduction d'un bloc échoue après tous les essais.

    Permet au worker de ne PAS enregistrer le texte source non traduit
    dans le checkpoint, et donc d'empêcher l'export d'un PDF en anglais.
    """
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
    """Traduit un bloc de texte avec retry et cache.

    Anti rate-limit Google : backoff exponentiel à base 5s
    (5s, 10s, 20s, 40s, 80s… plafonné par backoff_cap) + jitter,
    jusqu'à max_retries essais (défaut 15), sémaphore tenu pendant
    l'appel Google, pause longue après N blocages consécutifs.
    En cas d'échec final, lève TraductionEchoueeError SANS écrire
    le texte source au checkpoint (le worker ne persiste rien).
    """
    if not bloc.strip():
        return ""
    hit = cache_get(bloc)
    if hit is not None:
        with cfg.progress_lock:
            cfg.blocs_caches += 1
        return hit

    conf = cfg.get_config()
    proxy = get_next_proxy()
    max_tentatives = max(1, conf.max_retries)
    a_blocage_google = False
    for tentative in range(max_tentatives):
        try:
            if proxy and hasattr(translator, 'session'):
                translator.session.proxies.update(proxy)
            # Délai inter-requête respecté avant chaque nouvel essai.
            if tentative > 0:
                time.sleep(random.uniform(conf.pace_min, conf.pace_max))
            # Le sémaphore est TENU pendant l'appel Google : au plus
            # RATE_LIMIT (défaut 3) appels concurrents.
            with cfg._rate_limiter:
                result = translator.translate(bloc)
            if not result or not result.strip():
                raise TraductionEchoueeError("Google a renvoyé un texte vide")
            cache_put(bloc, result)
            _succes_reinitialise_blocages()
            time.sleep(random.uniform(conf.pace_min, conf.pace_max))
            return result
        except TraductionEchoueeError:
            time.sleep(random.uniform(conf.pace_min, conf.pace_max))
        except Exception as e:
            msg = str(e).lower()
            vide_ou_bloque = (
                "expecting value" in msg
                or "jsondecodeerror" in msg
                or "no translation" in msg
                or "no text" in msg
                or ("translator.session" in msg and "proxy" not in msg)
                or ("none" == msg.strip().strip("'\"") and tentative is not None)
            )
            if "429" in msg or "too many" in msg or "rate" in msg or vide_ou_bloque:
                a_blocage_google = True
                base = max(1.0, float(getattr(conf, "backoff_base_google", 5.0)))
                delai = min(conf.backoff_cap, base * (2 ** tentative)) + random.uniform(0, 2)
                log_fixe(
                    f" ⏳ Bloc bloqué par Google (anti-bot / rate-limit) "
                    f"— essai {tentative + 1}/{max_tentatives}, "
                    f"backoff {delai:.1f}s puis nouvel essai…"
                )
                _blocage_signale_et_pause_longue_si_seuil(conf)
                time.sleep(delai)
            elif _est_erreur_reseau(msg):
                if not internet_disponible():
                    raise HorsLigneError()
                time.sleep(random.uniform(conf.pace_min, conf.pace_max))
            else:
                time.sleep(random.uniform(conf.pace_min, conf.pace_max))
    if a_blocage_google or internet_disponible():
        pass
    else:
        raise HorsLigneError()
    with cfg.progress_lock:
        cfg.blocs_echoues += 1
    raise TraductionEchoueeError(
        f"Traduction impossible après {conf.max_retries} essais ({bloc[:40]!r}...)"
    )


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
            if conf.mode_nllb:
                from .nllb import traduire_bloc_nllb
                traduits = [
                    traduire_bloc_nllb(b, conf.langue_source, conf.langue_cible)
                    for b in blocs
                ]
            elif conf.mode_offline:
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
            try:
                while True:
                    task_queue.get_nowait()
                    task_queue.task_done()
            except Exception:
                pass
            task_queue.task_done()
            break
        except TraductionEchoueeError as e:
            # Page NON traduite : ne pas l'enregistrer dans le checkpoint.
            # Elle sera retentée lors d'une prochaine exécution.
            with cfg.progress_lock:
                cfg.blocs_echoues += 1
            log_fixe(f" \u26a0\ufe0f Page {index} non traduite ({nom_base}) : {e}")
            task_queue.task_done()
            continue

        texte_traduit = "\n\n".join(traduits)
        if conf.correction_ortho:
            texte_traduit = corr.corriger_texte(texte_traduit)

        # Garde-fou : une page dont la traduction est identique au texte source
        # n'est pas une traduction — ne pas la persister.
        if texte.strip() and hash_texte(texte_traduit) == hash_texte(texte):
            with cfg.progress_lock:
                cfg.blocs_echoues += 1
            log_fixe(
                f" \u26a0\ufe0f Page {index} identique \u00e0 la source ({nom_base}) "
                f"\u2014 non enregistr\u00e9e."
            )
            task_queue.task_done()
            continue

        with cfg.data_lock:
            data = fichiers_data[nom_base]
            data["pages_traduites"][str(index)] = texte_traduit
            data.setdefault("hash_original", {})[str(index)] = hash_texte(texte)
            data["compteur_local"] += 1

            if data["compteur_local"] % 15 == 0:
                sauvegarder_checkpoint(
                    nom_base, data["pages_traduites"], data["total_pages"],
                    data.get("hash_original"),
                )

            if data["compteur_local"] == data["total_pages"] and not data["deja_exporte"]:
                # Vérification finale : le document complet doit être en français.
                texte_complet = "\n\n".join(
                    data["pages_traduites"].get(str(i), "")
                    for i in range(data["total_pages"])
                )
                if texte_complet.strip() and not _est_francais(texte_complet):
                    log_fixe(
                        f" \u274c Export annul\u00e9 ({nom_base}) : le texte n'est pas en "
                        f"fran\u00e7ais (traduction \u00e9chou\u00e9e). Retentative au prochain passage."
                    )
                    sauvegarder_checkpoint(
                        nom_base, data["pages_traduites"], data["total_pages"],
                        data.get("hash_original"), langue_verifiee=False,
                    )
                    task_queue.task_done()
                    continue
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
            details = _format_eta(cfg.total_done, cfg.total_tasks, cfg.temps_debut)
            log_dynamique(
                f" \u23f3 {pct:.1f}% | {cfg.total_done}/{cfg.total_tasks} pages{details}"
            )
            if cfg.PROGRESS_CALLBACK:
                try:
                    cfg.PROGRESS_CALLBACK(
                        cfg.total_done / cfg.total_tasks if cfg.total_tasks else 0.0,
                        f"{cfg.total_done}/{cfg.total_tasks} pages traduites{details}",
                    )
                except Exception:
                    pass
        task_queue.task_done()


def _format_duree(secondes: float) -> str:
    """Formate une durée en h/min/s lisible."""
    secondes = int(max(secondes, 0))
    h, reste = divmod(secondes, 3600)
    m, s = divmod(reste, 60)
    if h:
        return f"{h}h{m:02d}"
    if m:
        return f"{m}min{s:02d}"
    return f"{s}s"


def _format_eta(done: int, total: int, t0: float) -> str:
    """Retourne ' | 12.4 p/min | ETA 3min20' ou '' si non calculable."""
    if not t0 or done <= 0 or total <= 0:
        return ""
    ecoule = time.time() - t0
    if ecoule < 2:
        return ""
    debit = done / ecoule
    restant = max(total - done, 0)
    eta = restant / debit if debit > 0 else 0
    return f" | {debit * 60:.1f} p/min | ETA {_format_duree(eta)}"
