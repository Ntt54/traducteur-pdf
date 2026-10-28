#!/usr/bin/env python3
"""
Tests du module glossaire : lecture, écriture, filtrage, import/export CSV.
"""

import json

import pytest

from moteur import glossaire as glo


@pytest.fixture
def base(tmp_path):
    """Base glossaire de test avec deux romans."""
    chemin = tmp_path / "glossary_db.json"
    donnees = {
        "roman_a": {"Sword": "Épée", "Jake": "Jake", "Mana": "Mana"},
        "roman_b": {"Beast": "Bête"},
    }
    chemin.write_text(json.dumps(donnees), encoding="utf-8")
    return chemin


def test_charger_base_absente(tmp_path):
    assert glo.charger(str(tmp_path / "inexistant.json")) == {}


def test_charger_base_corrompue(tmp_path):
    chemin = tmp_path / "casse.json"
    chemin.write_text("{ ceci n'est pas du json", encoding="utf-8")
    assert glo.charger(str(chemin)) == {}


def test_romans_tries(base):
    db = glo.charger(str(base))
    assert glo.romans(db) == ["roman_a", "roman_b"]


def test_termes_tous(base):
    db = glo.charger(str(base))
    resultats = glo.termes(db, "roman_a")
    assert [t for t, _ in resultats] == ["Jake", "Mana", "Sword"]


def test_termes_seulement_valides(base):
    db = glo.charger(str(base))
    resultats = glo.termes(db, "roman_a", seulement_valides=True)
    # "Jake" -> "Jake" et "Mana" -> "Mana" sont des détections non confirmées
    assert [t for t, _ in resultats] == ["Sword"]


def test_termes_filtre_insensible_a_la_casse(base):
    db = glo.charger(str(base))
    assert glo.termes(db, "roman_a", filtre="swo") == [("Sword", "Épée")]
    assert glo.termes(db, "roman_a", filtre="épée") == [("Sword", "Épée")]


def test_definir_terme_ajoute_et_met_a_jour(base):
    db = glo.charger(str(base))
    glo.definir_terme(db, "roman_a", "Shield", "Bouclier")
    assert db["roman_a"]["Shield"] == "Bouclier"
    glo.definir_terme(db, "roman_a", "Shield", "Écu")
    assert db["roman_a"]["Shield"] == "Écu"


def test_definir_terme_vide_leve():
    with pytest.raises(ValueError):
        glo.definir_terme({}, "roman", "   ", "valeur")


def test_supprimer_terme(base):
    db = glo.charger(str(base))
    assert glo.supprimer_terme(db, "roman_a", "Sword") is True
    assert glo.supprimer_terme(db, "roman_a", "Sword") is False


def test_statistiques(base):
    db = glo.charger(str(base))
    st = glo.statistiques(db, "roman_a")
    assert st == {"romans": 1, "total": 3, "valides": 1, "en_attente": 2}
    globales = glo.statistiques(db)
    assert globales["romans"] == 2
    assert globales["total"] == 4


def test_sauvegarder_cree_une_copie_de_secours(base):
    db = glo.charger(str(base))
    glo.definir_terme(db, "roman_a", "Shield", "Bouclier")
    glo.sauvegarder(db, str(base))
    assert (base.parent / (base.name + ".bak")).exists()
    relu = glo.charger(str(base))
    assert relu["roman_a"]["Shield"] == "Bouclier"


def test_export_puis_import_csv(base, tmp_path):
    db = glo.charger(str(base))
    csv_path = tmp_path / "export.csv"
    nb = glo.exporter_csv(db, "roman_a", str(csv_path))
    assert nb == 3

    cible: dict = {}
    importes = glo.importer_csv(cible, "roman_a", str(csv_path))
    assert importes == 3
    assert cible["roman_a"]["Sword"] == "Épée"


def test_import_csv_sans_ecrasement(base, tmp_path):
    db = glo.charger(str(base))
    csv_path = tmp_path / "export.csv"
    glo.exporter_csv(db, "roman_a", str(csv_path))

    cible = {"roman_a": {"Sword": "Lame"}}
    importes = glo.importer_csv(cible, "roman_a", str(csv_path), ecraser=False)
    assert importes == 2
    assert cible["roman_a"]["Sword"] == "Lame"

    importes = glo.importer_csv(cible, "roman_a", str(csv_path), ecraser=True)
    assert importes == 3
    assert cible["roman_a"]["Sword"] == "Épée"
