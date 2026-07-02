#!/usr/bin/env python3
"""
Tests unitaires pour le module d'extraction et de nettoyage de texte.
"""

from moteur.extracteur import nettoyer_texte


# ─────────────────────────────────────────────
#   CID
# ─────────────────────────────────────────────

def test_nettoyer_cid():
    """Les références (cid:N) doivent être supprimées du texte."""
    texte = "Voici un texte avec (cid:123) une référence et (cid:456) une autre."
    resultat = nettoyer_texte(texte)
    assert "(cid:" not in resultat
    assert "une référence" in resultat
    assert "une autre" in resultat


# ─────────────────────────────────────────────
#   CARACTÈRES UNICODE SPÉCIAUX (zone privée)
# ─────────────────────────────────────────────

def test_nettoyer_unicode_special():
    """Les caractères Unicode de la zone privée (U+E000–U+F8FF) doivent être supprimés."""
    texte = "Bonjour\uE000 le\uF8FF monde\uE123!"
    resultat = nettoyer_texte(texte)
    assert "\uE000" not in resultat
    assert "\uF8FF" not in resultat
    assert "\uE123" not in resultat
    assert "Bonjour le monde!" in resultat


# ─────────────────────────────────────────────
#   DÉTECTION DE CHAPITRES
# ─────────────────────────────────────────────

def test_chapter_detection():
    """Un titre 'Chapter N ...' doit être formaté en 'Chapter N — ...'."""
    texte = "Chapter 1 The Beginning"
    resultat = nettoyer_texte(texte)
    assert "Chapter 1" in resultat
    assert "\u2014" in resultat  # em dash
    assert "The Beginning" in resultat


# ─────────────────────────────────────────────
#   FUSION DE LIGNES
# ─────────────────────────────────────────────

def test_fusion_lignes():
    """Deux lignes consécutives sans ponctuation finale doivent être fusionnées."""
    texte = "Ceci est une longue phrase qui\ncontinue sur la ligne suivante"
    resultat = nettoyer_texte(texte)
    assert "continue sur la ligne suivante" in resultat
    # Les deux lignes doivent être dans le même paragraphe
    assert "Ceci est une longue phrase qui continue sur la ligne suivante" in resultat


# ─────────────────────────────────────────────
#   SÉPARATEURS
# ─────────────────────────────────────────────

def test_separators_removed():
    """Les lignes composées uniquement de séparateurs (---, ___...) doivent être supprimées."""
    texte = "Texte avant séparateur\n---\nTexte après séparateur"
    resultat = nettoyer_texte(texte)
    assert "---" not in resultat
    assert "___" not in resultat
    assert "Texte avant séparateur" in resultat
    assert "Texte après séparateur" in resultat


def test_separators_double_hyphens_removed():
    """Les lignes de tirets longs (━, ─, etc.) doivent aussi être supprimées."""
    texte = "Début\n───────\nFin"
    resultat = nettoyer_texte(texte)
    assert "───────" not in resultat
    assert "Début" in resultat
    assert "Fin" in resultat


# ─────────────────────────────────────────────
#   TEXTE VIDE
# ─────────────────────────────────────────────

def test_empty_result():
    """Un texte vide ou composé uniquement d'espaces doit retourner une chaîne vide."""
    assert nettoyer_texte("") == ""
    assert nettoyer_texte("   ") == ""
    assert nettoyer_texte("\n\n\n") == ""


# ─────────────────────────────────────────────
#   PARAGRAPHES PRÉSERVÉS
# ─────────────────────────────────────────────

def test_paragraph_preserved():
    """Les paragraphes séparés par une double newline doivent être conservés."""
    texte = "Premier paragraphe. Il contient plusieurs phrases.\n\nDeuxième paragraphe. Il est séparé."
    resultat = nettoyer_texte(texte)
    assert "Premier paragraphe" in resultat
    assert "Deuxième paragraphe" in resultat
    # Vérifier que les deux paragraphes sont bien séparés
    assert "\n\n" in resultat
