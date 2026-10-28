#!/usr/bin/env python3
"""
Tests des checkpoints versionnés : métadonnées, hashes et robustesse.
"""

import json

import pytest

from moteur import config as cfg
from moteur import utils


@pytest.fixture
def dossier_cp(tmp_path):
    cfg.configurer({
        "DOSSIER_CHECKPOINTS": str(tmp_path / "checkpoints"),
        "LANGUE_CIBLE": "fr",
    })
    yield tmp_path / "checkpoints"
    cfg.configurer()


def test_hash_texte_stable():
    assert utils.hash_texte("Bonjour") == utils.hash_texte("  Bonjour  ")
    assert utils.hash_texte("Bonjour") != utils.hash_texte("Bonsoir")
    assert len(utils.hash_texte("x")) == 16


def test_sauvegarde_puis_chargement(dossier_cp):
    pages = {"0": "Première page", "1": "Deuxième page"}
    hashes = {"0": utils.hash_texte("First page"), "1": utils.hash_texte("Second page")}
    utils.sauvegarder_checkpoint("roman", pages, 2, hashes, langue_verifiee=True)

    relues, total = utils.charger_checkpoint("roman")
    assert relues == pages
    assert total == 2


def test_metadonnees_enregistrees(dossier_cp):
    hashes = {"0": utils.hash_texte("Source")}
    utils.sauvegarder_checkpoint("roman", {"0": "Trad"}, 1, hashes, langue_verifiee=True)

    meta = utils.charger_metadonnees_checkpoint("roman")
    assert meta["version"] == utils.CHECKPOINT_VERSION
    assert meta["langue_verifiee"] is True
    assert meta["langue_cible"] == "fr"
    assert meta["hash_original"] == hashes
    assert meta["maj"] > 0


def test_checkpoint_illisible_ne_leve_pas(dossier_cp):
    dossier_cp.mkdir(parents=True, exist_ok=True)
    (dossier_cp / "casse.json").write_text("{ pas du json", encoding="utf-8")

    assert utils.charger_checkpoint("casse") == ({}, 0)
    assert utils.charger_metadonnees_checkpoint("casse") == {}


def test_metadonnees_checkpoint_absent(dossier_cp):
    assert utils.charger_metadonnees_checkpoint("jamais_vu") == {}


def test_ancien_format_reste_lisible(dossier_cp):
    dossier_cp.mkdir(parents=True, exist_ok=True)
    (dossier_cp / "ancien.json").write_text(
        json.dumps({"pages_traduites": {"0": "texte"}, "total_pages": 1}),
        encoding="utf-8",
    )

    pages, total = utils.charger_checkpoint("ancien")
    assert pages == {"0": "texte"}
    assert total == 1
    meta = utils.charger_metadonnees_checkpoint("ancien")
    assert meta["version"] == 1
    assert meta["langue_verifiee"] is False


def test_ecriture_atomique_ne_laisse_pas_de_fichier_temporaire(dossier_cp):
    utils.sauvegarder_checkpoint("roman", {"0": "a"}, 1)
    fichiers = {p.name for p in dossier_cp.iterdir()}
    assert fichiers == {"roman.json"}


def test_supprimer_checkpoint(dossier_cp):
    utils.sauvegarder_checkpoint("roman", {"0": "a"}, 1)
    utils.supprimer_checkpoint("roman")
    assert utils.charger_checkpoint("roman") == ({}, 0)
