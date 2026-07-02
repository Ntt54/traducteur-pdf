#!/usr/bin/env python3
"""
Tests unitaires pour les helpers d'export (nom de sortie, taille de page).
Ces tests ne génèrent aucun fichier.
"""

from traduire_pdfs_v2 import _nom_sortie
from moteur.config import configurer, get_config, STYLES_PDF_PAR_DEFAUT
from moteur.exportateur import _get_page_size
from reportlab.lib.pagesizes import A4, letter


# ─────────────────────────────────────────────
#   NOM DE FICHIER DE SORTIE
# ─────────────────────────────────────────────

def _reset_config():
    """Remet la config dans un état par défaut connu."""
    configurer({"LANGUE_CIBLE": "fr"})


def test_nom_sortie_pdf():
    """_nom_sortie('doc.pdf', 'pdf') → 'doc_traduit_fr.pdf'."""
    _reset_config()
    assert _nom_sortie("doc.pdf", "pdf") == "doc_traduit_fr.pdf"


def test_nom_sortie_txt():
    """_nom_sortie('doc.pdf', 'txt') → 'doc_traduit_fr.txt'."""
    _reset_config()
    assert _nom_sortie("doc.pdf", "txt") == "doc_traduit_fr.txt"


def test_nom_sortie_md():
    """_nom_sortie('doc.pdf', 'md') → 'doc_traduit_fr.md'."""
    _reset_config()
    assert _nom_sortie("doc.pdf", "md") == "doc_traduit_fr.md"


def test_nom_sortie_docx():
    """_nom_sortie('doc.pdf', 'docx') → 'doc_traduit_fr.docx'."""
    _reset_config()
    assert _nom_sortie("doc.pdf", "docx") == "doc_traduit_fr.docx"


def test_nom_sortie_with_path():
    """_nom_sortie doit fonctionner avec un chemin relatif."""
    _reset_config()
    result = _nom_sortie("sous-dossier/rapport.pdf", "pdf")
    assert result == "sous-dossier/rapport_traduit_fr.pdf"


def test_nom_sortie_langue_cible():
    """Le suffixe de langue doit correspondre à langue_cible configurée."""
    configurer({"LANGUE_CIBLE": "de"})
    assert _nom_sortie("doc.pdf", "pdf") == "doc_traduit_de.pdf"


# ─────────────────────────────────────────────
#   TAILLE DE PAGE
# ─────────────────────────────────────────────

def test_page_size_a4():
    """_get_page_size() avec page_size='A4' doit retourner A4."""
    configurer({"STYLES_PDF": dict(STYLES_PDF_PAR_DEFAUT, page_size="A4")})
    assert _get_page_size() == A4


def test_page_size_letter():
    """_get_page_size() avec page_size='letter' doit retourner letter."""
    configurer({"STYLES_PDF": dict(STYLES_PDF_PAR_DEFAUT, page_size="letter")})
    assert _get_page_size() == letter


def test_page_size_default():
    """_get_page_size() sans config explicite doit retourner A4 (valeur par défaut)."""
    configurer({"STYLES_PDF": dict(STYLES_PDF_PAR_DEFAUT)})
    assert get_config().styles_pdf.get("page_size") == "A4"
    assert _get_page_size() == A4
