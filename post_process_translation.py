#!/usr/bin/env python3
"""
post_process_translation.py

Script UNIQUE de post-traitement pour traductions Argos (EN->FR), conçu
pour s'adapter automatiquement à n'importe quel roman, sans fichier de
config à créer manuellement.

Fonctionnement :
1. Corrections universelles (faux-amis connus, typographie, interjections)
   appliquées à tout texte, quel que soit le roman.
2. Détection automatique du roman (via le titre trouvé dans les premières
   pages) et récupération/création de sa fiche dans une base glossaire
   UNIQUE et persistante (glossary_db.json), qui grossit au fil des usages.
3. Détection automatique de nouveaux termes candidats (noms propres
   récurrents, mots anglais restés non traduits) -> ajoutés à la base
   glossaire du roman comme "a verifier" (valeur = terme lui-meme tant
   que non corrige manuellement). Les entrees deja corrigees manuellement
   sont appliquees automatiquement aux traductions suivantes.

Usage:
    python post_process_translation.py input.json output.json
    python post_process_translation.py input.json output.json --db glossary_db.json
    python post_process_translation.py input.json output.json --novel-id mon_roman

Pour corriger un terme detecte automatiquement : ouvrir glossary_db.json,
trouver le roman, remplacer la valeur (initialement identique a la cle)
par la bonne traduction. Le prochain passage l'appliquera partout.
"""

import json
import re
import argparse
import unicodedata
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# 1) CORRECTIONS UNIVERSELLES (valables pour tout roman EN->FR via Argos)
# ---------------------------------------------------------------------------

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

# Mots-outils anglais courants qui, s'ils apparaissent tels quels dans le
# texte "traduit", indiquent qu'Argos a laissé un fragment non traduit.
ENGLISH_LEFTOVER_MARKERS = {
    "the", "and", "was", "were", "said", "with", "from", "they",
    "have", "been", "into", "will", "would", "could", "should",
    "than", "then", "when", "where", "which", "whose", "why", "how",
    "not", "but", "nor", "yet", "you", "this", "that", "what",
}

# Mots courants français à NE JAMAIS considérer comme nom propre candidat,
# même capitalisés en début de phrase.
FRENCH_STOPWORDS_CAP = {
    "Il", "Elle", "Le", "La", "Les", "Un", "Une", "Des", "Ce", "Cette",
    "Ces", "Son", "Sa", "Ses", "Mais", "Or", "Donc", "Car", "Et", "Ou",
    "Quand", "Comme", "Alors", "Après", "Avant", "Pendant", "Chapitre",
    "Tout", "Tous", "Toute", "Toutes", "Rien", "Personne", "Quelqu",
    "Quelque", "Aucun", "Chaque", "Plusieurs", "Certains", "Vous",
    "Nous", "Je", "Tu", "On",
}


def normalize_quotes(text: str) -> str:
    parts = text.split('"')
    if len(parts) == 1:
        return text
    result = parts[0]
    for i, part in enumerate(parts[1:], start=1):
        result += ("«\u00a0" if i % 2 == 1 else "\u00a0»") + part
    return result


def fix_spacing(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([!?;:])", "\u00a0\\1", text)
    return text


def fix_interjections(text: str) -> str:
    for en, fr in INTERJECTIONS.items():
        text = re.sub(rf"\b{en}\b", fr, text)
    return text


def apply_universal_corrections(text: str) -> str:
    if not text:
        return text
    for pattern, repl, _ in FIXED_CORRECTIONS:
        text = re.sub(pattern, repl, text)
    for pattern, repl, _ in FIXED_CORRECTIONS_CI:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    text = fix_interjections(text)
    text = normalize_quotes(text)
    text = fix_spacing(text)
    return text


# ---------------------------------------------------------------------------
# 2) DETECTION AUTOMATIQUE DU ROMAN + BASE GLOSSAIRE UNIQUE
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "roman_inconnu"


def detect_novel_id(pages: dict) -> str:
    """Cherche un titre plausible dans les 3 premières pages (texte sans URL,
    raisonnablement court -> probable page de titre/source)."""
    for key in sorted(pages.keys(), key=lambda x: int(x))[:3]:
        text = pages[key].strip()
        if not text:
            continue
        first_line = text.split("\n")[0]
        # Retire les URLs pour ne garder que le titre
        candidate = re.sub(r"https?://\S+", "", first_line).strip()
        candidate = re.sub(r"^Source\s*:?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"Produit par.*$", "", candidate, flags=re.IGNORECASE).strip()
        if candidate and 3 < len(candidate) < 80:
            return slugify(candidate)
    return "roman_inconnu"


def load_db(db_path: Path) -> dict:
    if db_path.exists():
        with open(db_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_db(db_path: Path, db: dict):
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2, sort_keys=True)


def apply_glossary(text: str, glossary: dict) -> str:
    for term, replacement in glossary.items():
        if replacement == term:
            continue  # pas encore validé manuellement -> on ne touche pas
        text = re.sub(rf"\b{re.escape(term)}\b", replacement, text)
    return text


# ---------------------------------------------------------------------------
# 3) DETECTION AUTOMATIQUE DE NOUVEAUX TERMES CANDIDATS
# ---------------------------------------------------------------------------

def detect_candidate_terms(all_text: str, existing_glossary: dict, min_freq: int = 3):
    """Retourne un dict {terme: terme} pour les noms propres récurrents et
    mots anglais visiblement non traduits, absents de la base actuelle."""
    candidates = Counter()

    # a) Noms propres récurrents : mots capitalisés hors début de phrase
    #    évident, en excluant les mots-outils français capitalisés.
    for word in re.findall(r"\b[A-Z][a-zàâäéèêëïîôöùûüç]+\b", all_text):
        if word in FRENCH_STOPWORDS_CAP:
            continue
        candidates[word] += 1

    # b) Mots anglais laissés tels quels (marqueurs de fragments non traduits)
    for word in re.findall(r"\b[a-zA-Z]+\b", all_text.lower()):
        if word in ENGLISH_LEFTOVER_MARKERS:
            candidates[word] += 1

    new_terms = {}
    for term, freq in candidates.items():
        if freq < min_freq:
            continue
        if term in existing_glossary or term.lower() in existing_glossary:
            continue
        new_terms[term] = term  # placeholder = a verifier manuellement

    return new_terms


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

def process_file(input_path: str, output_path: str, db_path: str, novel_id_override):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages_traduites", {})
    db_file = Path(db_path)
    db = load_db(db_file)

    novel_id = novel_id_override or detect_novel_id(pages)
    glossary = db.get(novel_id, {})

    all_text = "\n".join(pages.values())
    new_terms = detect_candidate_terms(all_text, glossary)
    if new_terms:
        glossary.update(new_terms)

    corrections_log = []
    for page_num, text in pages.items():
        new_text = apply_universal_corrections(text)
        new_text = apply_glossary(new_text, glossary)
        if new_text != text:
            corrections_log.append(page_num)
        pages[page_num] = new_text

    db[novel_id] = glossary
    save_db(db_file, db)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Roman détecté : {novel_id}")
    print(f"Pages traitées : {len(pages)} | Pages modifiées : {len(corrections_log)}")
    if new_terms:
        print(f"\nNouveaux termes détectés et ajoutés à '{db_path}' (a verifier manuellement) :")
        for term in sorted(new_terms):
            print(f"  - {term}")
        print(f"\n-> Ouvre {db_path}, section \"{novel_id}\", et corrige les valeurs.")
        print("   Le prochain passage appliquera automatiquement tes corrections.")
    else:
        print("Aucun nouveau terme candidat détecté.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Fichier JSON d'entrée (sortie Argos)")
    parser.add_argument("output", help="Fichier JSON de sortie corrigé")
    parser.add_argument("--db", default="glossary_db.json", help="Base glossaire unique (par défaut: glossary_db.json)")
    parser.add_argument("--novel-id", default=None, help="Force l'identifiant du roman au lieu de la détection automatique")
    args = parser.parse_args()

    process_file(args.input, args.output, args.db, args.novel_id)


if __name__ == "__main__":
    main()
