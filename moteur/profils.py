#!/usr/bin/env python3
"""
Profils de configuration (Feature 5).
Sauvegarde et chargement de préréglages nommés.
"""

from __future__ import annotations

import os
import json
from typing import Optional

DOSSIER_PROFILS = "profiles"
PROFIL_EXT = ".json"


def _dossier_profils() -> str:
    """Crée et retourne le chemin du dossier des profils."""
    # Stocké à côté du projet
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", DOSSIER_PROFILS)
    p = os.path.abspath(p)
    os.makedirs(p, exist_ok=True)
    return p


def lister_profils() -> list[str]:
    """Liste les noms des profils disponibles."""
    d = _dossier_profils()
    noms = []
    for f in sorted(os.listdir(d)):
        if f.endswith(PROFIL_EXT):
            noms.append(f[:-len(PROFIL_EXT)])
    return noms


def chemin_profil(nom: str) -> str:
    """Retourne le chemin complet d'un fichier profil."""
    return os.path.join(_dossier_profils(), nom + PROFIL_EXT)


def sauvegarder_profil(nom: str, config: dict) -> str:
    """Sauvegarde une configuration en tant que profil."""
    chemin = chemin_profil(nom)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return chemin


def charger_profil(nom: str) -> Optional[dict]:
    """Charge un profil par son nom."""
    chemin = chemin_profil(nom)
    if not os.path.exists(chemin):
        return None
    with open(chemin, "r", encoding="utf-8") as f:
        return json.load(f)


def supprimer_profil(nom: str) -> bool:
    """Supprime un profil."""
    chemin = chemin_profil(nom)
    if os.path.exists(chemin):
        os.remove(chemin)
        return True
    return False


def profil_existe(nom: str) -> bool:
    """Vérifie si un profil existe."""
    return os.path.exists(chemin_profil(nom))
