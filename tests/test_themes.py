#!/usr/bin/env python3
"""
Tests unitaires pour le système de thèmes.
"""

from themes import THEMES, THEME_NAMES, DEFAULT_THEME, get

# Clés communes attendues dans chaque thème
_KEYS_COMMUNES = {"bg", "card", "card2", "fg", "muted",
                  "accent", "accent_h",
                  "green", "green_h",
                  "red", "red_h",
                  "yellow", "log_bg", "name"}


# ─────────────────────────────────────────────
#   PRÉSENCE DES CLÉS
# ─────────────────────────────────────────────

def test_all_themes_have_keys():
    """Chaque thème doit posséder toutes les clés communes (bg, card, fg, accent, etc.)."""
    for nom, palette in THEMES.items():
        manquantes = _KEYS_COMMUNES - set(palette.keys())
        assert not manquantes, \
            f"Le thème '{nom}' n'a pas les clés : {manquantes}"


def test_all_themes_have_name():
    """La clé 'name' de chaque thème doit correspondre à sa clé dans THEMES."""
    for nom, palette in THEMES.items():
        assert palette["name"] == nom, \
            f"name='{palette['name']}' ne correspond pas à la clé '{nom}'"


# ─────────────────────────────────────────────
#   THÈME PAR DÉFAUT
# ─────────────────────────────────────────────

def test_default_theme_exists():
    """DEFAULT_THEME doit être une clé valide dans THEMES."""
    assert DEFAULT_THEME in THEMES, \
        f"DEFAULT_THEME='{DEFAULT_THEME}' n'est pas dans THEMES"
    # Vérifier que le thème par défaut a bien toutes ses clés
    assert _KEYS_COMMUNES.issubset(THEMES[DEFAULT_THEME].keys())


# ─────────────────────────────────────────────
#   get() RETOURNE UNE COPIE
# ─────────────────────────────────────────────

def test_get_returns_copy():
    """get() doit retourner un dict modifiable sans affecter l'original."""
    theme_original = THEMES[DEFAULT_THEME]
    theme_copie = get()

    # La copie doit être un dict différent
    assert theme_copie is not theme_original

    # Modifier la copie ne doit pas affecter l'original
    theme_copie["bg"] = "#FFFFFF"
    assert THEMES[DEFAULT_THEME]["bg"] != "#FFFFFF"


def test_get_with_name():
    """get('Nord') doit retourner le thème Nord."""
    nord = get("Nord")
    assert nord["name"] == "Nord"
    assert nord["bg"] == "#2e3440"


def test_get_with_invalid_name():
    """get() avec un nom invalide doit retourner le thème par défaut."""
    theme = get("Inexistant")
    assert theme["name"] == DEFAULT_THEME


# ─────────────────────────────────────────────
#   THEME_NAMES
# ─────────────────────────────────────────────

def test_list_names():
    """THEME_NAMES doit être égal à list(THEMES.keys())."""
    assert THEME_NAMES == list(THEMES.keys())


def test_list_names_contains_all():
    """THEME_NAMES doit contenir tous les noms de thèmes."""
    for nom in THEMES:
        assert nom in THEME_NAMES
    assert len(THEME_NAMES) == len(THEMES)
