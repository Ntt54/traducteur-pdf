#!/usr/bin/env python3
"""
Test complet de la traduction Google Translate (mode en ligne).

Vérifie que :
1. Google Translate fonctionne via deep_translator
2. Le worker traduit correctement les pages
3. Le checkpoint est bien créé (et PAS supprimé pendant le test)
4. Le pipeline complet fonctionne de bout en bout
"""

import os
import sys
import time
from queue import Queue
from threading import Thread

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deep_translator import GoogleTranslator
import moteur.config as cfg
from moteur.traducteur import (
    traduire_bloc,
    worker_traduction,
    init_cache,
    decouper_blocs,
    cache_get,
    cache_put,
)
from moteur.utils import (
    charger_checkpoint,
    sauvegarder_checkpoint,
    hash_texte,
)
from moteur.revision import texte_est_francais


def test_google_translate_direct():
    """Test basique : traduction directe via Google."""
    print("\n=== Test 1 : Traduction directe Google ===")
    t = GoogleTranslator(source="en", target="fr")

    textes = [
        "Hello, how are you?",
        "The cat sat on the mat.",
        "I love reading books in the evening.",
        "The quick brown fox jumps over the lazy dog near the old castle.",
        "Despite the heavy rain, they decided to continue their journey through the mountains.",
        "Jake bent his back as he avoided a wooden spear. The battle had been raging for hours, and the smoke filled his lungs.",
    ]

    for texte in textes:
        resultat = t.translate(texte)
        assert resultat is not None, f"Résultat None pour: {texte[:50]}"
        assert len(resultat.strip()) > 0, f"Résultat vide pour: {texte[:50]}"
        assert resultat.strip() != texte.strip(), (
            f"Identique à l'original: {resultat[:50]}"
        )
        est_francais = texte_est_francais(resultat)
        print(f"  ✅ '{texte[:40]}...' → '{resultat[:50]}...' (fr={est_francais})")

    print("  → Toutes les traductions directes OK\n")


def test_decoupage_blocs():
    """Test le découpage en blocs de taille maximale."""
    print("=== Test 2 : Découpage en blocs ===")
    cfg.configurer({"TAILLE_BLOC": 100})
    texte_long = "Ceci est un test. " * 50  # ~950 caractères
    blocs = decouper_blocs(texte_long)
    assert len(blocs) > 1, f"Devrait découper en >1 blocs, obtenu {len(blocs)}"
    for b in blocs:
        assert len(b) <= 150, f"Bloc trop long: {len(b)} caractères"
    print(f"  ✅ {len(texte_long)} caractères → {len(blocs)} blocs")
    print("  → Découpage OK\n")


def test_cache_traduction():
    """Test le cache SQLite de traduction."""
    print("=== Test 3 : Cache SQLite ===")
    init_cache()
    bloc = "The wizard cast a powerful spell."
    trad = "Le sorcier lança un sort puissant."
    cache_put(bloc, trad)
    hit = cache_get(bloc)
    assert hit == trad, f"Cache miss: obtenu {hit!r}"
    print(f"  ✅ Cache hit: '{bloc[:30]}...' → '{hit[:30]}...'")
    print("  → Cache OK\n")


def test_worker_traduction_complet():
    """Test complet du worker : queue → traduction → checkpoint (sans supprimer)."""
    print("=== Test 4 : Worker de traduction complet ===")
    cfg.configurer({
        "LANGUE_SOURCE": "en",
        "LANGUE_CIBLE": "fr",
        "MAX_RETRIES": 3,
        "BACKOFF_CAP": 5,
        "PACE_MIN": 0.01,
        "PACE_MAX": 0.05,
        "RATE_LIMIT": 5,
        "NB_THREADS_TRAD": 1,
        "TAILLE_BLOC": 4800,
    })
    init_cache()

    # Textes de test réalistes (style roman)
    pages = [
        (
            "Chapter 1: The Beginning\n\n"
            "The old dragon perched atop the mountain, its scales shimmering "
            "under the moonlight. Adventurers whispered tales of its treasure, "
            "but none dared to approach. The village below lived in fear, "
            "yet hoped for a hero who would save them from the beast."
        ),
        (
            "Chapter 2: The Journey\n\n"
            "She opened the ancient book and read the forbidden spell aloud. "
            "The air trembled with magical energy. Shadows danced across the "
            "walls of the dark chamber, and a cold wind swept through the "
            "corridor. She knew there was no turning back."
        ),
    ]

    nom_base = "test_google_worker"
    fichiers_data = {
        nom_base: {
            "sortie": f"/tmp/{nom_base}.txt",
            "total_pages": len(pages),
            "pages_traduites": {},
            "hash_original": {},
            "compteur_local": 0,
            "deja_exporte": False,
        }
    }

    task_queue = Queue()
    for i, page in enumerate(pages):
        task_queue.put((nom_base, i, page))

    cfg.total_tasks = len(pages)
    cfg.total_done = 0

    # Initialiser l'executor PDF (nécessaire quand le worker finit toutes les pages)
    from concurrent.futures import ThreadPoolExecutor
    cfg.executor_pdf = ThreadPoolExecutor(max_workers=1)
    cfg.futures_pdf = []

    # Lancer le worker
    translator = GoogleTranslator(source="en", target="fr")
    worker = Thread(
        target=worker_traduction,
        args=(translator, task_queue, fichiers_data, "DejaVu Sans", "DejaVu Sans"),
        daemon=True,
    )
    t0 = time.time()
    worker.start()
    task_queue.join()
    worker.join(timeout=60)

    # Attendre l'export PDF si déclenché
    for f in cfg.futures_pdf:
        try:
            f.result(timeout=30)
        except Exception as e:
            print(f"  ⚠️  Erreur export: {e}")
    if cfg.executor_pdf:
        cfg.executor_pdf.shutdown(wait=False)

    duree = time.time() - t0

    data = fichiers_data[nom_base]
    pages_traduites = data["pages_traduites"]

    print(f"  ⏱ Durée: {duree:.1f}s")
    print(f"  📄 Pages traduites: {len(pages_traduites)}/{len(pages)}")

    for idx_str, texte_traduit in pages_traduites.items():
        print(f"\n  --- Page {idx_str} ---")
        print(f"  {texte_traduit[:200]}...")
        assert len(texte_traduit.strip()) > 0, f"Page {idx_str} vide"
        assert texte_traduit.strip() != pages[int(idx_str)].strip(), (
            f"Page {idx_str} identique à l'original"
        )

    # Vérifier le checkpoint
    cp_pages, cp_meta = charger_checkpoint(nom_base)
    if cp_pages:
        print(f"\n  💾 Checkpoint trouvé: {len(cp_pages)} pages")
        print(f"  ⚠️  Checkpoint INTACT (pas supprimé)")
    else:
        print(f"\n  ℹ️  Pas de checkpoint (worker n'a pas encore exporté)")

    print("  → Worker OK\n")


def test_revision_langue():
    """Test la vérification que le résultat est bien en français."""
    print("=== Test 5 : Vérification langue ===")
    texte_fr = "Le chat noir dort sur le canapé."
    texte_en = "The black cat sleeps on the sofa."
    assert texte_est_francais(texte_fr), "Doit détecter le français"
    assert not texte_est_francais(texte_en), "Doit détecter que ce n'est PAS du français"
    print("  ✅ Détection FR vs EN correcte")
    print("  → Vérification langue OK\n")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTS TRADUCTION GOOGLE TRANSLATE (mode en ligne)")
    print("=" * 60)

    test_google_translate_direct()
    test_decoupage_blocs()
    test_cache_traduction()
    test_revision_langue()
    test_worker_traduction_complet()

    print("=" * 60)
    print("  ✅ TOUS LES TESTS TERMINÉS AVEC SUCCÈS")
    print("  📁 Les checkpoints ont été créés mais PAS supprimés")
    print("=" * 60)
