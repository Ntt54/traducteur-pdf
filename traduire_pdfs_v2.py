#!/usr/bin/env python3
"""
=============================================================
  TRADUCTEUR PDF v8 — PIPELINE COMPLET AVANCÉ
  (Wrapper rétrocompatible — délègue au package moteur/)
=============================================================

Ce fichier reste le point d'entrée principal pour la CLI et
l'interface graphique. Il importe et re-exporte tous les symboles
nécessaires depuis le package moteur/ refactoré.
"""

from __future__ import annotations

import os
import sys
import glob
import time
import re
from queue import Queue
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

from deep_translator import GoogleTranslator

# ── Import depuis le package refactoré ──
from moteur import config as _config
from moteur.config import (
    ConfigMoteur, configurer, get_config,
    ANNULER, HORS_LIGNE, blocs_echoues, blocs_caches,
    extraction_terminee, total_done, total_tasks,
    futures_pdf, executor_pdf,
    PROGRESS_CALLBACK, LOG_CALLBACK,
    STYLES_PDF_PAR_DEFAUT,
)
from moteur.utils import (
    log_dynamique, log_fixe, tri_naturel,
    charger_police, charger_checkpoint, sauvegarder_checkpoint,
    supprimer_checkpoint, charger_metadonnees_checkpoint, hash_texte,
)
from moteur.extracteur import (
    extraire_texte_pdf, nettoyer_texte,
    charger_cache_extraction, sauvegarder_cache_extraction,
)
from moteur.traducteur import (
    cache_get, cache_put, init_cache,
    decouper_blocs, traduire_bloc, worker_traduction,
    internet_disponible, HorsLigneError, TraductionEchoueeError,
    get_next_proxy,
    argos_disponible, modele_offline_installe, init_modele_offline,
)
from moteur.revision import texte_est_francais
from moteur.exportateur import (
    exporter_document, fusionner_pdfs,
)
from moteur.correcteur import (
    init_ortho, corriger_texte,
)

# ── Variables globales pour rétrocompatibilité ──
# (certains scripts externes peuvent les lire directement)
DOSSIER_SOURCE = "./pdfs_originaux"
DOSSIER_SORTIE = "./pdfs_traduits"
DOSSIER_CHECKPOINTS = "./checkpoints"
DOSSIER_CACHE_EXTRACTION = "./extraction_cache"
CHEMIN_CACHE_TRAD = "./translation_cache.db"
LANGUE_SOURCE = "en"
LANGUE_CIBLE = "fr"
TAILLE_BLOC = 4800
NB_THREADS_TRAD = 50
NB_THREADS_PDF = 5
RATE_LIMIT = 50
FORMAT_EXPORT = "pdf"
CORRECTION_ORTHO = False
MODE_OFFLINE = False
MODE_NLLB = False
PROXIES = []
MERGE_ENABLED = False
MERGE_OUTPUT = ""
STYLES_PDF = dict(STYLES_PDF_PAR_DEFAUT)
FICHIERS_SELECTION = None

# Pour la fonction traiter_tous (CLI)
_print_lock = _config.print_lock
_rate_limiter = _config._rate_limiter


def _sync_globals() -> None:
    """Synchronise les variables globales de ce module avec la config actuelle."""
    c = get_config()
    globals().update({
        "DOSSIER_SOURCE": c.dossier_source,
        "DOSSIER_SORTIE": c.dossier_sortie,
        "DOSSIER_CHECKPOINTS": c.dossier_checkpoints,
        "DOSSIER_CACHE_EXTRACTION": c.dossier_cache_extraction,
        "CHEMIN_CACHE_TRAD": c.chemin_cache_trad,
        "LANGUE_SOURCE": c.langue_source,
        "LANGUE_CIBLE": c.langue_cible,
        "TAILLE_BLOC": c.taille_bloc,
        "NB_THREADS_TRAD": c.nb_threads_trad,
        "NB_THREADS_PDF": c.nb_threads_pdf,
        "RATE_LIMIT": c.rate_limit,
        "FORMAT_EXPORT": c.format_export,
        "CORRECTION_ORTHO": c.correction_ortho,
        "MODE_OFFLINE": c.mode_offline,
        "MODE_NLLB": c.mode_nllb,
        "PROXIES": c.proxies,
        "MERGE_ENABLED": c.merge_enabled,
        "MERGE_OUTPUT": c.merge_output,
        "STYLES_PDF": c.styles_pdf,
        "FICHIERS_SELECTION": c.fichiers_selection,
    })


# ─────────────────────────────────────────────
#   NOM DE FICHIER DE SORTIE
# ─────────────────────────────────────────────

def _nom_sortie(fichier: str, fmt: str) -> str:
    """Génère le nom du fichier de sortie pour un fichier source."""
    conf = get_config()
    nom_base = os.path.splitext(fichier)[0]
    ext = ".pdf"
    if fmt == "txt":
        ext = ".txt"
    elif fmt == "md":
        ext = ".md"
    elif fmt == "docx":
        ext = ".docx"
    suffixe = "_argos" if conf.mode_offline else ("_nllb" if conf.mode_nllb else "")
    return nom_base + f"_traduit_{conf.langue_cible}{suffixe}{ext}"


# ─────────────────────────────────────────────
#   PIPELINE PRINCIPAL
# ─────────────────────────────────────────────

def traiter_tous() -> None:
    """Pipeline complet : extraction → traduction → export (pour CLI)."""
    global total_done, total_tasks, extraction_terminee, futures_pdf, executor_pdf, \
           ANNULER, HORS_LIGNE, blocs_echoues, blocs_caches
    conf = get_config()
    _sync_globals()
    ANNULER = False
    HORS_LIGNE = False

    os.makedirs(conf.dossier_source, exist_ok=True)
    os.makedirs(conf.dossier_sortie, exist_ok=True)

    init_cache()
    if conf.correction_ortho:
        init_ortho(conf.langue_ortho)
    t0 = time.time()

    exclure = {"traduits", "extraction_cache", "checkpoints"}
    fichiers = sorted(
        (os.path.relpath(p, conf.dossier_source) for p in glob.iglob(
            os.path.join(conf.dossier_source, "**", "*.pdf"), recursive=True)
         if not any(ex in os.path.relpath(p, conf.dossier_source).split(os.sep)
                    for ex in exclure)),
        key=tri_naturel
    )
    if not fichiers:
        log_fixe(f"Aucun PDF trouv\u00e9 dans '{conf.dossier_source}'")
        return
    if conf.fichiers_selection is not None:
        sel = set(conf.fichiers_selection)
        fichiers = [f for f in fichiers if f in sel]
        if not fichiers:
            log_fixe("Aucun fichier de la s\u00e9lection trouv\u00e9.")
            return

    print(f"\n{'='*80}")
    if conf.mode_nllb:
        mode_label = "HORS LIGNE (NLLB-200)"
    elif conf.mode_offline:
        mode_label = "HORS LIGNE (Argos)"
    else:
        mode_label = "EN LIGNE (Google)"
    print(f"  TRADUCTEUR PDF v8 — PIPELINE {'NLLB' if conf.mode_nllb else ('OFFLINE' if conf.mode_offline else 'AVANC\u00c9')}")
    print(f"  {conf.langue_source.upper()} -> {conf.langue_cible.upper()} | Mode: {mode_label} | Export: {conf.format_export.upper()}")
    if conf.mode_offline or conf.mode_nllb:
        print(f"  Offline — aucune connexion réseau nécessaire")
    print(f"  Threads: {conf.nb_threads_trad} | Taille bloc: {conf.taille_bloc}" + (f" | Proxies: {len(conf.proxies)}" if not conf.mode_offline else ""))
    if conf.correction_ortho:
        print(f"  Correction ortho: {conf.langue_ortho}")
    print(f"{'='*80}\n")

    police, police_bold = charger_police()
    task_queue: Queue = Queue()
    fichiers_data: dict = {}
    globals()["total_done"] = 0
    globals()["total_tasks"] = 0
    globals()["extraction_terminee"] = False
    globals()["futures_pdf"] = []

    executor = ThreadPoolExecutor(max_workers=conf.nb_threads_pdf)
    _config.executor_pdf = executor  # Source unique de vérité pour l'executor PDF

    if conf.mode_offline or conf.mode_nllb:
        translators = [None] * conf.nb_threads_trad
        label = "offline NLLB" if conf.mode_nllb else "offline"
        log_fixe(f"\U0001f4e1 {conf.nb_threads_trad} threads traducteurs ({label}) lanc\u00e9s.")
    else:
        translators = [GoogleTranslator(source=conf.langue_source, target=conf.langue_cible)
                       for _ in range(conf.nb_threads_trad)]
        log_fixe(f"\U0001f680 {conf.nb_threads_trad} threads traducteurs (en ligne) lanc\u00e9s.")
    threads = []
    for i in range(conf.nb_threads_trad):
        t = Thread(target=worker_traduction,
                   args=(translators[i], task_queue, fichiers_data, police, police_bold),
                   daemon=True)
        t.start()
        threads.append(t)

    fichiers_extraits = 0
    fichiers_a_extraire = len([f for f in fichiers
                               if not (conf.ignorer_deja_traduits and os.path.exists(
                                   os.path.join(conf.dossier_sortie, _nom_sortie(f, conf.format_export))))])
    log_fixe(f" \U0001f4e4 {fichiers_a_extraire} fichiers \u00e0 traiter")

    for fichier in fichiers:
        if ANNULER:
            log_fixe("Extraction interrompue.")
            break
        entree = os.path.join(conf.dossier_source, fichier)
        nom_base = os.path.splitext(fichier)[0]
        nom_out = _nom_sortie(fichier, conf.format_export)
        sortie = os.path.join(conf.dossier_sortie, nom_out)

        if conf.ignorer_deja_traduits and os.path.exists(sortie):
            log_fixe(f" \u23e9 D\u00e9j\u00e0 traduit (ignor\u00e9) : {fichier}")
            continue

        pages_texte = charger_cache_extraction(nom_base)
        if pages_texte is None:
            log_fixe(f" \U0001f50d [{fichiers_extraits+1}/{fichiers_a_extraire}] Extraction : {fichier}")
            try:
                pages_texte = extraire_texte_pdf(entree)
            except Exception as e:
                log_fixe(f" \u274c Erreur d'extraction ({fichier}) : {e}")
                continue
            sauvegarder_cache_extraction(nom_base, pages_texte)
        else:
            log_fixe(f" \U0001f4c2 [{fichiers_extraits+1}/{fichiers_a_extraire}] Cache : {fichier} ({len(pages_texte)} pages)")

        total_p = len(pages_texte)
        pages_traduites, _ = charger_checkpoint(nom_base)
        meta_cp = charger_metadonnees_checkpoint(nom_base)
        hashes_cp = meta_cp.get("hash_original", {})

        # Anti-corruption : ne conserver que les pages réellement traduites.
        # Rejet si (a) la page n'est pas en français, ou (b) elle est identique
        # au texte source (hash), signe d'un fallback silencieux.
        if pages_traduites:
            pages_valides = {}
            for k, v in pages_traduites.items():
                if not v.strip() or not texte_est_francais(v):
                    continue
                try:
                    source = pages_texte[int(k)]
                except (ValueError, IndexError):
                    source = ""
                if source.strip() and hash_texte(v) == hash_texte(source):
                    continue
                attendu = hashes_cp.get(k)
                if attendu and source.strip() and attendu != hash_texte(source):
                    # Le PDF source a changé depuis le checkpoint → retraduire.
                    continue
                pages_valides[k] = v
            if len(pages_valides) != len(pages_traduites):
                log_fixe(
                    f" \u26a0\ufe0f {len(pages_traduites) - len(pages_valides)} page(s) invalide(s) "
                    f"retir\u00e9e(s) du checkpoint ({nom_base}) \u2014 retraduction."
                )
                pages_traduites = pages_valides

        deja_faites = set(int(k) for k in pages_traduites.keys())

        with _config.data_lock:
            fichiers_data[nom_base] = {
                "sortie": sortie,
                "total_pages": total_p,
                "pages_traduites": pages_traduites,
                "hash_original": {
                    k: hash_texte(pages_texte[int(k)])
                    for k in pages_traduites
                    if int(k) < total_p
                },
                "compteur_local": len(deja_faites),
                "deja_exporte": False,
            }

        if len(deja_faites) == total_p and total_p > 0:
            # Vérification anti-corruption : le checkpoint doit être en français.
            texte_cp = "\n\n".join(
                pages_traduites.get(str(i), "")
                for i in range(total_p)
            )
            texte_src = "\n\n".join(pages_texte[:total_p])
            corrompu = (
                not texte_cp.strip()
                or not texte_est_francais(texte_cp)
                or hash_texte(texte_cp) == hash_texte(texte_src)
            )
            if corrompu:
                log_fixe(
                    f" \u26a0\ufe0f Checkpoint invalide ({nom_base}) \u2014 retraduction compl\u00e8te."
                )
                supprimer_checkpoint(nom_base)
                pages_traduites = {}
                deja_faites = set()
                with _config.data_lock:
                    fichiers_data[nom_base]["pages_traduites"] = {}
                    fichiers_data[nom_base]["hash_original"] = {}
                    fichiers_data[nom_base]["compteur_local"] = 0
            else:
                log_fixe(f" \U0001f4be [D\u00e9j\u00e0 Fait] G\u00e9n\u00e9ration : {nom_base}")
                futures_pdf.append(
                    executor.submit(
                        exporter_document, pages_traduites, total_p, sortie,
                        police, police_bold, nom_base,
                    )
                )
                supprimer_checkpoint(nom_base)
                fichiers_data[nom_base]["deja_exporte"] = True
                fichiers_extraits += 1
                continue

        for i in range(total_p):
            if i not in deja_faites:
                task_queue.put((nom_base, i, pages_texte[i]))
                total_tasks += 1
        fichiers_extraits += 1
        pct_ext = (fichiers_extraits / fichiers_a_extraire * 100) if fichiers_a_extraire > 0 else 0
        log_fixe(f" \U0001f4ca Extraction : {pct_ext:.1f}% ({fichiers_extraits}/{fichiers_a_extraire})")

    extraction_terminee = True
    log_fixe("\n\u2705 Toutes les extractions sont termin\u00e9es.")

    if not ANNULER:
        task_queue.join()
    for t in threads:
        t.join(timeout=1)
    for f in futures_pdf:
        try:
            f.result()
        except Exception as e:
            log_fixe(f" \u274c Erreur d'export ({f}) : {e}")
    executor.shutdown(wait=True)

    # Fusion finale si demandée
    if MERGE_ENABLED and MERGE_OUTPUT:
        log_fixe("\n\U0001f4c4 Fusion des PDF en cours...")
        pdfs_produits = [
            os.path.join(conf.dossier_sortie, _nom_sortie(f, conf.format_export))
            for f in fichiers
            if os.path.exists(os.path.join(conf.dossier_sortie, _nom_sortie(f, conf.format_export)))
        ]
        fusionner_pdfs(pdfs_produits, MERGE_OUTPUT)

    duree = max(time.time() - t0, 0.001)
    pages_s = total_done / duree
    log_fixe("=" * 60)
    if HORS_LIGNE:
        log_fixe(f"\U0001f4f5 ARR\u00caT (hors ligne) \u2014 {total_done}/{total_tasks} pages.")
    else:
        log_fixe(f"\u2705 100.0% | TERMIN\u00c9 \u2014 {total_tasks} pages traduites.")
    log_fixe(f"\u23f1 Dur\u00e9e : {duree:.0f}s ({duree/60:.1f} min) | D\u00e9bit : {pages_s:.2f} pages/s")
    log_fixe(f"\U0001f4be Cache hit: {blocs_caches} | \u26a0\ufe0f Fallback EN: {blocs_echoues}")
    log_fixe(f"\U0001f4c2 Sortie : {os.path.abspath(conf.dossier_sortie)}")
    log_fixe("=" * 60)
    if PROGRESS_CALLBACK:
        try:
            PROGRESS_CALLBACK(1.0, "Arr\u00eat\u00e9 (hors ligne)" if HORS_LIGNE else "Termin\u00e9")
        except Exception:
            pass


# ─────────────────────────────────────────────
#   FONCTIONS API (utilisées par app_gui.py)
# ─────────────────────────────────────────────

def lancer(config: dict | None = None,
           on_progress=None, on_log=None) -> None:
    """Point d'entrée principal : extraction + traduction + export."""
    if config:
        configurer(config)
        _sync_globals()
    global ANNULER, HORS_LIGNE
    ANNULER = False
    HORS_LIGNE = False
    conf = get_config()
    if conf.mode_nllb:
        from moteur.nllb import init_modele_nllb
        msg = init_modele_nllb(on_log)
        if "introuvable" in msg or "non installés" in msg or "Échec" in msg:
            if on_log:
                on_log(msg)
            print(msg)
            return
    elif conf.mode_offline:
        if not argos_disponible():
            msg = "argostranslate n'est pas installé. pip install argostranslate"
            if on_log:
                on_log(msg)
            print(msg)
            return
        init_modele_offline(conf.langue_source, conf.langue_cible, on_log)
    _config.PROGRESS_CALLBACK = on_progress
    _config.LOG_CALLBACK = on_log
    traiter_tous()


def extraire_seulement(config: dict | None = None,
                       on_progress=None, on_log=None) -> None:
    """Mode extraction uniquement (hors ligne)."""
    if config:
        configurer(config)
        _sync_globals()
    global ANNULER, HORS_LIGNE
    ANNULER = False
    HORS_LIGNE = False
    _config.PROGRESS_CALLBACK = on_progress
    _config.LOG_CALLBACK = on_log

    conf = get_config()
    os.makedirs(conf.dossier_source, exist_ok=True)
    exclure = {"traduits", "extraction_cache", "checkpoints"}
    fichiers = sorted(
        (os.path.relpath(p, conf.dossier_source) for p in glob.iglob(
            os.path.join(conf.dossier_source, "**", "*.pdf"), recursive=True)
         if not any(ex in os.path.relpath(p, conf.dossier_source).split(os.sep)
                    for ex in exclure)),
        key=tri_naturel
    )
    if not fichiers:
        log_fixe(f"Aucun PDF trouv\u00e9 dans '{conf.dossier_source}'")
        return
    if conf.fichiers_selection is not None:
        sel = set(conf.fichiers_selection)
        fichiers = [f for f in fichiers if f in sel]
        if not fichiers:
            log_fixe("Aucun fichier de la s\u00e9lection trouv\u00e9.")
            return
    n = len(fichiers)
    log_fixe(f"\U0001f4f4 Extraction hors ligne : {n} PDF")
    done = 0
    for fichier in fichiers:
        if ANNULER:
            log_fixe("Extraction interrompue.")
            break
        nom_base = os.path.splitext(fichier)[0]
        if charger_cache_extraction(nom_base) is None:
            log_fixe(f" \U0001f50d Extraction : {fichier}")
            try:
                pages = extraire_texte_pdf(os.path.join(conf.dossier_source, fichier))
            except Exception as e:
                log_fixe(f" \u274c Erreur d'extraction ({fichier}) : {e}")
                continue
            sauvegarder_cache_extraction(nom_base, pages)
        else:
            log_fixe(f" \U0001f4c2 D\u00e9j\u00e0 en cache : {fichier}")
        done += 1
        if PROGRESS_CALLBACK:
            try:
                PROGRESS_CALLBACK(done / n, f"{done}/{n} fichiers extraits")
            except Exception:
                pass
    log_fixe("\u2705 Extraction hors ligne termin\u00e9e.")
    if PROGRESS_CALLBACK:
        try:
            PROGRESS_CALLBACK(1.0, "Extraction termin\u00e9e")
        except Exception:
            pass


# ─────────────────────────────────────────────
#   VÉRIFICATION DES LIBRAIRIES (CLI)
# ─────────────────────────────────────────────

def verifier_librairies() -> None:
    """Vérifie que les dépendances principales sont installées."""
    manquantes = []
    for lib in ["pdfplumber", "deep_translator", "reportlab"]:
        try:
            __import__(lib.replace("-", "_"))
        except ImportError:
            manquantes.append(lib)
    if manquantes:
        print(f"pip install {' '.join(manquantes)} --break-system-packages")
        sys.exit(1)

    # Argos Translate (offline) — optionnel, avertir seulement
    try:
        import argostranslate  # noqa: F401
    except ImportError:
        print("ℹ️  argostranslate non installé — mode hors ligne indisponible.")
        print("   Pour l'installer : pip install argostranslate --break-system-packages")


if __name__ == "__main__":
    verifier_librairies()
    traiter_tous()
