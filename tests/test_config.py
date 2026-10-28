#!/usr/bin/env python3
"""
Tests unitaires pour la configuration du moteur (ConfigMoteur).
"""

import pytest
from moteur.config import ConfigMoteur, FORMATS_EXPORT_VALIDES


# ─────────────────────────────────────────────
#   CONFIGURATION PAR DÉFAUT
# ─────────────────────────────────────────────

def test_default_config():
    """Les valeurs par défaut de ConfigMoteur doivent être valides."""
    config = ConfigMoteur()
    # Ne doit pas lever d'exception
    assert config.langue_source == "en"
    assert config.langue_cible == "fr"
    assert config.format_export == "pdf"
    assert config.nb_threads_trad == 3
    assert config.nb_threads_pdf == 2
    assert config.taille_bloc == 2000
    assert config.rate_limit == 3
    assert config.dossier_source == "./pdfs_originaux"
    assert config.dossier_sortie == "./pdfs_traduits"


# ─────────────────────────────────────────────
#   FORMAT D'EXPORT INVALIDE
# ─────────────────────────────────────────────

def test_invalid_format():
    """Un format_export invalide doit lever une AssertionError."""
    with pytest.raises(AssertionError):
        ConfigMoteur(format_export="html")
    with pytest.raises(AssertionError):
        ConfigMoteur(format_export="xml")
    with pytest.raises(AssertionError):
        ConfigMoteur(format_export="")


# ─────────────────────────────────────────────
#   NB_THREADS À ZÉRO
# ─────────────────────────────────────────────

def test_zero_threads():
    """nb_threads_trad = 0 ou nb_threads_pdf = 0 doit lever une AssertionError."""
    with pytest.raises(AssertionError, match="nb_threads_trad"):
        ConfigMoteur(nb_threads_trad=0)
    with pytest.raises(AssertionError, match="nb_threads_pdf"):
        ConfigMoteur(nb_threads_pdf=0)


def test_zero_taille_bloc():
    """taille_bloc = 0 doit lever une AssertionError."""
    with pytest.raises(AssertionError, match="taille_bloc"):
        ConfigMoteur(taille_bloc=0)


# ─────────────────────────────────────────────
#   APPLIQUER_DICT
# ─────────────────────────────────────────────

def test_appliquer_dict():
    """appliquer_dict() doit mettre à jour les champs de la configuration."""
    config = ConfigMoteur()
    config.appliquer_dict({
        "LANGUE_SOURCE": "de",
        "LANGUE_CIBLE": "it",
        "FORMAT_EXPORT": "txt",
        "NB_THREADS_TRAD": 10,
    })
    assert config.langue_source == "de"
    assert config.langue_cible == "it"
    assert config.format_export == "txt"
    assert config.nb_threads_trad == 10


def test_appliquer_dict_ignores_none():
    """appliquer_dict() doit ignorer les valeurs None."""
    config = ConfigMoteur()
    config.appliquer_dict({"LANGUE_SOURCE": None, "LANGUE_CIBLE": "es"})
    assert config.langue_source == "en"  # inchangé car None
    assert config.langue_cible == "es"


def test_appliquer_dict_empty():
    """appliquer_dict() avec un dict vide ou None ne doit rien modifier."""
    config = ConfigMoteur()
    original = config.langue_source
    config.appliquer_dict(None)
    assert config.langue_source == original
    config.appliquer_dict({})
    assert config.langue_source == original


# ─────────────────────────────────────────────
#   EXPORTER_DICT
# ─────────────────────────────────────────────

def test_exporter_dict():
    """exporter_dict() doit retourner un dictionnaire avec des clés en MAJUSCULES."""
    config = ConfigMoteur()
    d = config.exporter_dict()
    assert isinstance(d, dict)
    assert "DOSSIER_SOURCE" in d
    assert "LANGUE_SOURCE" in d
    assert "LANGUE_CIBLE" in d
    assert "FORMAT_EXPORT" in d
    assert "NB_THREADS_TRAD" in d
    assert "STYLES_PDF" in d
    # Vérifier que les clés sont en MAJUSCULES
    for cle in d:
        assert cle == cle.upper(), f"La clé '{cle}' n'est pas en MAJUSCULES"


def test_exporter_dict_values():
    """Les valeurs exportées doivent correspondre aux attributs de l'instance."""
    config = ConfigMoteur(langue_source="pt", langue_cible="fr", format_export="md")
    d = config.exporter_dict()
    assert d["LANGUE_SOURCE"] == "pt"
    assert d["LANGUE_CIBLE"] == "fr"
    assert d["FORMAT_EXPORT"] == "md"
    assert d["STYLES_PDF"] is not None


# ─────────────────────────────────────────────
#   CONFIGURATION VALIDE
# ─────────────────────────────────────────────

def test_valid_config():
    """Une configuration valide doit pouvoir être créée et validée sans exception."""
    config = ConfigMoteur(
        dossier_source="/tmp/src",
        dossier_sortie="/tmp/dst",
        langue_source="en",
        langue_cible="fr",
        format_export="pdf",
        nb_threads_trad=10,
        nb_threads_pdf=3,
        taille_bloc=1000,
        rate_limit=20,
    )
    # __post_init__ s'exécute automatiquement
    # On vérifie juste que tout est OK
    assert config.nb_threads_trad == 10
    assert config.format_export == "pdf"


def test_valid_export_formats():
    """Tous les formats dans FORMATS_EXPORT_VALIDES doivent être acceptés."""
    for fmt in FORMATS_EXPORT_VALIDES:
        config = ConfigMoteur(format_export=fmt)
        assert config.format_export == fmt
