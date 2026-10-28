#!/usr/bin/env python3
"""
Révision des traductions — vérifie que les documents traduits sont bien en français
et évite les re-vérifications inutiles.

Stocke l'état de vérification dans un fichier JSON persistant
(``traductions_verifiees.json``) dans le dossier de sortie.
"""

from __future__ import annotations

import json
import os
import re
from typing import Set, Callable

# ─────────────────────────────────────────────
#   STOP WORDS FRANÇAIS
# ─────────────────────────────────────────────

MOTS_FR: set[str] = {
    "le", "la", "les", "des", "est", "sont", "dans", "avec", "pour", "sur",
    "par", "pas", "plus", "mais", "aussi", "très", "même", "cette", "être",
    "avoir", "faire", "comme", "leur", "tout", "bien", "sans", "chez",
    "depuis", "pendant", "entre", "autres", "notre", "votre", "leurs", "ces",
    "aux", "ses", "cet", "cette", "ne", "ce", "se", "je", "il",
    "elle", "on", "nous", "vous", "ils", "elles", "qui", "que", "quoi",
    "dont", "où", "au", "du", "de", "en", "vers", "selon", "malgré",
    "tout", "tous", "toute", "toutes", "mon", "ton", "son", "mes", "tes",
    "nos", "vos", "leurs", "c'est", "s'est", "n'est", "qu'il", "qu'elle",
    "d'un", "d'une", "lui", "y",
}

# ─────────────────────────────────────────────
#   STOP WORDS ANGLAIS
# ─────────────────────────────────────────────

MOTS_EN: set[str] = {
    "the", "and", "is", "are", "was", "were", "in", "with", "for", "on",
    "by", "has", "have", "been", "would", "could", "should", "very",
    "also", "more", "some", "such", "than", "that", "this", "these",
    "those", "what", "which", "who", "whom", "when", "where", "how",
    "all", "each", "every", "both", "few", "many", "much", "no", "not",
    "only", "own", "same", "so", "too", "will", "can", "may", "its",
    "into", "over", "through", "after", "before", "between", "under",
    "about", "above", "down", "out", "up", "to", "from", "of", "it",
    "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "mine", "yours", "hers",
    "ours", "theirs", "hasn't", "haven't", "hadn't", "doesn't", "don't",
    "didn't", "won't", "wouldn't", "couldn't", "shouldn't", "can't",
    "isn't", "aren't", "wasn't", "weren't", "been", "being", "having",
    "doing", "goes", "does", "did", "done", "said", "made", "get", "got",
    "use", "used", "using", "take", "took", "taken", "see", "saw", "seen",
    "know", "knew", "known", "think", "thought", "come", "came", "come",
    "give", "gave", "given", "find", "found", "tell", "told", "become",
    "became", "leave", "left", "feel", "felt", "put", "set", "mean",
    "meant", "keep", "kept", "let", "begin", "began", "begun", "show",
    "showed", "shown", "hear", "heard", "play", "run", "ran", "move",
    "live", "believe", "bring", "brought", "happen", "write", "wrote",
    "written", "provide", "sit", "sat", "stand", "stood", "lose", "lost",
    "pay", "paid", "meet", "met", "include", "continue", "set", "change",
    "lead", "led", "learn", "learned", "understand", "watch", "follow",
    "stop", "create", "speak", "spoke", "spoken", "read", "read", "allow",
    "add", "spend", "spent", "grow", "grew", "grown", "open", "walk",
    "win", "won", "teach", "taught", "offer", "remember", "consider",
    "appear", "buy", "bought", "serve", "die", "send", "sent", "build",
    "built", "stay", "fall", "fell", "fallen", "cut", "reach", "kill",
    "raise", "remain", "suggest", "raise", "produce", "want", "need",
    "seem", "try", "tried", "call", "keep", "held", "expect", "decide",
}

# ─────────────────────────────────────────────
#   PERSISTANCE
# ─────────────────────────────────────────────

FICHIER_VERIF = "traductions_verifiees.json"


def _verifications_path(dossier_sortie: str) -> str:
    """Chemin complet du fichier d'état des vérifications."""
    return os.path.join(dossier_sortie, FICHIER_VERIF)


def _charger_verifications(dossier_sortie: str) -> set[str]:
    """Charge l'ensemble des fichiers déjà vérifiés comme correctement traduits."""
    chemin = _verifications_path(dossier_sortie)
    if os.path.exists(chemin):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("verifies", []))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def _sauvegarder_verifications(dossier_sortie: str, verifies: set[str]) -> None:
    """Sauvegarde l'ensemble des fichiers vérifiés."""
    chemin = _verifications_path(dossier_sortie)
    try:
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump({"verifies": sorted(verifies)}, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"⚠️ Impossible d'écrire le fichier de vérification {chemin} : {e}")


def est_verifie(nom_base: str, dossier_sortie: str) -> bool:
    """Un fichier a-t-il déjà été vérifié comme correctement en français ?"""
    verifies = _charger_verifications(dossier_sortie)
    return nom_base in verifies


def marquer_verifie(nom_base: str, dossier_sortie: str) -> None:
    """Marque un fichier comme vérifié (traduction française confirmée)."""
    verifies = _charger_verifications(dossier_sortie)
    verifies.add(nom_base)
    _sauvegarder_verifications(dossier_sortie, verifies)


# ─────────────────────────────────────────────
#   DÉTECTION DE LANGUE
# ─────────────────────────────────────────────

# Caractères accentués français courants
_ACCENTS_FR = set("éèêëàâîôûùçæœïüÉÈÊËÀÂÎÔÛÙÇÆŒÏÜ")


def texte_est_francais(texte: str, seuil: float = 0.6) -> bool:
    """Vérifie si le texte est majoritairement en français.

    Compare les occurrences de mots français vs anglais à l'aide de
    listes de stop words. Si le ratio ``français / (français + anglais)``
    dépasse le *seuil*, le texte est considéré comme français.

    Args:
        texte: Texte à analyser.
        seuil: Ratio minimal français/(français+anglais) pour valider.

    Returns:
        True si le texte semble être en français.
    """
    if not texte or not texte.strip():
        return False

    mots = re.findall(r"\b[a-zA-ZéèêëàâîôûùçæœïüÉÈÊËÀÂÎÔÛÙÇÆŒÏÜ]\w+\b", texte.lower())
    if not mots:
        return False

    nb_fr = sum(1 for m in mots if m in MOTS_FR)
    nb_en = sum(1 for m in mots if m in MOTS_EN)

    total = nb_fr + nb_en
    if total == 0:
        # Aucun stop word détecté → vérification par caractères accentués
        nb_accents = sum(1 for c in texte if c in _ACCENTS_FR)
        return nb_accents / max(len(texte), 1) >= 0.015

    return nb_fr / total >= seuil


# ─────────────────────────────────────────────
#   API PUBLIQUE
# ─────────────────────────────────────────────


def verifier_et_marquer(
    nom_base: str,
    texte: str,
    dossier_sortie: str,
) -> bool:
    """Vérifie le texte d'une traduction et marque comme vérifié si c'est du français.

    Args:
        nom_base: Identifiant du fichier (sans extension).
        texte: Texte traduit complet.
        dossier_sortie: Dossier de sortie (pour le fichier d'état).

    Returns:
        True si le texte a été validé comme français.
    """
    if not texte or not texte.strip():
        return False

    if texte_est_francais(texte):
        marquer_verifie(nom_base, dossier_sortie)
        return True
    return False


def reinitialiser_verification(nom_base: str, dossier_sortie: str) -> None:
    """Retire un fichier de la liste des vérifiés (pour forcer une re-vérification)."""
    verifies = _charger_verifications(dossier_sortie)
    if nom_base in verifies:
        verifies.discard(nom_base)
        _sauvegarder_verifications(dossier_sortie, verifies)


# ─────────────────────────────────────────────
#   SCAN COMPLET DE TOUT LE DOSSIER DE SORTIE
# ─────────────────────────────────────────────

# Pattern pour extraire nom_base depuis un fichier de sortie.
# Exemples :
#   roman_part1_traduit_fr.pdf          → nom_base = "roman_part1"
#   roman_part1_traduit_fr_nllb.pdf     → nom_base = "roman_part1"
#   dossier/roman_traduit_fr_argos.txt  → nom_base = "dossier/roman"
_PATTERN_SORTIE = re.compile(
    r"^(.+?)_traduit_([a-z]{2,3})(?:_(argos|nllb))?\.(pdf|txt|md|docx)$",
    re.IGNORECASE,
)


def extraire_nom_base_de_sortie(chemin_relatif: str) -> str | None:
    """Extrait le *nom_base* (chemin relatif sans extension ni suffixe de traduction)
    depuis le nom d'un fichier de sortie.

    Exemples::

        "roman_part1_traduit_fr.pdf"       → "roman_part1"
        "dossier/roman_traduit_fr_nllb.txt" → "dossier/roman"
        "autre_fichier.txt"                 → None
    """
    nom_fichier = os.path.basename(chemin_relatif)
    m = _PATTERN_SORTIE.match(nom_fichier)
    if not m:
        return None

    # Reconstruire le chemin relatif du nom_base (dossier + nom sans suffixe)
    dossier = os.path.dirname(chemin_relatif)
    nom_base_fichier = m.group(1)
    if dossier:
        return os.path.join(dossier, nom_base_fichier).replace("\\", "/")
    return nom_base_fichier


def extraire_texte_sortie(chemin: str, max_caracteres: int = 10000) -> str:
    """Extrait le texte d'un fichier de sortie (PDF, TXT, MD, DOCX)
    pour vérification.

    Args:
        chemin: Chemin absolu du fichier de sortie.
        max_caracteres: Nombre max de caractères à extraire.

    Returns:
        Texte extrait (tronqué si nécessaire).
    """
    ext = os.path.splitext(chemin)[1].lower()
    texte = ""

    if ext in (".txt", ".md"):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                texte = f.read()
        except (IOError, UnicodeDecodeError):
            return ""

    elif ext == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(chemin) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        texte += t + "\n"
                    if len(texte) >= max_caracteres:
                        break
        except Exception:
            return ""

    elif ext == ".docx":
        try:
            from docx import Document  # type: ignore[import-untyped]
            doc = Document(chemin)
            for para in doc.paragraphs:
                texte += para.text + "\n"
                if len(texte) >= max_caracteres:
                    break
        except ImportError:
            return ""
        except Exception:
            return ""

    return texte[:max_caracteres]


def scanner_dossier_sortie(
    dossier_sortie: str,
    dossier_source: str | None = None,
    dossier_checkpoints: str | None = None,
    dossier_cache_extraction: str | None = None,
    langue_cible: str = "fr",
    on_log: Callable | None = None,
) -> tuple[int, int]:
    """Analyse tous les fichiers présents dans le dossier de sortie,
    vérifie qu'ils sont bien en français, et supprime ceux qui ne le sont pas
    pour qu'ils soient retraduits au prochain passage.

    Args:
        dossier_sortie: Chemin du dossier contenant les fichiers traduits.
        dossier_source: Chemin du dossier source (pour retrouver le fichier
            original et le checkpoint). Si None, vérification depuis le
            fichier de sortie uniquement.
        dossier_checkpoints: Chemin du dossier des checkpoints.
            Si None, on ne vérifie pas depuis les checkpoints.
        dossier_cache_extraction: Chemin du dossier du cache d'extraction.
            Non utilisé directement, sert pour la cohérence.
        langue_cible: Code de la langue cible (ex: "fr").
        on_log: Fonction de log optionnelle.

    Returns:
        Tuple (nb_verifies, nb_supprimes).
    """
    if not os.path.isdir(dossier_sortie):
        return 0, 0

    verifies = _charger_verifications(dossier_sortie)
    nb_verifies = 0
    nb_supprimes = 0
    fichiers_trouves: list[tuple[str, str]] = []  # (nom_base, chemin_complet)

    # 1. Collecter tous les fichiers de sortie
    for dirpath, _dirnames, filenames in os.walk(dossier_sortie):
        # Ignorer .edits/
        if ".edits" in dirpath.split(os.sep):
            continue
        for f in filenames:
            chemin_rel = os.path.relpath(os.path.join(dirpath, f), dossier_sortie)
            nom_base = extraire_nom_base_de_sortie(chemin_rel)
            if nom_base is not None:
                fichiers_trouves.append((nom_base, os.path.join(dirpath, f)))

    if not fichiers_trouves:
        return 0, 0

    for nom_base, chemin_complet in fichiers_trouves:
        if nom_base in verifies:
            continue  # déjà vérifié

        texte = ""

        # 2. Essayer d'abord depuis le checkpoint
        if dossier_checkpoints and os.path.isdir(dossier_checkpoints):
            try:
                from moteur.utils import charger_checkpoint
                pages_traduites, _ = charger_checkpoint(nom_base)
                if pages_traduites:
                    texte = "\n".join(
                        pages_traduites[str(i)]
                        for i in range(len(pages_traduites))
                        if str(i) in pages_traduites
                    )
            except Exception:
                pass

        # 3. Sinon, extraire depuis le fichier lui-même
        if not texte.strip():
            texte = extraire_texte_sortie(chemin_complet)

        if not texte.strip():
            # Impossible de lire le texte → on le garde (prudent)
            continue

        # 4. Vérifier la langue
        if texte_est_francais(texte):
            marquer_verifie(nom_base, dossier_sortie)
            nb_verifies += 1
            if on_log:
                on_log(f"  ✅ Vérifié : {chemin_complet}")
        else:
            # Pas en français → supprimer pour retraduction
            try:
                os.remove(chemin_complet)
                nb_supprimes += 1
                if on_log:
                    on_log(f"  ♻️ Retraduction (non français) : {chemin_complet}")
                # Supprimer aussi le checkpoint s'il existe
                if dossier_checkpoints:
                    try:
                        from moteur.utils import supprimer_checkpoint
                        supprimer_checkpoint(nom_base)
                    except Exception:
                        pass
            except OSError as e:
                if on_log:
                    on_log(f"  ⚠️ Impossible de supprimer {chemin_complet} : {e}")

    if nb_verifies or nb_supprimes:
        if on_log:
            on_log(f"  📊 Bilan : {nb_verifies} vérifié(s), {nb_supprimes} supprimé(s)")

    return nb_verifies, nb_supprimes


# ─────────────────────────────────────────────
#   REGISTRE DES FICHIERS SOURCE (anti-doublons)
# ─────────────────────────────────────────────
#
# Empêche de retraduire un fichier déjà traduit même si son nom change.
# Empreinte = hash(fichier_source) → {nom_base, sortie, horodatage}

FICHIER_REGISTRE = "source_registry.json"


def _registry_path(dossier_sortie: str) -> str:
    """Chemin du fichier registre (dans le dossier de sortie)."""
    return os.path.join(dossier_sortie, FICHIER_REGISTRE)


def _charger_registry(dossier_sortie: str) -> dict[str, dict]:
    """Charge le registre des fichiers source déjà traduits."""
    chemin = _registry_path(dossier_sortie)
    if os.path.exists(chemin):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _sauvegarder_registry(dossier_sortie: str, registry: dict[str, dict]) -> None:
    """Sauvegarde le registre des fichiers source."""
    chemin = _registry_path(dossier_sortie)
    try:
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"⚠️ Impossible d'écrire le registre {chemin} : {e}")


def empreinte_fichier(chemin: str) -> str | None:
    """Calcule une empreinte rapide d'un fichier.

    Utilise la taille + le début (64 Ko) + la fin (64 Ko) + l'extension
    pour identifier un fichier sans le lire entièrement.

    Args:
        chemin: Chemin absolu du fichier.

    Returns:
        Empreinte hexadécimale, ou None si erreur.
    """
    try:
        import hashlib
        taille = os.path.getsize(chemin)
        ext = os.path.splitext(chemin)[1].lower()
        h = hashlib.sha256()
        h.update(f"{taille}:{ext}".encode())
        with open(chemin, "rb") as f:
            debut = f.read(65536)          # 64 Ko début
            h.update(debut)
            if taille > 131072:
                f.seek(-65536, 2)          # 64 Ko fin (si fichier > 128 Ko)
                fin = f.read(65536)
                h.update(fin)
        return h.hexdigest()
    except (IOError, OSError):
        return None


def fichier_deja_traduit(chemin_source: str, dossier_sortie: str) -> str | None:
    """Vérifie si un fichier source (par empreinte) a déjà été traduit.

    Args:
        chemin_source: Chemin du fichier source à vérifier.
        dossier_sortie: Dossier contenant les traductions.

    Returns:
        Le *nom_base* enregistré si déjà traduit, None sinon.
    """
    emp = empreinte_fichier(chemin_source)
    if not emp:
        return None
    registry = _charger_registry(dossier_sortie)
    entree = registry.get(emp)
    if entree is None:
        return None
    # Vérifier que le fichier de sortie existe encore
    sortie = entree.get("sortie", "")
    if sortie and os.path.exists(sortie):
        return entree.get("nom_base")
    # La sortie a été supprimée → retraduire
    return None


def enregistrer_traduction(
    chemin_source: str,
    nom_base: str,
    sortie_path: str,
    dossier_sortie: str,
) -> None:
    """Enregistre un fichier source comme traduit dans le registre.

    Args:
        chemin_source: Chemin du fichier source original.
        nom_base: Identifiant du fichier (sans extension).
        sortie_path: Chemin du fichier de sortie généré.
        dossier_sortie: Dossier de sortie (pour le fichier registre).
    """
    emp = empreinte_fichier(chemin_source)
    if not emp:
        return
    registry = _charger_registry(dossier_sortie)
    import time as _time
    registry[emp] = {
        "nom_base": nom_base,
        "sortie": sortie_path,
        "fichier": os.path.basename(chemin_source),
        "timestamp": _time.time(),
    }
    _sauvegarder_registry(dossier_sortie, registry)
