"""
post_process.py — Post-traitement des traductions Argos (EN->FR)

Améliore la qualité des traductions brutes via :
1. Corrections universelles (faux-amis, typographie, interjections)
2. Glossaire persistant par roman (détection auto, enrichissement progressif)

S'inspire de post_process_translation.py à la racine (qui reste utilisable
en standalone), mais conçu pour s'intégrer directement dans le pipeline.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────
# 1) CORRECTIONS UNIVERSELLES
# ─────────────────────────────────────────────

FIXED_CORRECTIONS = [
    (r"\bPNC\b", "PNJ", "NPC mal traduit (PNC -> PNJ)"),
    (r"\bgele\b", "gèle", "accent manquant sur 'gèle'"),
    (r"\bpestle\b", "pilon", "mot anglais 'pestle' non traduit"),
]

FIXED_CORRECTIONS_CI = [
    (r"\bses élèves\b", "ses pupilles", "pupils (yeux) mal traduit en 'élèves'"),
    (r"\bl'élève\b", "la pupille", "pupil (oeil) mal traduit en 'élève'"),
]

INTERJECTIONS = {
    "Ugh": "Argh", "Huh": "Hein", "Yawn": "Bâille",
    "Ouch": "Aïe", "Yeah": "Ouais", "Hmm": "Hmm",
}

ENGLISH_LEFTOVER_MARKERS = {
    "the", "and", "was", "were", "said", "with", "from", "they",
    "have", "been", "into", "will", "would", "could", "should",
    "than", "then", "when", "where", "which", "whose", "why", "how",
    "not", "but", "nor", "yet", "you", "this", "that", "what",
}

FRENCH_STOPWORDS_CAP = {
    "Il", "Elle", "Le", "La", "Les", "Un", "Une", "Des", "Ce", "Cette",
    "Ces", "Son", "Sa", "Ses", "Mais", "Or", "Donc", "Car", "Et", "Ou",
    "Quand", "Comme", "Alors", "Après", "Avant", "Pendant", "Chapitre",
    "Tout", "Tous", "Toute", "Toutes", "Rien", "Personne", "Quelqu",
    "Quelque", "Aucun", "Chaque", "Plusieurs", "Certains", "Vous",
    "Nous", "Je", "Tu", "On",
}

_GLOSSAIRE_LOCK = threading.Lock()


def corriger_typographie(text: str) -> str:
    """Guillemets anglais -> français, espaces insécables."""
    parts = text.split('"')
    if len(parts) == 1:
        return text
    result = parts[0]
    for i, part in enumerate(parts[1:], start=1):
        result += ("«\u00a0" if i % 2 == 1 else "\u00a0»") + part
    return result


def corriger_espaces(text: str) -> str:
    """Doubles espaces, espace insécable avant !?;:"""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([!?;:])", "\u00a0\\1", text)
    return text


def corriger_interjections(text: str) -> str:
    for en, fr in INTERJECTIONS.items():
        text = re.sub(rf"\b{re.escape(en)}\b", fr, text)
    return text


def corriger_texte_universel(text: str) -> str:
    """Applique toutes les corrections universelles à un texte traduit."""
    if not text:
        return text
    for pattern, repl, _ in FIXED_CORRECTIONS:
        text = re.sub(pattern, repl, text)
    for pattern, repl, _ in FIXED_CORRECTIONS_CI:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    text = corriger_interjections(text)
    text = corriger_typographie(text)
    text = corriger_espaces(text)
    return text


def appliquer_glossaire(text: str, glossary: dict[str, str]) -> str:
    """Applique un glossaire {terme: traduction} à un texte.
    Ignore les entrées non validées (valeur == clé)."""
    for term, replacement in glossary.items():
        if replacement == term:
            continue  # pas encore validé manuellement
        text = re.sub(rf"\b{re.escape(term)}\b", replacement, text)
    return text


# ─────────────────────────────────────────────
# 2) GLOSSAIRE PERSISTANT
# ─────────────────────────────────────────────

def slugifier(titre: str) -> str:
    titre = unicodedata.normalize("NFKD", titre).encode("ascii", "ignore").decode()
    titre = re.sub(r"[^a-zA-Z0-9]+", "_", titre).strip("_").lower()
    return titre or "roman_inconnu"


def detecter_roman(pages: dict[str, str]) -> str:
    """Détecte l'ID du roman depuis les 3 premières pages (source ou traduites).

    Joint les lignes du premier paragraphe pour gérer les soft-wrap PDF
    (ex. titre coupé par un retour à la ligne). Tentatives par ordre de
    préférence : 2 premières lignes assemblées, puis 3, puis 1 seule.
    """
    for key in sorted(pages.keys(), key=lambda x: int(x))[:5]:
        text = pages[key].strip()
        if not text:
            continue
        lines = [l.strip() for l in text.split("\n")]
        # Différentes stratégies de jointure
        essais: list[str] = []
        # 1) 2 premières lignes (soft-wrap titre)
        if len(lines) >= 2 and lines[0] and lines[1]:
            essais.append(f"{lines[0]} {lines[1]}")
        # 2) 3 premières lignes (titre un peu plus long)
        if len(lines) >= 3 and all(lines[:3]):
            essais.append(" ".join(lines[:3]))
        # 3) Lignes jusqu'au premier saut de paragraphe
        bloc = ""
        for line in lines:
            if not line:
                break
            bloc = f"{bloc} {line}" if bloc else line
        if bloc:
            essais.append(bloc)
        # 4) Première ligne seule (fallback)
        if lines[0]:
            essais.append(lines[0])

        for essai in essais:
            candidate = re.sub(r"https?://\S+", "", essai).strip()
            candidate = re.sub(r"^Source\s*:?\s*", "", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"Produit par.*$", "", candidate, flags=re.IGNORECASE).strip()
            if candidate and 3 < len(candidate) < 80:
                return slugifier(candidate)
    return "roman_inconnu"


class GlossaireManager:
    """Gère la base glossaire persistante (glossary_db.json)."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._db: dict = {}
        self._novel_id: Optional[str] = None
        self._glossary: dict[str, str] = {}
        self._ready = False
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        if self.db_path.exists():
            with open(self.db_path, "r", encoding="utf-8") as f:
                self._db = json.load(f)
        self._loaded = True

    def _save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _GLOSSAIRE_LOCK:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self._db, f, ensure_ascii=False, indent=2, sort_keys=True)

    def detecter_et_charger(self, pages: dict[str, str]) -> str:
        """Détecte le roman depuis les pages traduites et charge son glossaire."""
        self._load()
        novel_id = detecter_roman(pages)
        self._novel_id = novel_id
        self._glossary = dict(self._db.get(novel_id, {}))
        self._ready = True
        return novel_id

    @property
    def novel_id(self) -> Optional[str]:
        return self._novel_id

    @property
    def glossary(self) -> dict[str, str]:
        return self._glossary

    @property
    def ready(self) -> bool:
        return self._ready

    def appliquer(self, text: str) -> str:
        """Applique le glossaire du roman courant (si chargé) au texte."""
        if not self._ready:
            return text
        return appliquer_glossaire(text, self._glossary)

    def detecter_nouveaux_termes(self, all_text: str, min_freq: int = 3) -> dict[str, str]:
        """Trouve les termes candidats (noms propres, anglais non traduits)
        absents du glossaire actuel."""
        candidates: Counter = Counter()

        # Noms propres récurrents capitalisés (hors stopwords)
        for word in re.findall(r"\b[A-Z][a-zàâäéèêëïîôöùûüç]+\b", all_text):
            if word in FRENCH_STOPWORDS_CAP:
                continue
            candidates[word] += 1

        # Marqueurs anglais non traduits
        for word in re.findall(r"\b[a-zA-Z]+\b", all_text.lower()):
            if word in ENGLISH_LEFTOVER_MARKERS:
                candidates[word] += 1

        new_terms = {}
        for term, freq in candidates.items():
            if freq < min_freq:
                continue
            if term in self._glossary or term.lower() in self._glossary:
                continue
            new_terms[term] = term  # placeholder = à vérifier manuellement

        return new_terms

    def enrichir_et_sauvegarder(self, all_text: str, min_freq: int = 3) -> dict[str, str]:
        """Détecte les nouveaux termes candidats, les ajoute au glossaire
        du roman actuel et sauvegarde la base. Retourne les nouveaux termes."""
        new_terms = self.detecter_nouveaux_termes(all_text, min_freq)
        if new_terms:
            self._glossary.update(new_terms)
            if self._novel_id:
                self._db[self._novel_id] = self._glossary
                self._save()
        return new_terms

    def obtenir_stats(self) -> dict:
        """Retourne des stats sur le glossaire actuel."""
        valides = sum(1 for k, v in self._glossary.items() if v != k)
        en_attente = sum(1 for k, v in self._glossary.items() if v == k)
        return {
            "novel_id": self._novel_id or "?",
            "total": len(self._glossary),
            "valides": valides,
            "a_verifier": en_attente,
        }
