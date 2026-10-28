"""
Tests du correctif anti-fallback : un bloc qui ne peut pas être traduit
doit lever TraductionEchoueeError (et non retourner silencieusement le texte
source en anglais, ce qui polluait le checkpoint et produisait des PDF en anglais).
"""

import sys
import types

import pytest
from unittest.mock import patch

import moteur.traducteur as trad
from moteur.traducteur import (
    TraductionEchoueeError,
    traduire_bloc,
    traduire_bloc_offline,
)


@pytest.fixture
def argos_factice(monkeypatch):
    """Fournit un module ``argostranslate`` minimal quand il n'est pas installé.

    Le mode hors ligne est optionnel : les tests doivent rester exécutables
    sur une machine sans Argos.
    """
    if getattr(trad, "argostranslate", None) is not None:
        return trad.argostranslate
    faux = types.ModuleType("argostranslate")
    faux.translate = types.SimpleNamespace(translate=lambda *a, **k: "")
    faux.package = types.SimpleNamespace(get_installed_packages=lambda: [])
    monkeypatch.setattr(trad, "argostranslate", faux, raising=False)
    return faux


@pytest.fixture(autouse=True)
def config_pipeline():
    """Config minimal avec peu d'essais pour des tests rapides."""
    from moteur.config import configurer
    configurer({
        "MAX_RETRIES": 2,
        "BACKOFF_CAP": 1,
        "PACE_MIN": 0,
        "PACE_MAX": 0,
        "RATE_LIMIT": 2,
        "LANGUE_SOURCE": "en",
        "LANGUE_CIBLE": "fr",
    })
    yield
    configurer()


class _FauxTraducteur:
    """Traducteur qui échoue toujours."""

    def translate(self, bloc):
        raise Exception("429 Too Many Requests")


class _FauxTraducteurVide:
    """Traducteur qui renvoie un résultat vide."""

    def translate(self, bloc):
        return ""


def test_traduire_bloc_leve_sur_echec(config_pipeline):
    """Quand Google échoue après tous les essais, on lève une erreur
    au lieu de retourner le bloc anglais non traduit."""
    from moteur.traducteur import _est_erreur_reseau, internet_disponible
    with patch("moteur.traducteur.internet_disponible", return_value=True), \
         patch("moteur.traducteur.get_next_proxy", return_value=None):
        with pytest.raises(TraductionEchoueeError):
            traduire_bloc(
                "Jake bent his back as he avoided a wooden spear.",
                "en", "fr", _FauxTraducteur(),
            )


def test_traduire_bloc_leve_sur_reponse_vide(config_pipeline):
    """Une réponse vide de Google ne doit pas être traitée comme une traduction."""
    from moteur.traducteur import internet_disponible
    with patch("moteur.traducteur.internet_disponible", return_value=True), \
         patch("moteur.traducteur.get_next_proxy", return_value=None):
        with pytest.raises(TraductionEchoueeError):
            traduire_bloc(
                "Some English text to translate.",
                "en", "fr", _FauxTraducteurVide(),
            )


def test_traduire_bloc_offline_leve_sur_echec(config_pipeline, argos_factice):
    """Argos en échec doit lever TraductionEchoueeError, pas retourner le bloc."""
    with patch.object(argos_factice.translate, "translate",
                      side_effect=Exception("modèle non chargé")):
        with pytest.raises(TraductionEchoueeError):
            traduire_bloc_offline("Hello world", "en", "fr")


def test_traduire_bloc_offline_leve_sur_identique(config_pipeline, argos_factice):
    """Si Argos renvoie le texte source inchangé, on considère que c'est un échec."""
    with patch.object(argos_factice.translate, "translate",
                      return_value="Hello world"):
        with pytest.raises(TraductionEchoueeError):
            traduire_bloc_offline("Hello world", "en", "fr")
