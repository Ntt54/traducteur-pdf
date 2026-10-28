#!/usr/bin/env python3
"""
Construction d'un EPUB à partir des PDF déjà traduits.

Le module parcourt un dossier de PDF traduits (``pdfs_traduits/<roman>``),
détecte les entêtes de chapitres dans le texte extrait, puis assemble un EPUB
avec une table des matières du type ``Chapitre 12 : Le jour du commencement``.

Particularités :

* les PDF sont lus avec ``pypdf`` (rapide, pas de rendu) ;
* les entêtes reconnues couvrent les différentes formes produites par les
  traductions : ``Chapitre 12``, ``Chapter 12``, ``Chapitre 12 : titre``,
  ``CHAPITRE 12 TITRE`` (parfois collé au corps du texte), ``Prologue``, etc. ;
* les pages de sommaire présentes dans certains PDF sont ignorées ;
* un cache par PDF permet de ne ré-extraire que les nouveaux fichiers : la
  mise à jour d'un EPUB ne reprend donc pas tout depuis le début ;
* le fichier EPUB est réécrit de façon atomique (temporaire puis remplacement).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

try:  # pypdf est déjà une dépendance du projet
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - dépendance normalement présente
    PdfReader = None  # type: ignore[assignment]

try:
    from ebooklib import epub
    HAS_EPUBLIB = True
except ImportError:  # pragma: no cover - dépendance normalement présente
    epub = None  # type: ignore[assignment]
    HAS_EPUBLIB = False

from .utils import tri_naturel

# ─────────────────────────────────────────────
#   CONSTANTES
# ─────────────────────────────────────────────

ETAT_VERSION = 1
PARSEUR_VERSION = 18

DOSSIER_ETAT = ".epub_build"
NOM_ETAT = "state.json"
NOM_CACHE = "cache"

# Un chapitre traduit "utile" fait toujours plus que cela. Cela permet
# d'éliminer les entrées de sommaire (corps vide) et les faux positifs.
MIN_CARACTERES_CHAPITRE = 250
MIN_CARACTERES_CHAPITRE_NOMME = 60

# Caractères de fin de phrase / de titre.
_RE_FIN = re.compile(r"[.!?…»\"’”\])}]\s*$")
_RE_ENTETE_NUM = re.compile(
    r"(?<![\w])"
    r"(?P<kw>chapitre|chapter|chap\.?|ch\.?)"
    r"[ \t]*[:.\-–—]?[ \t]*"
    r"(?P<num>\d+(?:[.\-]\d+)*)",
    re.IGNORECASE,
)
_RE_ENTETE_NOMME = re.compile(
    r"^\s*(?P<kw>prologue|épilogue|epilogue|interlude|bonus|extra|"
    r"avant-propos|après-propos|préface)\b(?P<reste>.*)$",
    re.IGNORECASE,
)
_RE_PAGE = re.compile(
    r"^[—\-–]?\s*Page\s+\d+\s*/\s*\d+\s*[—\-–]?$", re.IGNORECASE
)
_RE_LIGNE_PARASITE = re.compile(
    r"^(?:Aucun contenu disponible|#\d+|Traduit\s+EN\s*→\s*FR.*|"
    r"Produit par .*|Source\s*:.*|"
    r"(?:machine\s+)?translated\s+by\s+google.*|"
    r"traduit\s+(?:automatiquement\s+)?par\s+google.*|"
    r"ce\s+document\s+a\s+été\s+traduit\s+automatiquement.*|"
    r"https?://translate\.google\.com/?.*)$",
    re.IGNORECASE,
)
# Mention ajoutée par Google Traduction, parfois collée au texte de la page.
_RE_GOOGLE_INLINE = re.compile(
    r"(?i)\s*(?:machine\s+translated\s+by\s+google|"
    r"traduit\s+(?:automatiquement\s+)?par\s+google)\s*"
)
_RE_SEPARATEURS = " \t:;,\u2013\u2014-_." + "•·"
_NOMS_SPECIAUX = (
    "prologue", "épilogue", "epilogue", "interlude", "bonus", "extra",
    "avant-propos", "après-propos", "préface",
)

# Débuts de phrase fréquents permettant de séparer un titre du corps quand
# Google a collé les deux sans ponctuation : « Chapitre 497 Un peu froid
# Zhou Wen savait... ».
_DEBUTS_CORPS = frozenset({
    "Zhou", "Lu", "Jiang", "Gu", "Xia", "John", "Li", "Wang", "Yu", "An",
    "Xu", "Sun", "Fang", "Bai", "Tian", "Shen", "Qin", "Zhao", "Qian",
    "Après", "Lorsque", "Quand", "Il", "Elle", "Ils", "Elles", "Ce",
    "Cette", "Ces", "Dans", "Mais", "Cependant", "Pourtant", "Soudain",
    "Alors", "Comme", "Tout", "Deux", "Trois", "Quatre", "Cinq", "Six",
    "Sept", "Huit", "Neuf", "Dix", "En", "À", "Au", "Aux", "Pour", "Par",
    "Sur", "Sous", "Avec", "Sans", "Tandis", "Pendant", "Depuis",
    "Ensuite", "Puis", "Enfin", "Bien", "Même", "Son", "Sa", "Ses",
    "Leur", "Le", "La", "Les", "Un", "Une", "Des", "Du", "De",
})


# ─────────────────────────────────────────────
#   DATACLASSES
# ─────────────────────────────────────────────

@dataclass
class ChapitreEpub:
    """Un chapitre prêt à être écrit dans l'EPUB."""

    numero: str = ""
    numero_affichage: str = ""
    titre: str = ""
    texte: str = ""
    source: str = ""
    statut: str = "connu"
    ordre: int = 0
    fichier_ordre: int = 0

    @property
    def label(self) -> str:
        """Libellé de la table des matières."""
        if self.numero.startswith("partie:"):
            return self.numero_affichage or "Partie"
        if self.numero in ("prologue", "épilogue", "epilogue", "interlude",
                           "bonus", "extra", "avant-propos", "après-propos",
                           "préface"):
            base = self.numero_affichage or self.numero.capitalize()
            return f"{base} : {self.titre}" if self.titre else base
        base = f"Chapitre {self.numero_affichage or self.numero}"
        return f"{base} : {self.titre}" if self.titre else base

    @property
    def longueur(self) -> int:
        return len(re.sub(r"\s", "", self.texte or ""))


@dataclass
class AnalyseEpub:
    """Résultat d'un scan de dossier, avant génération de l'EPUB."""

    dossier: str
    pdfs: list[str] = field(default_factory=list)
    chapitres: list[ChapitreEpub] = field(default_factory=list)
    sources_nouvelles: int = 0
    sources_modifiees: int = 0
    sources_connues: int = 0
    epub_existant: Optional[str] = None
    chemin_epub: Optional[str] = None

    def resume(self) -> str:
        parties = [
            f"{len(self.pdfs)} PDF",
            f"{len(self.chapitres)} chapitre(s)",
            f"{self.sources_nouvelles} nouveau(x)",
            f"{self.sources_modifiees} modifié(s)",
            f"{self.sources_connues} déjà indexé(s)",
        ]
        return " · ".join(parties)


# ─────────────────────────────────────────────
#   NETTOYAGE / DÉTECTION DES ENTÊTES
# ─────────────────────────────────────────────

def _nettoyer_ligne(ligne: str) -> str:
    ligne = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\ufeff]", "", ligne)
    # Les PDF issus de Google/PDFium utilisent des espaces insécables et des
    # espaces multiples pour simuler la mise en page. On les normalise pour
    # que les entêtes « Chapitre 1 : ... » restent détectables.
    ligne = ligne.replace("\u00a0", " ").replace("\u202f", " ")
    ligne = re.sub(r"[ \t]+", " ", ligne)
    return ligne.strip()


def _cle_chapitre(numero: str, titre: str) -> str:
    """Clé de déduplication : les sections nommées peuvent se répéter.

    Deux « Bonus » ou deux « Interlude » de titres différents sont deux
    chapitres distincts ; seul le même titre est considéré comme un doublon.
    """
    if numero in _NOMS_SPECIAUX:
        return f"{numero}|{(titre or '').strip().lower()}"
    return numero


def _canon_numero(brut: str) -> tuple[str, tuple[int, ...]]:
    """Canonise un numéro de chapitre (``150.1``, ``244-151``...)."""
    morceaux = [int(x) for x in re.findall(r"\d+", brut)]
    if not morceaux:
        return "", ()
    return ".".join(str(x) for x in morceaux), tuple(morceaux)


def _affichage_numero(brut: str, canon: str) -> str:
    """Conserve la forme lisible d'origine (``244-151``) sans espaces."""
    brut = re.sub(r"\s+", "", brut or "")
    if "-" in brut and "." not in brut:
        return brut
    return canon


def _majuscule_initiale(mot: str) -> str:
    if not mot:
        return mot
    if any(c.isalpha() for c in mot):
        return mot[0].upper() + mot[1:].lower()
    return mot


def _title_case(texte: str) -> str:
    return " ".join(_majuscule_initiale(m) for m in texte.split())


def _coeur_mot(mot: str) -> str:
    return mot.strip(".,;:!?()[]{}«»\"'’‘“”–—-")


def _serie_majuscules(reste: str) -> tuple[str, str]:
    """Extrait une suite de mots en MAJUSCULES au début de ``reste``.

    Retourne ``(titre, corps)``. Sert aux PDF où l'entête est collée au texte
    (``CHAPITRE 12 LE JOUR DU COMMENCEMENT Il était une fois...``).
    """
    mots = list(re.finditer(r"\S+", reste))
    retenus: list[str] = []
    debut = False
    coupe = len(reste)

    for idx, m in enumerate(mots):
        mot = m.group(0)
        coeur = _coeur_mot(mot)
        if coeur and any(c.isalpha() for c in coeur):
            if coeur.upper() == coeur:
                # Une lettre seule suivie d'un mot en minuscules marque
                # généralement le début de la phrase ("TROLL A la fin").
                if len(coeur) == 1 and idx + 1 < len(mots):
                    suivant = _coeur_mot(mots[idx + 1].group(0))
                    if suivant and suivant[:1].islower():
                        coupe = m.start()
                        break
                retenus.append(mot)
                debut = True
            else:
                coupe = m.start()
                break
        else:
            if debut:
                sans_ponctuation = coeur.strip("()[]{}«»\"'’‘“”")
                numerique = (
                    sans_ponctuation.replace(".", "").replace("-", "").isdigit()
                )
                if numerique or mot in ("–", "—", "-", "/", "."):
                    retenus.append(mot)
                    continue
                coupe = m.start()
                break

    return " ".join(retenus).strip(), reste[coupe:].lstrip()


def _nettoyer_titre(reste: str, numero: str, inline: bool) -> tuple[str, str, str]:
    """Nettoie le reste d'une ligne d'entête.

    Retourne ``(titre, corps_sur_la_meme_ligne, numero)``.
    """
    reste = reste or ""

    # "Chapitre 150 — .1 - ÉPISODE..." → chapitre 150.1
    m_sub = re.match(r"^\s*[.\-–—]\s*\.\s*(\d+)\b", reste)
    if m_sub:
        numero = f"{numero}.{m_sub.group(1)}"
        reste = reste[m_sub.end():]

    # Enlève les répétitions du type "Chapitre 448 : Chapitre 448 ...".
    for _ in range(3):
        reste = reste.lstrip(_RE_SEPARATEURS)
        m = re.match(
            r"(?i)^(?:chapitre|chapter|chap\.?|ch\.?)\s*\d+(?:[.\-]\d+)*\s*"
            r"[:.\-–—]*\s*",
            reste,
        )
        if m:
            reste = reste[m.end():]
            continue
        # "362" ou "72 :" répété après le tiret.
        m2 = re.match(r"^(\d+(?:[.\-]\d+)*)\s*([:.\-–—,])\s*", reste)
        if m2:
            reste = reste[m2.end():]
            continue
        break

    reste = reste.lstrip(_RE_SEPARATEURS)
    reste = re.sub(r"^[.\-–—:;,•·\s]+", "", reste)
    reste = re.sub(r"\s+", " ", reste).strip()

    # Google colle parfois le début du corps au titre :
    # « Chapitre 526 : Comprendre l'immortel volant. Étrangement, ... ».
    # On coupe après la première phrase du titre pour ne pas avaler le texte.
    corps_apres_titre = ""
    m_phrase = re.match(
        r"^(.+?[.!?…])\s+(?=[A-ZÀ-ÖØ-Ý«\"'“])", reste
    )
    if m_phrase and len(m_phrase.group(1)) <= 110:
        corps_apres_titre = reste[m_phrase.end():].strip()
        reste = m_phrase.group(1).rstrip(" .!?…")

    if inline:
        titre, corps = _serie_majuscules(reste)
        if not titre:
            corps = ""
        corps = " ".join(x for x in (corps_apres_titre, corps) if x)
        return _title_case(titre), corps.rstrip(), numero

    reste = re.sub(r"[\s:;,\-–—_.•·]+$", "", reste)
    titre, corps = _serie_majuscules(reste)
    if not titre:
        # Titre en casse normale : tout « reste » est le titre, pas le corps.
        corps = ""
    corps = " ".join(x for x in (corps_apres_titre, corps) if x)
    if titre and corps:
        return _title_case(titre), corps.rstrip(), numero
    if titre and not corps and any(c.isalpha() for c in reste) and reste.upper() == reste:
        return _title_case(titre), "", numero
    return reste, corps.rstrip(), numero


def _corps_colle(titre: str, titre_connu: str) -> str:
    """Retire un titre dupliqué collé au début du corps.

    Utilisé quand Google produit « Chapitre 497 Un peu froid Zhou Wen... »
    juste après l'entête propre « Chapitre 497 : Un peu froid ».
    """
    mots = (titre or "").split()
    if not mots:
        return ""
    # Le titre connu donne une longueur approximative ; la variante traduite
    # peut différer d'un mot. On cherche ensuite un vrai début de phrase.
    depart = max(1, len((titre_connu or "").split()) - 1)
    for i in range(depart, len(mots)):
        brut = mots[i]
        if brut[:1] in "«\"“":
            return " ".join(mots[i:])
        coeur = _coeur_mot(brut)
        if coeur in _DEBUTS_CORPS:
            return " ".join(mots[i:])
    return ""


def _detecter_entete(ligne: str) -> Optional[dict]:
    """Détecte une ligne d'entête de chapitre.

    Retourne un dict ``{num, titre, corps, prefixe, debut_ligne}`` ou None.
    """
    m = _RE_ENTETE_NUM.search(ligne)
    if m:
        prefixe = ligne[:m.start()]
        mot = m.group("kw")
        debut_ligne = not prefixe.strip()
        # En plein texte, on n'accepte que les entêtes en MAJUSCULES ou
        # précédées uniquement de ponctuation/chiffres. Cela évite
        # « Le chapitre 12 explique... ».
        prefixe_nu = prefixe.strip()
        prefixe_muet = not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", prefixe_nu)
        if (debut_ligne or mot.isupper()
                or (len(prefixe_nu) < 10 and prefixe_muet)):
            numero, _ = _canon_numero(m.group("num"))
            titre, corps, numero = _nettoyer_titre(
                ligne[m.end():], numero, inline=not debut_ligne
            )
            return {
                "num": numero,
                "titre": titre,
                "corps": corps,
                "prefixe": prefixe.strip(),
                "debut_ligne": debut_ligne,
                "affiche": _affichage_numero(m.group("num"), numero),
            }
        # Sinon, ce n'est pas un entête en début de ligne : on laisse la
        # détection « Titre du chapitre 525 » ci-dessous tenter sa chance.

    # Forme traduite par Google : « Défi officiel du chapitre 525 ».
    # Le numéro est après le titre, donc _RE_ENTETE_NUM ne peut pas le voir.
    m3 = re.match(
        r"(?i)^(?P<titre>.+?)\s+(?:du\s+|de\s+la\s+|des\s+)?"
        r"chapitre\s+(?P<num>\d+)\s*$",
        ligne.strip(),
    )
    if (
        m3
        and len(ligne.strip()) <= 120
        and len(m3.group("titre").split()) <= 8
        and not _RE_FIN.search(ligne)
    ):
        titre = m3.group("titre").strip(" :;,­–—.-")
        if titre and (titre[0].isupper() or titre.upper() == titre):
            numero, _ = _canon_numero(m3.group("num"))
            return {
                "num": numero,
                "titre": _title_case(titre),
                "corps": "",
                "prefixe": "",
                "debut_ligne": True,
                "affiche": _affichage_numero(m3.group("num"), numero),
            }

    m2 = _RE_ENTETE_NOMME.match(ligne)
    if m2 and len(ligne.strip()) <= 80:
        mot = m2.group("kw").lower().replace("epilogue", "épilogue")
        titre, corps, _ = _nettoyer_titre(m2.group("reste"), "", inline=False)
        if len(titre) > 60 or corps:
            return None
        # « Bonus : gagnée en tuant... » est une ligne de statistiques, pas
        # un titre de chapitre : un vrai titre commence par une majuscule.
        if titre and titre[0].islower():
            return None
        return {
            "num": mot,
            "titre": titre,
            "corps": corps,
            "prefixe": "",
            "debut_ligne": True,
            "affiche": mot.capitalize(),
        }
    return None


# ─────────────────────────────────────────────
#   PAGES / PARAGRAPHES
# ─────────────────────────────────────────────

def _nettoyer_page(texte: str) -> str:
    lignes = []
    for brute in texte.splitlines():
        ligne = _RE_GOOGLE_INLINE.sub(" ", _nettoyer_ligne(brute)).rstrip()
        nue = ligne.strip()
        if not nue:
            continue
        if _RE_PAGE.match(nue) or _RE_LIGNE_PARASITE.match(nue):
            continue
        lignes.append(ligne)
    return "\n".join(lignes)


def _page_est_sommaire(lignes: Iterable[str]) -> bool:
    """Détecte les pages de sommaire (entêtes, listes numérotées, peu de corps)."""
    nb_entetes = 0
    longueur_entetes = 0
    longueur_corps = 0
    nb_entrees = 0
    longueur_entrees = 0
    total = 0
    for ligne in lignes:
        if not ligne.strip():
            continue
        total += len(ligne)
        if _detecter_entete(ligne):
            nb_entetes += 1
            longueur_entetes += len(ligne)
        elif re.match(r"^\s*\d{1,4}\.\s+\S", ligne) and len(ligne.strip()) < 100:
            nb_entrees += 1
            longueur_entrees += len(ligne)
        else:
            longueur_corps += len(ligne)
    if not total:
        return False
    if nb_entetes >= 3 and (longueur_entetes / total) >= 0.45:
        return True
    if nb_entrees >= 6 and (longueur_entrees / total) >= 0.45:
        return True
    return False


def _texte_est_sommaire(texte: str) -> bool:
    """Vrai si le texte ressemble à une liste numérotée de titres (sommaire)."""
    entrees = re.findall(r"\b\d{1,4}\.\s+[A-ZÀ-ÖØ-Ý]", texte)
    return len(entrees) >= 8


def _reflow(lignes: list[str]) -> str:
    """Reconstitue des paragraphes lisibles à partir des lignes du PDF."""
    paragraphes: list[str] = []
    tampon: list[str] = []

    def vider():
        if tampon:
            paragraphes.append(" ".join(tampon))
            tampon.clear()

    for brute in lignes:
        ligne = brute.strip()
        if not ligne:
            vider()
            continue
        if not tampon:
            tampon.append(ligne)
            continue

        precedent = tampon[-1]
        longueur = len(" ".join(tampon))
        fin_phrase = bool(_RE_FIN.search(precedent))
        debut_paragraphe = ligne[:1] in "\"«'“‘–—([{#•"

        if fin_phrase and longueur >= 190 and (
            debut_paragraphe or ligne[:1].isupper() or longueur >= 650
        ):
            vider()
            tampon.append(ligne)
        else:
            tampon.append(ligne)

    vider()
    return "\n\n".join(paragraphes)


def _numero_partie(source: str, fichier_ordre: int) -> int:
    nom = os.path.basename(source or "")
    m = re.search(r"(?i)(?:^|[_:\-\s])part(?:ie)?[_\-\s]*(\d+)", nom)
    return int(m.group(1)) if m else fichier_ordre + 1


def _parse_lignes(texte: str, source: str = "", fichier_ordre: int = 0) -> list[dict]:
    """Analyse un texte déjà nettoyé et retourne les chapitres bruts."""
    chapitres: list[dict] = []
    courant: Optional[dict] = None
    corps: list[str] = []
    avant: list[str] = []
    vient_entete = False
    vu_entete = False

    def vider():
        nonlocal courant, corps
        if courant is not None:
            courant["texte"] = _reflow(corps)
            chapitres.append(courant)
        courant = None
        corps = []

    lignes = [_nettoyer_ligne(l).rstrip() for l in texte.splitlines()]
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        if not ligne.strip():
            i += 1
            continue

        entete = _detecter_entete(ligne)
        if entete:
            vu_entete = True
            # Entêtes dupliquées du même chapitre : on garde le meilleur titre
            # et on continue le même chapitre (évite de couper le corps).
            meme_nom = (
                courant is not None
                and courant["num"] == entete["num"]
                and (
                    courant["num"] not in _NOMS_SPECIAUX
                    or courant["titre"].strip().lower()
                    == entete["titre"].strip().lower()
                )
            )
            if meme_nom:
                if entete["prefixe"]:
                    corps.append(entete["prefixe"])
                corps_dup = entete["corps"]
                titre_colle = bool(corps_dup)
                if not corps_dup and len(entete["titre"]) > len(courant["titre"]) + 25:
                    # Titre dupliqué + corps sur la même ligne, sans
                    # ponctuation pour les séparer.
                    corps_dup = _corps_colle(entete["titre"], courant["titre"])
                    titre_colle = bool(corps_dup)
                if not titre_colle and entete["titre"]:
                    ancien_nu = re.sub(r"\D", "", courant["titre"] or "")
                    if (not courant["titre"]
                            or (ancien_nu and ancien_nu == courant["titre"].strip())
                            or len(entete["titre"]) > len(courant["titre"])):
                        courant["titre"] = entete["titre"]
                if corps_dup:
                    corps.append(corps_dup)
                vient_entete = len(corps) == 0
                i += 1
                continue

            vider()
            courant = {
                "num": entete["num"],
                "titre": entete["titre"],
                "affiche": entete["affiche"],
                "source": source,
                "fichier_ordre": fichier_ordre,
                "ordre": len(chapitres),
            }
            if entete["prefixe"]:
                corps.append(entete["prefixe"])
            vient_entete = True
            i += 1

            # Le titre en MAJUSCULES peut continuer sur la ligne suivante
            # (PDF où l'entête est collée au texte, parfois même en début de
            # ligne). On ne consomme que des mots réellement en majuscules.
            if entete["corps"]:
                corps.append(entete["corps"])
            garde = 0
            while garde < 2 and i < len(lignes):
                suivante = lignes[i]
                if not suivante.strip() or _detecter_entete(suivante):
                    break
                titre_sup, reste = _serie_majuscules(suivante)
                if not titre_sup:
                    break
                courant["titre"] = (
                    f"{courant['titre']} {titre_sup}".strip()
                    if courant["titre"] else titre_sup
                )
                courant["titre"] = _title_case(courant["titre"])
                if reste:
                    corps.append(reste)
                i += 1
                garde += 1
                if reste:
                    break
            vient_entete = False
            continue

        if courant is None:
            avant.append(ligne)
        elif (
            vient_entete
            and courant["titre"]
            and not _RE_FIN.search(courant["titre"])
            and len(ligne) <= 50
            and ligne[:1].islower()
        ):
            courant["titre"] = f"{courant['titre']} {ligne.strip()}".strip()
            vient_entete = False
        else:
            corps.append(ligne)
            vient_entete = False
        i += 1

    vider()

    # Texte situé avant le premier entête : souvent un chapitre dont le titre
    # n'a pas été traduit. On le conserve s'il est assez long pour être du
    # vrai contenu (et non un sommaire ou une page de garde).
    avant_texte = _reflow([l for l in avant if l.strip()])
    if (
        vu_entete
        and len(re.sub(r"\s", "", avant_texte)) >= 3000
        and not _texte_est_sommaire(avant_texte)
    ):
        numero = _numero_partie(source, fichier_ordre)
        chapitres.insert(0, {
            "num": f"partie:{fichier_ordre}:debut",
            "titre": "",
            "affiche": f"Partie {numero} (début)",
            "source": source,
            "fichier_ordre": fichier_ordre,
            "ordre": -1,
            "texte": avant_texte,
        })
    return chapitres


def _extraire_pages_pdf(chemin_pdf: str) -> list[str]:
    """Lit les pages d'un PDF dans l'ordre visuel.

    ``pdftotext`` (poppler) est utilisé en priorité : il est très rapide et
    respecte l'ordre de lecture des PDF produits par Google/PDFium, dont les
    objets texte ne sont pas stockés dans l'ordre des paragraphes. Sans lui,
    pypdf peut renvoyer les phrases dans le désordre.
    """
    try:
        proc = subprocess.run(
            ["pdftotext", "-q", "-enc", "UTF-8", chemin_pdf, "-"],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            pages = proc.stdout.split("\f")
            if pages and not pages[-1].strip():
                pages.pop()
            if pages:
                return pages
    except (OSError, subprocess.SubprocessError):
        pass

    if PdfReader is None:
        raise ImportError("pypdf n'est pas installé (pip install pypdf)")
    lecteur = PdfReader(chemin_pdf)
    pages = []
    for page in lecteur.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        except (TypeError, ValueError):
            pages.append(page.extract_text() or "")
    return pages


def _extraire_chapitres_pdf(chemin_pdf: str, fichier_ordre: int = 0) -> list[dict]:
    """Extrait les chapitres d'un PDF traduit."""
    try:
        pages = _extraire_pages_pdf(chemin_pdf)
    except Exception as exc:
        raise RuntimeError(f"Lecture impossible de {os.path.basename(chemin_pdf)} : {exc}")

    # Écarte les pages de sommaire, fréquentes dans certains EPUB convertis.
    pages_utiles: list[str] = []
    for page in pages:
        nettoyee = _nettoyer_page(page)
        lignes = [l for l in nettoyee.splitlines() if l.strip()]
        if lignes and _page_est_sommaire(lignes):
            continue
        pages_utiles.append(nettoyee)

    texte = "\n\n".join(pages_utiles)
    chapitres = _parse_lignes(texte, source=chemin_pdf, fichier_ordre=fichier_ordre)

    if not chapitres:
        # Aucun entête reconnue (roman sans titres, PDF ancien...) : on garde
        # le fichier comme une « partie » pour ne rien perdre.
        corps = _reflow([l for l in texte.splitlines() if l.strip()])
        if len(re.sub(r"\s", "", corps)) < MIN_CARACTERES_CHAPITRE:
            return []
        nom = os.path.basename(chemin_pdf)
        m = re.search(r"(?i)(?:^|[_\-\s])part(?:ie)?[_\-\s]*(\d+)", nom)
        numero_partie = int(m.group(1)) if m else fichier_ordre + 1
        return [{
            "num": f"partie:{fichier_ordre}",
            "titre": "",
            "affiche": f"Partie {numero_partie}",
            "source": chemin_pdf,
            "fichier_ordre": fichier_ordre,
            "ordre": 0,
            "texte": corps,
        }]

    # Déduplique les entrées de sommaire / entêtes répétées du même fichier :
    # on garde la version qui possède le plus de texte.
    meilleurs: dict[str, dict] = {}
    for idx, ch in enumerate(chapitres):
        ch.setdefault("ordre", idx)
        cle = _cle_chapitre(ch["num"], ch.get("titre", ""))
        ancien = meilleurs.get(cle)
        if ancien is None or len(ch.get("texte", "")) > len(ancien.get("texte", "")):
            meilleurs[cle] = ch

    resultat = list(meilleurs.values())
    resultat.sort(key=lambda c: c.get("ordre", 0))
    for idx, ch in enumerate(resultat):
        ch["ordre"] = idx
    return resultat


# ─────────────────────────────────────────────
#   ÉTAT / CACHE INCRÉMENTAL
# ─────────────────────────────────────────────

def _dossier_etat(dossier: str) -> str:
    return os.path.join(dossier, DOSSIER_ETAT)


def _chemin_etat(dossier: str) -> str:
    return os.path.join(_dossier_etat(dossier), NOM_ETAT)


def _charger_etat(dossier: str) -> dict:
    chemin = _chemin_etat(dossier)
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            etat = json.load(f)
        if isinstance(etat, dict) and etat.get("version") == ETAT_VERSION:
            etat.setdefault("sources", {})
            return etat
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": ETAT_VERSION, "sources": {}, "epub": None}


def _sauver_etat(dossier: str, etat: dict) -> None:
    os.makedirs(_dossier_etat(dossier), exist_ok=True)
    chemin = _chemin_etat(dossier)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def _chemin_cache(dossier: str, chemin_pdf: str) -> str:
    rel = os.path.relpath(chemin_pdf, dossier)
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_dossier_etat(dossier), NOM_CACHE, f"{digest}.json")


def _empreinte(chemin: str) -> str:
    st = os.stat(chemin)
    return f"{st.st_size}:{st.st_mtime_ns}"


def _lire_cache(chemin_cache: str) -> Optional[list[dict]]:
    try:
        with open(chemin_cache, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("chapitres"), list):
            return data["chapitres"]
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _ecrire_cache(chemin_cache: str, chapitres: list[dict], empreinte: str) -> None:
    os.makedirs(os.path.dirname(chemin_cache), exist_ok=True)
    tmp = chemin_cache + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {"version": PARSEUR_VERSION, "empreinte": empreinte,
             "chapitres": chapitres},
            f, ensure_ascii=False,
        )
    os.replace(tmp, chemin_cache)


def _lister_pdfs(dossier: str) -> list[str]:
    fichiers: list[str] = []
    for racine, dossiers, noms in os.walk(dossier):
        dossiers[:] = [
            d for d in dossiers
            if not d.startswith(".") and d != DOSSIER_ETAT
        ]
        for nom in noms:
            if nom.lower().endswith(".pdf"):
                fichiers.append(os.path.join(racine, nom))
    fichiers.sort(key=lambda p: tri_naturel(os.path.relpath(p, dossier)))
    return fichiers


# ─────────────────────────────────────────────
#   ANALYSE
# ─────────────────────────────────────────────

def analyser_dossier(
    dossier: str,
    force: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
) -> AnalyseEpub:
    """Scanne un dossier de PDF traduits et prépare la liste des chapitres.

    Les PDF inchangés sont lus depuis le cache ; seuls les nouveaux ou les PDF
    modifiés sont ré-extraits. Aucun EPUB n'est encore écrit ici.
    """
    log = on_log or (lambda _m: None)
    dossier = os.path.abspath(dossier)
    if not os.path.isdir(dossier):
        raise ValueError(f"Dossier introuvable : {dossier}")

    etat = _charger_etat(dossier)
    if force:
        log("Ré-analyse forcée : tous les PDF vont être relus.")
    pdfs = _lister_pdfs(dossier)
    log(f"{len(pdfs)} PDF trouvé(s) dans {dossier}")

    sources: dict[str, dict] = {}
    tous: list[ChapitreEpub] = []
    nouvelles = modifiees = connues = 0

    for idx, chemin in enumerate(pdfs, 1):
        rel = os.path.relpath(chemin, dossier)
        empreinte = _empreinte(chemin)
        ancien = etat["sources"].get(rel)
        cache = _chemin_cache(dossier, chemin)
        statut = "connu"

        chapitres_bruts: Optional[list[dict]] = None
        if (
            not force
            and ancien
            and ancien.get("empreinte") == empreinte
            and ancien.get("parseur") == PARSEUR_VERSION
        ):
            chapitres_bruts = _lire_cache(cache)
            if chapitres_bruts is None:
                chapitres_bruts = None  # cache perdu → ré-extraction

        if chapitres_bruts is None:
            statut = "modifie" if ancien else "nouveau"
            log(f"[{idx}/{len(pdfs)}] Extraction : {rel}")
            try:
                chapitres_bruts = _extraire_chapitres_pdf(chemin, fichier_ordre=idx - 1)
            except Exception as exc:
                log(f"  ⚠️ {rel} ignoré : {exc}")
                chapitres_bruts = []
            _ecrire_cache(cache, chapitres_bruts, empreinte)
        else:
            log(f"[{idx}/{len(pdfs)}] Déjà indexé : {rel}")

        sources[rel] = {
            "empreinte": empreinte,
            "parseur": PARSEUR_VERSION,
            "cache": os.path.relpath(cache, dossier),
            "chapitres": len(chapitres_bruts),
        }
        if statut == "nouveau":
            nouvelles += 1
        elif statut == "modifie":
            modifiees += 1
        else:
            connues += 1

        mtime = os.stat(chemin).st_mtime_ns
        for ch in chapitres_bruts:
            texte = ch.get("texte", "") or ""
            longueur = len(re.sub(r"\s", "", texte))
            nomme = str(ch.get("num", "")).startswith(
                ("prologue", "épilogue", "epilogue", "interlude", "bonus",
                 "extra", "avant-propos", "après-propos", "préface")
            )
            seuil = MIN_CARACTERES_CHAPITRE_NOMME if nomme else MIN_CARACTERES_CHAPITRE
            if longueur < seuil:
                continue
            tous.append(ChapitreEpub(
                numero=ch.get("num", ""),
                numero_affichage=ch.get("affiche", ch.get("num", "")),
                titre=ch.get("titre", ""),
                texte=texte,
                source=rel,
                statut=statut,
                ordre=ch.get("ordre", 0),
                fichier_ordre=ch.get("fichier_ordre", idx - 1),
            ))
            # mtime conservé pour départager les doublons inter-fichiers.
            tous[-1]._mtime_ns = mtime  # type: ignore[attr-defined]

    etat["sources"] = sources
    etat["dossier"] = dossier
    etat["dernier_scan"] = datetime.datetime.now().isoformat(timespec="seconds")
    _sauver_etat(dossier, etat)

    # Déduplique les chapitres présents dans plusieurs fichiers (versions
    # Google/Argos d'une même partie, chevauchements...). On privilégie le
    # corps le plus complet, puis le fichier le plus récent.
    meilleurs: dict[str, ChapitreEpub] = {}
    for ch in tous:
        cle = _cle_chapitre(ch.numero, ch.titre)
        ancien = meilleurs.get(cle)
        if ancien is None or (
            ch.longueur, getattr(ch, "_mtime_ns", 0)
        ) > (
            ancien.longueur, getattr(ancien, "_mtime_ns", 0)
        ):
            meilleurs[cle] = ch

    chapitres = list(meilleurs.values())
    chapitres.sort(key=lambda c: (c.fichier_ordre, c.ordre))

    epub_existant = etat.get("epub")
    if not epub_existant:
        defaut = _chemin_sortie_defaut(dossier)
        epub_existant = defaut if os.path.exists(defaut) else None

    analyse = AnalyseEpub(
        dossier=dossier,
        pdfs=pdfs,
        chapitres=chapitres,
        sources_nouvelles=nouvelles,
        sources_modifiees=modifiees,
        sources_connues=connues,
        epub_existant=epub_existant,
    )
    log(
        f"Analyse terminée : {len(chapitres)} chapitre(s) retenu(s) "
        f"({nouvelles} PDF nouveau(x), {modifiees} modifié(s))."
    )
    return analyse


# ─────────────────────────────────────────────
#   CONSTRUCTION EPUB
# ─────────────────────────────────────────────

def _titre_roman(dossier: str) -> str:
    nom = os.path.basename(os.path.normpath(dossier))
    nom = re.sub(r"\{[^}]*\}|\[[^\]]*\]", " ", nom)
    nom = re.sub(r"(?i)[_ ]c\d+[_\-]\d+.*$", " ", nom)
    nom = re.sub(r"(?i)[_ ]part(?:ie)?[_\-\s]*\d+.*$", " ", nom)
    nom = re.sub(r"@\w+", " ", nom)
    nom = nom.replace("_", " ").replace("-", " ")
    nom = re.sub(r"\s+", " ", nom).strip(" –—")
    if nom and nom == nom.lower():
        nom = nom.title()
    return nom or os.path.basename(os.path.normpath(dossier))


def _slug(texte: str) -> str:
    texte = re.sub(r"[^\w\- ]+", "", texte, flags=re.UNICODE)
    texte = re.sub(r"\s+", "-", texte.strip())
    return texte[:80].strip("-") or "roman"


def _chemin_sortie_defaut(dossier: str) -> str:
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dossier_epubs = os.path.join(racine, "epubs")
    return os.path.join(dossier_epubs, f"{_slug(_titre_roman(dossier))}.epub")


def _echapper(texte: str) -> str:
    from xml.sax.saxutils import escape
    return escape(texte)


def _epub_disponible() -> Optional[str]:
    if not HAS_EPUBLIB:
        return "ebooklib n'est pas installé (pip install ebooklib)"
    return None


def generer_epub(
    analyse: AnalyseEpub,
    chemin_sortie: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Écrit (ou met à jour) l'EPUB à partir d'une analyse."""
    log = on_log or (lambda _m: None)
    erreur = _epub_disponible()
    if erreur:
        raise ImportError(erreur)
    assert epub is not None  # garanti par _epub_disponible()
    if not analyse.chapitres:
        raise ValueError(
            "Aucun chapitre traduit détecté. Vérifiez que le dossier contient "
            "des PDF traduits avec des entêtes de chapitres."
        )

    dossier = analyse.dossier
    sortie = chemin_sortie or _chemin_sortie_defaut(dossier)
    sortie = os.path.abspath(sortie)
    os.makedirs(os.path.dirname(sortie), exist_ok=True)

    titre = _titre_roman(dossier)
    livre = epub.EpubBook()
    livre.set_identifier(
        "traducteur-pdf-" + hashlib.sha1(dossier.encode("utf-8")).hexdigest()[:12]
    )
    livre.set_title(titre)
    livre.set_language("fr")
    livre.add_author("Traduction automatique")
    livre.add_metadata("DC", "date", datetime.date.today().isoformat())
    livre.add_metadata("DC", "description",
                       "Traduction automatique assemblée depuis des PDF.")

    css = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=(
            "html,body{margin:0;padding:0;}"
            "body{font-family:Georgia,'DejaVu Serif',serif;line-height:1.45;"
            "padding:0 .6em;color:#1c1c1c;}"
            "h1{font-size:1.35em;line-height:1.2;margin:0 0 .9em;"
            "text-align:left;page-break-after:avoid;}"
            "p{margin:0;text-indent:1.25em;text-align:justify;"
            "hyphens:auto;-webkit-hyphens:auto;-epub-hyphens:auto;"
            "orphans:2;widows:2;}"
            "h1+p,p:first-of-type{text-indent:0;}"
            "p:empty{display:none;}"
        ),
    )
    livre.add_item(css)

    page_titre = epub.EpubHtml(title="Page de titre", file_name="titre.xhtml",
                               lang="fr")
    page_titre.content = (
        f"<h1>{_echapper(titre)}</h1>"
        f"<p>Traduction automatique — {len(analyse.chapitres)} chapitre(s).</p>"
        f"<p>Généré le {datetime.date.today().strftime('%d/%m/%Y')}.</p>"
    )
    page_titre.add_item(css)
    livre.add_item(page_titre)

    sommaire = []
    items_chapitres = []
    for index, chapitre in enumerate(analyse.chapitres, 1):
        label = chapitre.label
        item = epub.EpubHtml(
            title=label,
            file_name=f"chap_{index:05d}.xhtml",
            lang="fr",
        )
        # Marges nulles en style inline : certains lecteurs EPUB imposent
        # sinon un grand blanc entre les paragraphes d'un même chapitre.
        paragraphes = []
        for position, bloc in enumerate(re.split(r"\n{2,}", chapitre.texte)):
            bloc = bloc.strip()
            if not bloc:
                continue
            retrait = "0" if not paragraphes else "1.25em"
            paragraphes.append(
                f'<p style="margin:0;text-indent:{retrait};">'
                f"{_echapper(bloc)}</p>"
            )
        item.content = (
            f'<h1 style="margin:0 0 .9em;">{_echapper(label)}</h1>\n'
            + "\n".join(paragraphes)
        )
        item.add_item(css)
        livre.add_item(item)
        items_chapitres.append(item)
        sommaire.append(
            epub.Link(item.file_name, label, f"chap_{index:05d}")
        )

    livre.toc = list(sommaire)
    livre.add_item(epub.EpubNcx())
    livre.add_item(epub.EpubNav())
    livre.spine = ["nav", page_titre] + items_chapitres

    # Réécriture atomique : un échec ne casse pas l'EPUB précédent.
    tmp = sortie + ".tmp"
    try:
        epub.write_epub(tmp, livre)
        os.replace(tmp, sortie)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    analyse.chemin_epub = sortie
    etat = _charger_etat(dossier)
    etat["epub"] = sortie
    etat["epub_mtime"] = os.path.getmtime(sortie)
    etat["chapitres_epub"] = len(analyse.chapitres)
    _sauver_etat(dossier, etat)

    log(
        f"EPUB généré : {sortie} "
        f"({len(analyse.chapitres)} chapitres, "
        f"{os.path.getsize(sortie) // 1024} Ko)"
    )
    return sortie


def analyser_et_generer(
    dossier: str,
    chemin_sortie: Optional[str] = None,
    force: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
) -> tuple[str, AnalyseEpub]:
    """Raccourci : scanne puis génère l'EPUB. Retourne (chemin, analyse)."""
    analyse = analyser_dossier(dossier, force=force, on_log=on_log)
    chemin = generer_epub(analyse, chemin_sortie=chemin_sortie, on_log=on_log)
    return chemin, analyse
