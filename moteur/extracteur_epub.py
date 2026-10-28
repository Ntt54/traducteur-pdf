#!/usr/bin/env python3
"""
Extraction de texte depuis des fichiers EPUB avec découpage automatique en parties
d'environ 100 pages imprimées, pour alimenter le pipeline de traduction.

Une "partie" correspond à ~30 000 mots (≈ 100 pages papier de 300 mots chacune).
Le découpage s'effectue aux limites des chapitres pour préserver l'intégrité du texte.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from . import config as cfg
from .utils import log_fixe

# ── Dépendances optionnelles ──

try:
    import ebooklib
    from ebooklib import epub
    HAS_EPUBLIB = True
except ImportError:
    HAS_EPUBLIB = False

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False

# ── Constantes de découpage ──

# Une page papier standard contient ~300 mots en moyenne
MOTS_PAR_PAGE = 300
# Nombre de pages souhaité par partie (≈ 100)
PAGES_PAR_PARTIE = 100
# Seuil en mots pour déclencher une nouvelle partie
MOTS_PAR_PARTIE = MOTS_PAR_PAGE * PAGES_PAR_PARTIE  # 30 000


# ── Vérification de disponibilité ──

def epub_disponible() -> bool:
    """Vérifie si les bibliothèques EPUB sont installées."""
    return HAS_EPUBLIB and HAS_BEAUTIFULSOUP


def verification_epub() -> str | None:
    """Retourne un message d'erreur si une dépendance manque, sinon None."""
    if not HAS_EPUBLIB:
        return "ebooklib n'est pas installé. Commande : pip install ebooklib"
    if not HAS_BEAUTIFULSOUP:
        return "beautifulsoup4 n'est pas installé. Commande : pip install beautifulsoup4"
    return None


# ── Extraction du texte ──

def extraire_texte_epub(chemin_epub: str) -> list[str]:
    """
    Extrait le texte d'un fichier EPUB, chapitre par chapitre.

    Args:
        chemin_epub: Chemin absolu ou relatif vers le fichier .epub

    Returns:
        Liste de textes, un élément par document/chapitre
    """
    msg = verification_epub()
    if msg:
        raise ImportError(msg)

    book = epub.read_epub(chemin_epub)
    chapitres: list[str] = []

    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        try:
            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')

            # Supprime les éléments non-texte
            for tag in soup(['script', 'style', 'nav', 'navmap', 'svg']):
                tag.decompose()

            texte = soup.get_text(separator='\n')
            texte = _nettoyer_texte_epub(texte)
            if texte.strip():
                chapitres.append(texte)
        except Exception:
            continue

    return chapitres


def _nettoyer_texte_epub(texte: str) -> str:
    """
    Nettoie le texte brut extrait d'un EPUB :
    - Caractères de contrôle
    - Espacements excessifs
    - Lignes vides multiples
    """
    texte = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', texte)
    texte = re.sub(r'\n{3,}', '\n\n', texte)
    texte = re.sub(r'[ \t]+', ' ', texte)
    return texte.strip()


# ── Découpage en parties ──

def diviser_en_parties(
    chapitres: list[str],
    mots_par_partie: int = MOTS_PAR_PARTIE,
) -> list[list[str]]:
    """
    Divise les chapitres en groupes d'environ ``mots_par_partie`` mots chacun.

    Le découpage respecte les limites des chapitres : un chapitre n'est jamais
    coupé en deux. Si un chapitre dépasse à lui seul ``mots_par_partie`` mots,
    il forme une partie à lui seul.

    Args:
        chapitres: Liste de textes de chapitres
        mots_par_partie: Nombre cible de mots par partie (défaut: 30 000)

    Returns:
        Liste de parties, chaque partie étant une liste de textes de chapitres
    """
    parties: list[list[str]] = []
    partie_courante: list[str] = []
    mots_courants = 0

    for chapitre in chapitres:
        mots_chapitre = len(chapitre.split())

        # Si le chapitre est énorme à lui seul, il prend une partie entière
        if mots_chapitre >= mots_par_partie:
            # Finaliser la partie en cours si elle existe
            if partie_courante:
                parties.append(partie_courante)
                partie_courante = []
                mots_courants = 0
            parties.append([chapitre])
            continue

        # Si ajouter ce chapitre dépasse le seuil ET qu'on a du contenu
        if mots_courants + mots_chapitre > mots_par_partie and partie_courante:
            parties.append(partie_courante)
            partie_courante = [chapitre]
            mots_courants = mots_chapitre
        else:
            partie_courante.append(chapitre)
            mots_courants += mots_chapitre

    # Dernière partie
    if partie_courante:
        parties.append(partie_courante)

    return parties


# ── Point d'entrée pour le pipeline ──

def traiter_epub(chemin_epub: str, relatif: str = "") -> list[tuple[str, list[str]]]:
    """
    Traite un fichier EPUB complet : extraction + découpage en parties.

    Args:
        chemin_epub: Chemin absolu vers le fichier .epub
        relatif: Chemin relatif (pour le nom de base des parties)

    Returns:
        Liste de (nom_partie, pages_texte) où :
        - nom_partie : identifiant unique (ex: "dossier/roman/part1")
        - pages_texte : textes des chapitres de cette partie
    """
    nom_base = os.path.splitext(relatif if relatif else os.path.basename(chemin_epub))[0]

    chapitres = extraire_texte_epub(chemin_epub)
    if not chapitres:
        log_fixe(f" ⚠️ Aucun texte trouvé dans : {os.path.basename(chemin_epub)}")
        return []

    parties = diviser_en_parties(chapitres)
    total_mots = sum(len(c.split()) for c in chapitres)
    mots_par_partie = total_mots // len(parties) if parties else 0

    log_fixe(
        f" 📖 {nom_base} : {len(chapitres)} chapitres, "
        f"~{total_mots} mots → {len(parties)} partie(s) "
        f"(~{mots_par_partie} mots / ~{mots_par_partie // MOTS_PAR_PAGE} pages chaque)"
    )

    resultats = []
    nom_dossier = nom_base.replace(os.sep, "_")  # dossier unique pour ce roman
    for idx, pages in enumerate(parties, 1):
        nom_partie = f"{nom_dossier}/{nom_base}_part{idx}"
        resultats.append((nom_partie, pages))

    return resultats


def compter_parties_existantes(nom_base: str) -> int:
    """
    Combe le nombre de parties déjà en cache pour un EPUB.

    Cherche les fichiers ``extraction_cache/<dossier_roman>/<nom_base>_part*.json``
    dans un sous-dossier par roman.
    """
    conf = cfg.get_config()
    cache_dir = conf.dossier_cache_extraction
    nom_dossier = nom_base.replace(os.sep, "_")
    motif = os.path.join(cache_dir, nom_dossier, f"{nom_base}_part*.json")
    import glob
    fichiers = sorted(glob.glob(motif))
    return len(fichiers)


# ── Conversion EPUB → PDF (optionnel) ──

def convertir_epub_en_pdf(chemin_epub: str, chemin_sortie: str) -> str | None:
    """
    Convertit un fichier EPUB en PDF simple pour lecture.

    Utilise reportlab (déjà présent dans les dépendances) pour générer
    un PDF basique avec le texte extrait de l'EPUB.

    Args:
        chemin_epub: Chemin du fichier .epub source
        chemin_sortie: Chemin du fichier .pdf à créer

    Returns:
        Le chemin du PDF créé, ou None en cas d'erreur
    """
    try:
        from xml.sax.saxutils import escape as xml_escape
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

        chapitres = extraire_texte_epub(chemin_epub)
        if not chapitres:
            return None

        os.makedirs(os.path.dirname(chemin_sortie), exist_ok=True)

        doc = SimpleDocTemplate(
            chemin_sortie, pagesize=A4,
            rightMargin=2.5*cm, leftMargin=2.5*cm,
            topMargin=2.0*cm, bottomMargin=2.0*cm,
        )

        style_normal = ParagraphStyle(
            "N", fontName="Helvetica", fontSize=11,
            leading=16, spaceAfter=4,
        )
        style_titre = ParagraphStyle(
            "T", fontName="Helvetica-Bold", fontSize=14,
            leading=20, spaceAfter=8, spaceBefore=12,
        )

        contenu = []
        for chapitre in chapitres:
            lignes = chapitre.strip().split('\n')
            for i, ligne in enumerate(lignes):
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    escaped = xml_escape(ligne)
                    if i == 0 and len(ligne) < 100 and any(
                        tag in ligne.lower() for tag in ['chapter', 'chapitre', 'prologue', 'epilogue']
                    ):
                        contenu.append(Paragraph(escaped, style_titre))
                    else:
                        contenu.append(Paragraph(escaped, style_normal))
                    contenu.append(Spacer(1, 0.08*cm))
                except Exception:
                    pass
            contenu.append(Spacer(1, 0.3*cm))

        doc.build(contenu)
        log_fixe(f" \U0001f4c4 EPUB converti en PDF : {os.path.basename(chemin_sortie)}")
        return chemin_sortie

    except Exception as e:
        log_fixe(f" \u26a0\ufe0f Erreur conversion EPUB\u2192PDF ({os.path.basename(chemin_epub)}) : {e}")
        return None
