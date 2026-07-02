#!/usr/bin/env python3
"""
Gestion des éditions utilisateur dans l'aperçu (Feature 4).
Sauvegarde locale des modifications texte pour réinjection à l'export.
"""

from __future__ import annotations

import os
import json
from typing import Optional

DOSSIER_EDITS = ".edits"


def _dossier_edits(dossier_sortie: str) -> str:
    """Retourne le chemin du dossier d'éditions."""
    ed = os.path.join(dossier_sortie, DOSSIER_EDITS)
    os.makedirs(ed, exist_ok=True)
    return ed


def chemin_edits(nom_base: str, dossier_sortie: str) -> str:
    """Retourne le chemin du fichier d'éditions pour un fichier."""
    return os.path.join(_dossier_edits(dossier_sortie), f"{nom_base}.json")


def sauvegarder_edits(nom_base: str, texte_modifie: str, dossier_sortie: str) -> str:
    """Sauvegarde le texte modifié par l'utilisateur."""
    chemin = chemin_edits(nom_base, dossier_sortie)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump({"texte": texte_modifie}, f, ensure_ascii=False, indent=2)
    return chemin


def charger_edits(nom_base: str, dossier_sortie: str) -> Optional[str]:
    """Charge le texte modifié par l'utilisateur."""
    chemin = chemin_edits(nom_base, dossier_sortie)
    if os.path.exists(chemin):
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("texte")
    return None


def supprimer_edits(nom_base: str, dossier_sortie: str) -> None:
    """Supprime les éditions d'un fichier."""
    chemin = chemin_edits(nom_base, dossier_sortie)
    if os.path.exists(chemin):
        os.remove(chemin)


def lister_edits(dossier_sortie: str) -> list[str]:
    """Liste les fichiers qui ont des éditions."""
    ed_dir = _dossier_edits(dossier_sortie)
    if not os.path.isdir(ed_dir):
        return []
    return sorted(
        f.replace(".json", "") for f in os.listdir(ed_dir)
        if f.endswith(".json")
    )
