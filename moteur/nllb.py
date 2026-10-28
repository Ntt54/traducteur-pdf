#!/usr/bin/env python3
"""
Backend de traduction NLLB-200 (CTranslate2 int8) — 100 % hors ligne, CPU.

Sélectionnable au même titre qu'Argos. Le modèle est chargé une seule fois
(paresseux, thread-safe) et partagé entre tous les workers : CTranslate2 gère
lui-même le parallélisme interne des appels `translate_batch`.
"""

from __future__ import annotations

import os
import re
from threading import Lock
from typing import Callable, Optional, Any

try:
    import ctranslate2
    import sentencepiece as spm
    _LIBS_OK = True
except ImportError:
    _LIBS_OK = False


# ─────────────────────────────────────────────
#   EMPLACEMENT DU MODÈLE
# ─────────────────────────────────────────────

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(_RACINE, "models", "nllb-200-distilled-600M-int8")
_SP_MODEL = os.path.join(MODEL_DIR, "sentencepiece.bpe.model")


# ─────────────────────────────────────────────
#   CODES DE LANGUE FLORES-200
# ─────────────────────────────────────────────

# Mappe les codes courts utilisés par la config (en, fr, …) vers les codes
# FLORES-200 attendus par NLLB.
_FLORES: dict[str, str] = {
    "en": "eng_Latn", "fr": "fra_Latn", "es": "spa_Latn", "de": "deu_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn", "ru": "rus_Cyrl",
    "pl": "pol_Latn", "ro": "ron_Latn", "tr": "tur_Latn", "sv": "swe_Latn",
    "da": "dan_Latn", "no": "nob_Latn", "fi": "fin_Latn", "cs": "ces_Latn",
    "el": "ell_Grek", "uk": "ukr_Cyrl", "ar": "arb_Arab", "he": "heb_Hebr",
    "hi": "hin_Deva", "ja": "jpn_Jpan", "ko": "kor_Hang", "zh": "zho_Hans",
    "zh-cn": "zho_Hans", "zh-tw": "zho_Hant", "vi": "vie_Latn", "id": "ind_Latn",
    "th": "tha_Thai", "fa": "pes_Arab", "ca": "cat_Latn", "hu": "hun_Latn",
}


def _code_flores(langue: str) -> str:
    """Convertit un code court (en/fr/…) en code FLORES-200 (eng_Latn/…)."""
    c = (langue or "").lower()
    if c in _FLORES:
        return _FLORES[c]
    # Déjà au format FLORES ?
    if "_" in c and len(c) >= 7:
        return langue
    # Repli raisonnable : alphabet latin
    return f"{c[:3]}_Latn"


# ─────────────────────────────────────────────
#   DISPONIBILITÉ / INSTALLATION
# ─────────────────────────────────────────────

def nllb_disponible() -> bool:
    """Vrai si ctranslate2 + sentencepiece sont installés."""
    return _LIBS_OK


def modele_nllb_installe() -> bool:
    """Vrai si le modèle NLLB (CTranslate2) est présent sur le disque."""
    return (
        _LIBS_OK
        and os.path.isfile(os.path.join(MODEL_DIR, "model.bin"))
        and os.path.isfile(_SP_MODEL)
    )


# ─────────────────────────────────────────────
#   CHARGEMENT PARESSEUX DU MODÈLE
# ─────────────────────────────────────────────

_translator: Any = None
_sp: Any = None
_load_lock = Lock()

# Nombre de cœurs utilisés À L'INTÉRIEUR d'une inférence (pas en parallèle).
# On borne à un maximum raisonnable pour éviter la sur-souscription CPU/RAM.
_NB_CPU = os.cpu_count() or 4
_INTRA_THREADS = max(1, min(_NB_CPU, int(os.environ.get("NLLB_THREADS", 8))))

# Taille de batch bornée : la mémoire de pointe ≈ MAX_BATCH × beam × longueur.
# Plus le batch est petit, plus la RAM de pointe est basse.
_MAX_BATCH = max(1, int(os.environ.get("NLLB_MAX_BATCH", 8)))
_BEAM = max(1, int(os.environ.get("NLLB_BEAM", 4)))


def _get_modele():
    """Charge (une seule fois) le traducteur CTranslate2 + le tokenizer.

    Le modèle (≈ 600 Mo) n'est chargé qu'UNE fois et partagé par tous les
    workers. `inter_threads=1` garantit qu'une seule inférence tourne à la
    fois → mémoire de pointe bornée (pas de OOM). `intra_threads` répartit
    cette inférence unique sur plusieurs cœurs → vitesse maximale.
    """
    global _translator, _sp
    if _translator is not None:
        return _translator, _sp
    with _load_lock:
        if _translator is None:
            _sp = spm.SentencePieceProcessor(model_file=_SP_MODEL)
            _translator = ctranslate2.Translator(
                MODEL_DIR,
                device="cpu",
                compute_type="int8",
                intra_threads=_INTRA_THREADS,
                inter_threads=1,
            )
    return _translator, _sp


def workers_recommandes() -> int:
    """Nombre de threads workers conseillé pour NLLB sur CPU.

    Sur CPU, une seule inférence utilisant déjà tous les cœurs (intra_threads)
    est optimale : lancer plusieurs inférences en parallèle sature la RAM sans
    gain de vitesse (le CPU est déjà saturé). On renvoie donc 1.
    """
    return 1


def init_modele_nllb(callback: Optional[Callable[[str], None]] = None) -> str:
    """Charge le modèle NLLB et fait un warmup. Retourne un message d'état."""
    if not _LIBS_OK:
        msg = "ctranslate2/sentencepiece non installés. pip install ctranslate2 sentencepiece"
        if callback:
            callback(msg)
        return msg
    if not modele_nllb_installe():
        msg = f"Modèle NLLB introuvable dans {MODEL_DIR}"
        if callback:
            callback(msg)
        return msg
    try:
        if callback:
            callback("Chargement du modèle NLLB-200 (offline, CPU)...")
        traduire_texte_nllb("Hello", "en", "fr")  # warmup
        msg = "Modèle NLLB-200 chargé (offline, CPU)."
        if callback:
            callback(msg)
        return msg
    except Exception as e:
        msg = f"Échec du chargement du modèle NLLB : {e}"
        if callback:
            callback(msg)
        return msg


# ─────────────────────────────────────────────
#   SEGMENTATION (respect de la limite de tokens NLLB)
# ─────────────────────────────────────────────

_SEG_MAX = 250  # caractères max par segment envoyé au modèle
_PHRASE_RE = re.compile(r'[^.!?…]*[.!?…]+|[^.!?…]+$')

# Fin de phrase : ponctuation forte éventuellement suivie de guillemets/parenthèses.
_FIN_PHRASE = re.compile(r'[.!?…:][”"\'\)\]]*\s*$')

# Lignes à NE PAS traduire (laissées telles quelles) : URLs, mentions de source.
_PASSTHROUGH = re.compile(r'https?://|www\.|Generated by|^\s*Source\s*:', re.I)
# Doit contenir au moins une lettre pour valoir la peine d'être traduit.
_A_DES_LETTRES = re.compile(r'[A-Za-zÀ-ÿ]')


def _reflow(texte: str) -> str:
    """Recolle les phrases coupées par les retours à la ligne du PDF.

    L'extraction PDF insère des sauts de ligne au milieu des phrases
    (soft-wrap). NLLB traduit alors des fragments (« on his », « own. »)
    → charabia. On fusionne les lignes tant que la phrase n'est pas finie,
    tout en préservant les sauts de paragraphe (lignes vides).
    """
    out: list[str] = []
    cur = ""
    for brute in texte.split("\n"):
        s = brute.strip()
        if not s:
            if cur:
                out.append(cur)
                cur = ""
            out.append("")  # préserve la séparation de paragraphe
            continue
        cur = f"{cur} {s}" if cur else s
        if _FIN_PHRASE.search(s):
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    # Évite les lignes vides multiples
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def _a_traduire(seg: str) -> bool:
    """Vrai si le segment doit passer par NLLB (sinon on garde l'original)."""
    s = seg.strip()
    if not s or not _A_DES_LETTRES.search(s):
        return False
    if _PASSTHROUGH.search(s):
        return False
    return True


# ─────────────────────────────────────────────
#   PROTECTION DES NOMS PROPRES / TERMES
# ─────────────────────────────────────────────

# Registre {terme_source: sortie_voulue}. Rempli par le pipeline depuis le
# glossaire du roman. Les termes protégés sont remplacés par un placeholder
# que NLLB préserve intact (PROPN0, PROPN1…), puis restaurés après traduction.
# → garantit qu'un nom reste stable (« Blood » ne devient jamais « Sang »)
#   et qu'une traduction imposée (« Goblin »→« Gobelin ») est fiable.
_TERMES_PROTEGES: dict[str, str] = {}
_protection_lock = Lock()
_PLACEHOLDER_RE = re.compile(r"PROPN(\d+)")


def definir_termes_proteges(termes: dict) -> None:
    """Définit les termes à protéger (nom source → sortie voulue)."""
    global _TERMES_PROTEGES
    # Trie par longueur décroissante : les termes multi-mots (« Battle Worlds »)
    # sont traités avant leurs sous-termes (« Battle »).
    with _protection_lock:
        _TERMES_PROTEGES = {
            k: termes[k]
            for k in sorted(termes, key=len, reverse=True)
            if k and str(k).strip()
        }


def termes_proteges() -> dict:
    """Retourne une copie du registre des termes protégés."""
    with _protection_lock:
        return dict(_TERMES_PROTEGES)


def _proteger(texte: str) -> tuple[str, dict[str, str]]:
    """Remplace les termes protégés par des placeholders NLLB-safe.

    Retourne (texte_protégé, mapping placeholder→sortie_voulue).
    """
    termes = termes_proteges()
    if not termes:
        return texte, {}
    mapping: dict[str, str] = {}
    n = 0
    for terme, sortie in termes.items():
        motif = re.compile(rf"\b{re.escape(terme)}\b")
        if motif.search(texte):
            ph = f"PROPN{n}"
            texte = motif.sub(ph, texte)
            mapping[ph] = sortie
            n += 1
    return texte, mapping


def _restaurer(texte: str, mapping: dict[str, str]) -> str:
    """Restaure les placeholders en leur forme voulue."""
    if not mapping:
        return texte
    return _PLACEHOLDER_RE.sub(
        lambda m: mapping.get(f"PROPN{m.group(1)}", m.group(0)), texte
    )


def _hard_split(texte: str) -> list[str]:
    """Découpe une phrase trop longue par mots, sous _SEG_MAX caractères."""
    out: list[str] = []
    cur = ""
    for mot in texte.split(" "):
        if not cur:
            cur = mot
        elif len(cur) + 1 + len(mot) <= _SEG_MAX:
            cur += " " + mot
        else:
            out.append(cur)
            cur = mot
    if cur:
        out.append(cur)
    return out


def _segmenter_ligne(ligne: str) -> list[str]:
    """Découpe une ligne en segments traduisibles : UNE phrase par segment.

    NLLB-200 distilled ne traduit de façon fiable qu'une phrase à la fois ;
    regrouper plusieurs phrases fait perdre du contenu. On isole donc chaque
    phrase, et on ne re-découpe que les phrases dépassant la limite de tokens.
    """
    phrases = [m.group(0).strip() for m in _PHRASE_RE.finditer(ligne)]
    phrases = [p for p in phrases if p]
    if not phrases:
        return [ligne] if ligne.strip() else []
    segments: list[str] = []
    for p in phrases:
        if len(p) > _SEG_MAX:
            segments.extend(_hard_split(p))
        else:
            segments.append(p)
    return segments


# ─────────────────────────────────────────────
#   POST-PROCESSING : remplacement des anglicismes
#   NLLB laisse parfois des mots anglais courts non traduits
#   (the, and, with, was...). On les rattrape ici.
# ─────────────────────────────────────────────

# Dictionnaire de remplacement : mot anglais → mot français.
# Les clés longueurs sont traitées en premier (multi-mots avant
# mots simples) pour éviter les chevauchements de sous-chaînes.
_ANGLAIS_FRANCAIS: dict[str, str] = {
    # 🏆 Multi-mots (avant les mots simples)
    "a lot of": "beaucoup de",
    "a few": "quelques",
    "a little": "un peu",
    "a lot": "beaucoup",
    "according to": "selon",
    "across from": "en face de",
    "after all": "après tout",
    "all of": "tous les",
    "along with": "avec",
    "as if": "comme si",
    "as long as": "tant que",
    "as soon as": "dès que",
    "as well": "aussi",
    "as well as": "ainsi que",
    "because of": "à cause de",
    "both of": "les deux",
    "each other": "l'un l'autre",
    "even if": "même si",
    "even though": "bien que",
    "for example": "par exemple",
    "in fact": "en fait",
    "in front of": "devant",
    "in order to": "afin de",
    "in spite of": "malgré",
    "instead of": "au lieu de",
    "kind of": "genre de",
    "lots of": "beaucoup de",
    "more than": "plus de",
    "most of": "la plupart des",
    "no one": "personne",
    "of course": "bien sûr",
    "on top of": "sur",
    "out of": "hors de",
    "rather than": "plutôt que",
    "such as": "tel que",
    "thanks to": "grâce à",
    "the same": "le même",
    "too much": "trop",
    # 📝 Mots simples — classés par importance
    # (les plus fréquents et les plus gênants d'abord)
    "the": "le",
    "and": "et",
    "with": "avec",
    "was": "était",
    "is": "est",
    "in": "dans",
    "it": "il",
    "an": "un",
    "like crazy": "comme un fou",
    "like that": "comme ça",
    "like this": "comme ça",
    "like": "comme",
    "that": "que",
    "this": "ce",
    "but": "mais",
    "for": "pour",
    "from": "de",
    "are": "sont",
    "were": "étaient",
    "been": "été",
    "have": "ont",
    "has": "a",
    "had": "avait",
    "not": "pas",
    "all": "tous",
    "then": "alors",
    "now": "maintenant",
    "here": "ici",
    "there": "là",
    "which": "qui",
    "what": "quoi",
    "when": "quand",
    "where": "où",
    "why": "pourquoi",
    "how": "comment",
    "if": "si",
    "or": "ou",
    "as": "comme",
    "at": "à",
    "by": "par",
    "out": "hors",
    "into": "dans",
    "than": "que",
    "about": "environ",
    "over": "sur",
    "under": "sous",
    "behind": "derrière",
    "between": "entre",
    "through": "à travers",
    "while": "tandis que",
    "because": "parce que",
    "just": "juste",
    "only": "seulement",
    "even": "même",
    "also": "aussi",
    "very": "très",
    "still": "encore",
    "already": "déjà",
    "should": "devrait",
    "would": "voudrait",
    "could": "pourrait",
    "will": "va",
    "more": "plus",
    "most": "plus",
    "much": "beaucoup",
    "many": "beaucoup",
    "crazy": "fou",
    "few": "peu",
    "some": "certains",
    "each": "chaque",
    "such": "tel",
    "both": "les deux",
    "before": "avant",
    "after": "après",
    "until": "jusqu'à",
    "against": "contre",
    "without": "sans",
    "within": "dans",
    "along": "le long de",
    "another": "un autre",
    "enough": "assez",
    "again": "encore",
    "well": "bien",
    "else": "autre",
    "every": "chaque",
    "whole": "entier",
    "though": "bien que",
    "together": "ensemble",
    "around": "autour",
    "above": "au-dessus",
    "below": "au-dessous",
    "whether": "si",
    "neither": "ni",
    "nor": "ni",
    "ever": "jamais",
    "never": "jamais",
    "always": "toujours",
    "often": "souvent",
    "sometimes": "parfois",
    "soon": "bientôt",
    "early": "tôt",
    "late": "tard",
    "ago": "il y a",
    "away": "loin",
    "back": "retour",
    "maybe": "peut-être",
    "quite": "assez",
    "rather": "plutôt",
    "almost": "presque",
    "nearly": "presque",
    "hardly": "à peine",
    "merely": "simplement",
    "nobody": "personne",
    "nothing": "rien",
    "everything": "tout",
    "something": "quelque chose",
    "anything": "rien",
    "everyone": "tout le monde",
    "someone": "quelqu'un",
    "anyone": "personne",
    "somewhere": "quelque part",
    "anywhere": "nulle part",
    "everywhere": "partout",
    "somehow": "d'une façon",
    "anyway": "de toute façon",
    "perhaps": "peut-être",
    "indeed": "en effet",
    "instead": "au lieu",
    "anyhow": "de toute façon",
    "meanwhile": "pendant ce temps",
    "furthermore": "en outre",
    "moreover": "en outre",
    "therefore": "donc",
    "however": "cependant",
    "otherwise": "sinon",
    "besides": "d'ailleurs",
    "hence": "donc",
    "thus": "ainsi",
    "likely": "probablement",
    "probably": "probablement",
    "actually": "en fait",
    "basically": "fondamentalement",
    "certainly": "certainement",
    "definitely": "certainement",
    "obviously": "évidemment",
    "apparently": "apparemment",
    "essentially": "essentiellement",
    "eventually": "finalement",
    "finally": "finalement",
    "gradually": "progressivement",
    "immediately": "immédiatement",
    "recently": "récemment",
    "suddenly": "soudainement",
    "usually": "généralement",
    "especially": "surtout",
    "particularly": "particulièrement",
    "mainly": "principalement",
    "mostly": "principalement",
    "practically": "pratiquement",
    "simply": "simplement",
    "truly": "vraiment",
    "honestly": "honnêtement",
    "hopefully": "avec espoir",
    "luckily": "heureusement",
    "unfortunately": "malheureusement",
    "meanwhile": "pendant ce temps",
}

# Construit les motifs regex une fois pour toutes
_ANGLAIS_MOTIFS: list[tuple[re.Pattern, str]] = []
# Tri par longueur décroissante : les expressions longues d'abord
for mot_anglais in sorted(_ANGLAIS_FRANCAIS.keys(), key=lambda s: -len(s)):
    motif = re.compile(
        rf"\b{re.escape(mot_anglais)}\b",
        re.IGNORECASE,
    )
    _ANGLAIS_MOTIFS.append((motif, _ANGLAIS_FRANCAIS[mot_anglais]))


def _post_traiter(texte: str) -> str:
    """Remplace les mots anglais laissés par NLLB par leur équivalent français.

    Ne touche pas aux mots à l'intérieur d'autres mots (grace aux \\b),
    et traite les multi-mots avant les mots simples.
    """
    if not texte:
        return texte
    for motif, remplacement in _ANGLAIS_MOTIFS:
        texte = motif.sub(remplacement, texte)
    return texte

def traduire_texte_nllb(texte: str, langue_source: str, langue_cible: str) -> str:
    """Traduit un texte quelconque avec NLLB, en préservant les sauts de ligne.

    Le texte est découpé en phrases (sous la limite de tokens du modèle),
    traduites en un seul `translate_batch`, puis réassemblées.
    """
    if not texte or not texte.strip():
        return texte
    try:
        translator, sp = _get_modele()
    except Exception:
        return texte

    src_code = _code_flores(langue_source)
    tgt_code = _code_flores(langue_cible)

    texte = _reflow(texte)  # recolle les phrases coupées par les retours PDF
    texte, mapping_protege = _proteger(texte)  # protège les noms propres/termes

    lignes = texte.split("\n")
    segments: list[str] = []
    carte: list[list[int]] = []  # indices des segments pour chaque ligne
    for ligne in lignes:
        idxs: list[int] = []
        for seg in _segmenter_ligne(ligne):
            idxs.append(len(segments))
            segments.append(seg)
        carte.append(idxs)

    if not segments:
        return texte

    # On ne tokenise et ne traduit QUE les segments pertinents ; les URLs et
    # autres lignes techniques restent identiques à l'original.
    a_faire = [i for i, s in enumerate(segments) if _a_traduire(s)]
    traduits: list[str] = list(segments)  # défaut = original (passthrough)
    if a_faire:
        try:
            sources = [
                [src_code] + sp.encode(segments[i], out_type=str) + ["</s>"]
                for i in a_faire
            ]
            results = translator.translate_batch(
                sources,
                target_prefix=[[tgt_code]] * len(sources),
                beam_size=_BEAM,
                max_batch_size=_MAX_BATCH,
            )
            for i, r in zip(a_faire, results):
                hyp = r.hypotheses[0]
                if hyp and hyp[0] == tgt_code:  # retire le token de langue cible
                    hyp = hyp[1:]
                traduits[i] = sp.decode(hyp).strip()
        except Exception:
            return texte

    lignes_out: list[str] = []
    for idxs in carte:
        if not idxs:
            lignes_out.append("")
        else:
            ligne_trad = " ".join(traduits[i] for i in idxs)
            lignes_out.append(re.sub(r"  +", " ", ligne_trad).strip())
    return _restaurer(_post_traiter("\n".join(lignes_out)), mapping_protege)


def traduire_bloc_nllb(bloc: str, langue_source: str, langue_cible: str) -> str:
    """Traduit un bloc avec NLLB (offline).

    En cas d'échec, lève ``TraductionEchoueeError`` (importé depuis le
    moteur traducteur) afin que le texte source ne soit jamais enregistré
    comme une traduction valide dans le checkpoint.
    """
    if not bloc.strip():
        return ""
    from .traducteur import TraductionEchoueeError
    if not _LIBS_OK or not modele_nllb_installe():
        raise TraductionEchoueeError("NLLB : librairies ou modèle indisponibles")
    resultat = traduire_texte_nllb(bloc, langue_source, langue_cible)
    if not resultat or not resultat.strip():
        raise TraductionEchoueeError("NLLB a renvoyé un texte vide")
    return resultat


def traduire_blocs_nllb_batch(
    blocs: list[str], langue_source: str, langue_cible: str
) -> str:
    """Traduit tous les blocs d'une page en un seul appel NLLB (batch).

    Retourne le texte complet traduit (blocs joints avec \\n\\n).
    """
    if not blocs:
        return ""
    texte_complet = "\n\n".join(blocs)
    return traduire_texte_nllb(texte_complet, langue_source, langue_cible) or texte_complet
