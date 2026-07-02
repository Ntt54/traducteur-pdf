#!/usr/bin/env python3
"""
Tests unitaires pour le gestionnaire de statistiques.
Nécessite sqlite3 (stdlib) et utilise un fichier DB temporaire.
"""

import os
import tempfile
import pytest

pytest.importorskip("sqlite3", reason="sqlite3 n'est pas disponible")

import stats_manager as sm


# ─────────────────────────────────────────────
#   ENREGISTRER & RÉCUPÉRER UNE SESSION
# ─────────────────────────────────────────────

def test_enregistrer_et_recuperer():
    """Enregistre une session et vérifie qu'elle est retournée par get_historique()."""
    old_path = sm.DB_PATH

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    sm.DB_PATH = tmp.name

    try:
        sm.enregistrer_session(
            fichiers=3,
            pages=50,
            duration=120.5,
            source="en",
            cible="fr",
            statut="termine",
            format_export="pdf",
            cache_hit=10,
            fallback_en=2,
            pages_par_seconde=0.42,
        )

        # Vérifier l'historique
        historique = sm.get_historique()
        assert len(historique) >= 1, "L'historique doit contenir au moins une session"

        row = historique[0]
        # Structure : (id, date, duration, fichiers, pages, source, cible, statut,
        #              format_export, cache_hit, fallback_en, pages_par_seconde)
        assert row[3] == 3, "fichiers devrait être 3"
        assert row[4] == 50, "pages devrait être 50"
        assert row[5] == "en", "source devrait être 'en'"
        assert row[6] == "fr", "cible devrait être 'fr'"
        assert row[7] == "termine", "statut devrait être 'termine'"
        assert row[8] == "pdf", "format_export devrait être 'pdf'"
        assert row[9] == 10, "cache_hit devrait être 10"
        assert row[10] == 2, "fallback_en devrait être 2"

        # Vérifier les stats globales
        globales = sm.get_stats_globales()
        assert globales["total_sessions"] >= 1
        assert globales["total_pages"] >= 50
        assert globales["total_fichiers"] >= 3
        assert globales["total_duree"] >= 120.0

    finally:
        sm.DB_PATH = old_path
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def test_multiple_sessions():
    """Enregistrer plusieurs sessions doit les accumuler dans les stats globales."""
    old_path = sm.DB_PATH

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    sm.DB_PATH = tmp.name

    try:
        sm.enregistrer_session(fichiers=1, pages=10, duration=5.0,
                               source="en", cible="fr", statut="termine",
                               format_export="pdf")
        sm.enregistrer_session(fichiers=2, pages=20, duration=10.0,
                               source="en", cible="de", statut="termine",
                               format_export="txt")

        globales = sm.get_stats_globales()
        assert globales["total_sessions"] >= 2
        assert globales["total_pages"] >= 30
        assert globales["total_fichiers"] >= 3

        historique = sm.get_historique(limite=10)
        assert len(historique) >= 2

    finally:
        sm.DB_PATH = old_path
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
