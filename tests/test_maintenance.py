#!/usr/bin/env python3
"""
Tests du module de maintenance : inventaire, purges et compactage.
"""

import os
import json
import time
import sqlite3

import pytest

from moteur import config as cfg
from moteur import maintenance as mnt


@pytest.fixture
def espace_travail(tmp_path):
    """Crée une arborescence de travail isolée et configure le moteur dessus."""
    source = tmp_path / "pdfs_originaux"
    sortie = tmp_path / "pdfs_traduits"
    extraction = tmp_path / "extraction_cache"
    checkpoints = tmp_path / "checkpoints"
    for d in (source, sortie, extraction, checkpoints):
        d.mkdir()

    base = tmp_path / "cache.db"
    conn = sqlite3.connect(base)
    conn.execute("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)",
                     [(f"cle{i}", f"valeur{i}") for i in range(50)])
    conn.commit()
    conn.close()

    cfg.configurer({
        "DOSSIER_SOURCE": str(source),
        "DOSSIER_SORTIE": str(sortie),
        "DOSSIER_CACHE_EXTRACTION": str(extraction),
        "DOSSIER_CHECKPOINTS": str(checkpoints),
        "CHEMIN_CACHE_TRAD": str(base),
    })
    yield tmp_path
    cfg.configurer()


def test_formater_taille():
    assert mnt.formater_taille(512) == "512.0 o"
    assert mnt.formater_taille(2048) == "2.0 Ko"
    assert mnt.formater_taille(5 * 1024 ** 2) == "5.0 Mo"


def test_inventaire_compte_les_artefacts(espace_travail):
    (espace_travail / "extraction_cache" / "a.json").write_text('["page"]')
    (espace_travail / "extraction_cache" / "b.json").write_text('["page"]')

    inv = mnt.inventaire()
    assert inv["extraction"]["nb"] == 2
    assert inv["extraction"]["taille"] > 0
    assert inv["cache_traduction"]["nb"] == 50


def test_purger_cache_extraction_tout(espace_travail):
    dossier = espace_travail / "extraction_cache"
    for nom in ("a.json", "b.json", "c.json"):
        (dossier / nom).write_text('["contenu"]')

    nb, octets = mnt.purger_cache_extraction(jours=None)
    assert nb == 3
    assert octets > 0
    assert list(dossier.iterdir()) == []


def test_purger_cache_extraction_respecte_l_age(espace_travail):
    dossier = espace_travail / "extraction_cache"
    recent = dossier / "recent.json"
    ancien = dossier / "ancien.json"
    recent.write_text('["a"]')
    ancien.write_text('["b"]')
    vieux = time.time() - 60 * 86400
    os.utime(ancien, (vieux, vieux))

    nb, _ = mnt.purger_cache_extraction(jours=30)
    assert nb == 1
    assert recent.exists()
    assert not ancien.exists()


def test_purger_checkpoints_orphelins(espace_travail):
    checkpoints = espace_travail / "checkpoints"
    (checkpoints / "vivant.json").write_text("{}")
    (checkpoints / "orphelin.json").write_text("{}")
    (espace_travail / "pdfs_originaux" / "vivant.pdf").write_bytes(b"%PDF-1.4")

    nb, _ = mnt.purger_checkpoints(seulement_orphelins=True)
    assert nb == 1
    assert (checkpoints / "vivant.json").exists()
    assert not (checkpoints / "orphelin.json").exists()


def test_vider_cache_traduction(espace_travail):
    nb = mnt.vider_cache_traduction()
    assert nb == 50
    assert mnt.inventaire()["cache_traduction"]["nb"] == 0


def test_compacter_cache_traduction_retourne_les_tailles(espace_travail):
    avant, apres = mnt.compacter_cache_traduction()
    assert avant > 0
    assert apres > 0


def test_checkpoints_suspects_detecte_incomplet(espace_travail):
    checkpoints = espace_travail / "checkpoints"
    (checkpoints / "partiel.json").write_text(json.dumps({
        "version": 2,
        "pages_traduites": {"0": "texte"},
        "total_pages": 10,
    }))
    (checkpoints / "complet.json").write_text(json.dumps({
        "version": 2,
        "pages_traduites": {"0": "texte"},
        "total_pages": 1,
    }))

    suspects = mnt.checkpoints_suspects()
    noms = {s["nom"] for s in suspects}
    assert "partiel" in noms
    assert "complet" not in noms


def test_nettoyage_complet_produit_un_rapport(espace_travail):
    (espace_travail / "extraction_cache" / "a.json").write_text('["x"]')
    messages: list[str] = []
    rapport = mnt.nettoyage_complet(jours_extraction=None,
                                    callback=messages.append)
    assert rapport["libere"] >= 0
    assert len(rapport["details"]) == 3
    assert messages
