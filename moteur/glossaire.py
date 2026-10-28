#!/usr/bin/env python3
"""
Glossaire : accès CRUD à la base de termes ``glossary_db.json``.

Structure du fichier :
    {
      "id_du_roman": {"terme_source": "traduction", ...},
      ...
    }

Une entrée dont la valeur est identique à la clé est considérée comme
*non validée* : elle a été détectée automatiquement mais jamais confirmée
par un humain, et n'est donc pas appliquée lors du post-traitement.
"""

from __future__ import annotations

import os
import json
import shutil
import threading
from typing import Optional

_LOCK = threading.Lock()

CHEMIN_PAR_DEFAUT = "glossary_db.json"


def chemin_db(dossier_travail: Optional[str] = None) -> str:
    """Retourne le chemin de la base glossaire."""
    base = dossier_travail or os.getcwd()
    return os.path.join(base, CHEMIN_PAR_DEFAUT)


def charger(chemin: Optional[str] = None) -> dict[str, dict[str, str]]:
    """Charge la base complète. Retourne {} si absente ou illisible."""
    chemin = chemin or chemin_db()
    if not os.path.exists(chemin):
        return {}
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def sauvegarder(db: dict[str, dict[str, str]], chemin: Optional[str] = None) -> None:
    """Écrit la base sur disque (écriture atomique + sauvegarde .bak)."""
    chemin = chemin or chemin_db()
    with _LOCK:
        if os.path.exists(chemin):
            try:
                shutil.copy2(chemin, chemin + ".bak")
            except OSError:
                pass
        tmp = chemin + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, chemin)


def romans(db: dict) -> list[str]:
    """Liste triée des identifiants de romans présents dans la base."""
    return sorted(db.keys())


def termes(db: dict, roman: str, filtre: str = "",
           seulement_valides: bool = False) -> list[tuple[str, str]]:
    """Retourne les couples (terme, traduction) d'un roman.

    Args:
        filtre: sous-chaîne recherchée (insensible à la casse) sur le terme
            ou sa traduction.
        seulement_valides: n'inclure que les entrées dont la traduction
            diffère du terme source.
    """
    entrees = db.get(roman, {})
    filtre = filtre.strip().lower()
    resultat = []
    for terme, trad in entrees.items():
        if seulement_valides and trad == terme:
            continue
        if filtre and filtre not in terme.lower() and filtre not in str(trad).lower():
            continue
        resultat.append((terme, trad))
    return sorted(resultat, key=lambda t: t[0].lower())


def definir_terme(db: dict, roman: str, terme: str, traduction: str) -> None:
    """Ajoute ou met à jour un terme dans le glossaire d'un roman."""
    terme = terme.strip()
    if not terme:
        raise ValueError("Le terme ne peut pas être vide.")
    db.setdefault(roman, {})[terme] = traduction.strip()


def supprimer_terme(db: dict, roman: str, terme: str) -> bool:
    """Supprime un terme. Retourne True si l'entrée existait."""
    entrees = db.get(roman)
    if not entrees or terme not in entrees:
        return False
    del entrees[terme]
    return True


def statistiques(db: dict, roman: Optional[str] = None) -> dict:
    """Compte les termes totaux / validés / en attente."""
    cibles = [roman] if roman else list(db.keys())
    total = 0
    valides = 0
    for r in cibles:
        for terme, trad in db.get(r, {}).items():
            total += 1
            if trad != terme:
                valides += 1
    return {
        "romans": len(cibles),
        "total": total,
        "valides": valides,
        "en_attente": total - valides,
    }


def exporter_csv(db: dict, roman: str, chemin: str) -> int:
    """Exporte le glossaire d'un roman en CSV. Retourne le nombre de lignes."""
    import csv

    entrees = termes(db, roman)
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["terme", "traduction"])
        writer.writerows(entrees)
    return len(entrees)


def importer_csv(db: dict, roman: str, chemin: str, ecraser: bool = False) -> int:
    """Importe un CSV (terme,traduction) dans le glossaire d'un roman.

    Returns:
        Nombre d'entrées importées.
    """
    import csv

    cible = db.setdefault(roman, {})
    nb = 0
    with open(chemin, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for ligne in reader:
            if len(ligne) < 2:
                continue
            terme, trad = ligne[0].strip(), ligne[1].strip()
            if not terme or terme.lower() == "terme":
                continue
            if terme in cible and not ecraser:
                continue
            cible[terme] = trad
            nb += 1
    return nb
