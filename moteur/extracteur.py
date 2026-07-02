#!/usr/bin/env python3
"""
Extraction de texte depuis des PDF avec mise en cache et nettoyage.
"""

from __future__ import annotations

import os
import re
import json
from typing import Optional, Any

import pdfplumber

from . import config as cfg
from .utils import log_fixe


# ─────────────────────────────────────────────
#   CONSTANTES DE NETTOYAGE
# ─────────────────────────────────────────────

_RE_CHAP = re.compile(r'Chap[\uE000-\uF8FF\w]*\s+\d+')
_RE_CID = re.compile(r'\(cid:\d+\)')
_RE_SEP = re.compile(r'^[\s\-─━═—_*✦⋆°✩⊱⊰~|]{2,}$', re.MULTILINE)
_RE_SPECIAL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_RE_UNICODE = re.compile(r'[\uE000-\uF8FF]')
_RE_FIN_PHRASE = re.compile(r'[.!?…»"\u201d\u2019]\s*$')
_RE_DEBUT_PARA = re.compile(r'^([«"\u201c\'\-–—\[\(]|Chapter|Chap)')


def nettoyer_titre_chapitre(ligne: str) -> Optional[str]:
    """Détecte et nettoie les lignes de titre de chapitre."""
    if _RE_CHAP.search(ligne):
        num_match = re.search(r'(\d+)', ligne)
        if not num_match:
            return _RE_UNICODE.sub('', ligne).strip()
        num = num_match.group(1)
        suite = _RE_UNICODE.sub('', ligne)
        suite = re.sub(r'Chap\w*\s+\d+\s*', '', suite)
        suite = re.sub(r'\s+', ' ', suite).strip()
        if suite:
            return f'Chapter {num} \u2014 {suite}'
        return f'Chapter {num}'
    return None


def nettoyer_texte(texte: str) -> str:
    """Nettoie le texte brut extrait d'un PDF : CID, Unicode, séparateurs, fusion de lignes."""
    texte = _RE_SPECIAL.sub('', texte)
    texte = _RE_CID.sub('', texte)
    texte = _RE_SEP.sub('', texte)
    lignes = texte.split('\n')
    resultat: list[str] = []
    tampon = ""
    for ligne in lignes:
        ligne = ligne.rstrip()
        if not ligne:
            if tampon:
                resultat.append(tampon)
                tampon = ""
            resultat.append("")
            continue
        titre = nettoyer_titre_chapitre(ligne)
        if titre:
            if tampon:
                resultat.append(tampon)
                tampon = ""
            resultat.append("")
            resultat.append(titre)
            resultat.append("")
            continue
        ligne = _RE_UNICODE.sub('', ligne).strip()
        if not ligne:
            continue
        if not tampon:
            tampon = ligne
        else:
            coller = (
                not _RE_FIN_PHRASE.search(tampon)
                and not _RE_DEBUT_PARA.match(ligne)
                and len(ligne) > 10
            )
            if coller:
                tampon += " " + ligne.lstrip()
            else:
                resultat.append(tampon)
                tampon = ligne
    if tampon:
        resultat.append(tampon)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(resultat)).strip()


# ─────────────────────────────────────────────
#   EXTRACTION PDF
# ─────────────────────────────────────────────

def extraire_texte_pdf(chemin_pdf: str) -> list[str]:
    """Extrait le texte de chaque page d'un PDF sous forme de liste."""
    pages: list[str] = []
    with pdfplumber.open(chemin_pdf) as pdf:
        for page in pdf.pages:
            texte = page.extract_text() or ""
            pages.append(nettoyer_texte(texte))
    return pages


# ─────────────────────────────────────────────
#   CACHE D'EXTRACTION (fichiers JSON)
# ─────────────────────────────────────────────

def chemin_cache_extraction(nom_base: str) -> str:
    """Retourne le chemin du fichier cache d'extraction."""
    conf = cfg.get_config()
    cc = os.path.join(conf.dossier_cache_extraction, nom_base + ".json")
    os.makedirs(os.path.dirname(cc), exist_ok=True)
    return cc


def charger_cache_extraction(nom_base: str) -> Optional[list[str]]:
    """Charge le texte extrait depuis le cache."""
    chemin = chemin_cache_extraction(nom_base)
    if os.path.exists(chemin):
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def sauvegarder_cache_extraction(nom_base: str, pages_texte: list[str]) -> None:
    """Sauvegarde le texte extrait dans le cache."""
    chemin = chemin_cache_extraction(nom_base)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(pages_texte, f, ensure_ascii=False, indent=2)
