#!/usr/bin/env python3
"""
Tests de la construction EPUB à partir des PDF traduits.

Couvre :
- la reconnaissance des différentes formes d'entêtes de chapitres ;
- le nettoyage des titres (doublons, numéros répétés, titres sur plusieurs lignes) ;
- l'ignorance des pages de sommaire ;
- le cache incrémental (ne ré-extrait que les nouveaux PDF) ;
- la génération réelle d'un EPUB lisible avec table des matières.
"""

from __future__ import annotations

import os

import pytest

from moteur import export_epub as ex


# ─────────────────────────────────────────────
#   RECONNAISSANCE DES ENTÊTES
# ─────────────────────────────────────────────

def _chapitres(texte: str) -> list[dict]:
    return ex._parse_lignes(texte)


def test_variantes_entetes_et_titres():
    texte = """\
Chapitre 74 — : Homicide Maniaque
Corps du chapitre soixante-quatorze. Il fait assez long pour être conservé.
Chapitre 141 — - Démon de la prophétie (1)
Corps du chapitre cent quarante et un.
Chapitre 318 – Fuir à nouveau vers le sud
Chapitre 318 — Fuir à nouveau vers le sud
Corps du chapitre trois cent dix-huit.
Chapitre 448 : Une introduction douce
Chapitre 448 : Chapitre 448 Une introduction douce
Corps du chapitre quatre cent quarante-huit.
Chapitre 244-151 : Hope
Corps du chapitre deux cent quarante-quatre.
Prologue
Un prologue suffisamment long pour ne pas être considéré comme du sommaire.
"""
    chapitres = _chapitres(texte)
    par_num = {c["num"]: c for c in chapitres}

    assert par_num["74"]["titre"] == "Homicide Maniaque"
    assert par_num["141"]["titre"] == "Démon de la prophétie (1)"
    assert par_num["318"]["titre"] == "Fuir à nouveau vers le sud"
    assert par_num["448"]["titre"] == "Une introduction douce"
    assert par_num["244.151"]["affiche"] == "244-151"
    assert par_num["244.151"]["titre"] == "Hope"
    assert par_num["prologue"]["titre"] == ""


def test_titre_repete_et_numero_sur_ligne_suivante():
    texte = """\
Chapitre 362
Chapitre 362 — : 362
Chapitre 362 — : Il semble que je ne puisse pas tuer trop
vite
L’herbe électrique et l’épée du Dieu du Tonnerre étaient déjà entre ses mains.
La suite du corps, assez longue pour être un vrai paragraphe de roman.
"""
    chapitres = _chapitres(texte)
    assert len(chapitres) == 1
    ch = chapitres[0]
    assert ch["num"] == "362"
    assert ch["titre"] == "Il semble que je ne puisse pas tuer trop vite"
    assert "L’herbe électrique" in ch["texte"]
    assert "vite" not in ch["texte"].split("\n")[0]


def test_entete_collee_au_texte_en_majuscules():
    texte = """\
CHAPITRE 1 DES
TRAJETS ENNUYANTS Je laisse échapper un petit bâillement, ma joue appuyée.
La suite du chapitre, assez longue pour être conservée dans le résultat final.
CHAPITRE 9 NOUS DEVONS LES
DISSECTER Je décide d'ignorer les points de statistiques pour l'instant.
Encore du corps de texte pour ce chapitre neuf.
"""
    chapitres = _chapitres(texte)
    assert [c["num"] for c in chapitres] == ["1", "9"]
    assert chapitres[0]["titre"] == "Des Trajets Ennuyants"
    assert chapitres[1]["titre"] == "Nous Devons Les Dissecter"
    assert chapitres[0]["texte"].startswith("Je laisse")
    assert chapitres[1]["texte"].startswith("Je décide")


def test_sous_chapitre_et_episode():
    texte = """\
Chapitre 150 — .1 - ÉPISODE 150.1 – VOLEUR FANTÔME (2)
Le corps de ce sous-chapitre.
Chapitre 151 : ÉPISODE 151 – VOLEUR FANTÔME (3)
Le corps du chapitre suivant.
"""
    chapitres = _chapitres(texte)
    assert chapitres[0]["num"] == "150.1"
    assert chapitres[0]["titre"] == "Épisode 150.1 – Voleur Fantôme (2)"
    assert chapitres[1]["num"] == "151"


def test_page_sommaire_ignoree():
    sommaire = [
        "Chapitre 1 — Le début",
        "Chapitre 2 — La suite",
        "Chapitre 3 — Encore",
        "Chapitre 4 — Toujours",
    ]
    corps = [
        "Un long paragraphe de texte normal qui raconte l'histoire.",
        "Une deuxième ligne de texte tout aussi normale que la première.",
    ]
    assert ex._page_est_sommaire(sommaire) is True
    assert ex._page_est_sommaire(corps) is False


def test_bonus_statistique_nest_pas_un_chapitre():
    texte = """\
Il observa la récompense qui venait de s'afficher.
Bonus : gagnée en tuant un ennemi au-dessus de votre niveau*
La suite du texte revient à l'histoire et continue normalement.
"""
    assert _chapitres(texte) == []


def test_entetes_google_translate_supprimees():
    texte = """\
Machine translated by Google
Chapitre 1 : Le début
Traduit automatiquement par Google Ce paragraphe continue normalement.
Une deuxième ligne de texte qui doit rester intacte.
https://translate.google.com
"""
    nettoye = ex._nettoyer_page(texte)
    assert "Google" not in nettoye
    assert "Chapitre 1 : Le début" in nettoye
    assert "Ce paragraphe continue normalement." in nettoye
    assert "deuxième ligne" in nettoye


def test_sommaire_numerote_reconnu():
    sommaire = " ".join(
        f"{i}. Un titre de chapitre assez long pour ressembler à un sommaire"
        for i in range(1, 12)
    )
    assert ex._texte_est_sommaire(sommaire) is True
    assert ex._texte_est_sommaire(
        "Le héros marche longtemps. Il rencontre un monstre. 12. Il fuit."
    ) is False


def test_bonus_de_titres_differents_conserves():
    texte = """\
Bonus : Noël
Un premier bonus assez long pour être conservé dans le résultat final.
Bonus : Halloween
Un second bonus, lui aussi suffisamment long pour ne pas être écarté.
Bonus : Noël
Une version courte du même bonus qui doit être ignorée comme doublon.
"""
    bruts = _chapitres(texte)
    assert len(bruts) == 3
    assert ex._cle_chapitre("bonus", "Noël") != ex._cle_chapitre("bonus", "Halloween")
    assert ex._cle_chapitre("bonus", "Noël") == ex._cle_chapitre("bonus", " noël ")


def test_ligne_de_texte_ordinaire_nest_pas_un_entete():
    texte = """\
Il expliqua que le chapitre 12 de son livre parlait de la pluie.
Le chapitre 12 explique aussi pourquoi cette phrase ne doit pas créer de titre.
Cette phrase ne doit jamais créer un faux chapitre dans la table des matières.
"""
    assert _chapitres(texte) == []


# ─────────────────────────────────────────────
#   TITRE DU ROMAN
# ─────────────────────────────────────────────

def test_titre_roman_et_slug(tmp_path):
    dossier = tmp_path / "the-god-eater"
    dossier.mkdir()
    assert ex._titre_roman(str(dossier)) == "The God Eater"
    assert ex._slug("The God Eater") == "The-God-Eater"


# ─────────────────────────────────────────────
#   EXTRACTION RÉELLE D'UN PDF SIMPLE
# ─────────────────────────────────────────────

def test_extraction_pdf_reel(tmp_path):
    from reportlab.pdfgen import canvas

    chemin = tmp_path / "roman_part1_traduit_fr.pdf"
    c = canvas.Canvas(str(chemin))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(72, 800, "Chapitre 1 : Le jour du commencement")
    c.setFont("Helvetica", 11)
    y = 770
    for i in range(20):
        c.drawString(72, y, f"Ligne de texte numero {i} avec assez de contenu pour le test.")
        y -= 16
    c.showPage()
    c.save()

    chapitres = ex._extraire_chapitres_pdf(str(chemin), fichier_ordre=0)
    assert len(chapitres) == 1
    assert chapitres[0]["num"] == "1"
    assert chapitres[0]["titre"] == "Le jour du commencement"
    assert len(chapitres[0]["texte"]) > 250


# ─────────────────────────────────────────────
#   CACHE INCRÉMENTAL + EPUB
# ─────────────────────────────────────────────

def _faux_chapitres(chemin_pdf: str, fichier_ordre: int = 0) -> list[dict]:
    """Remplace l'extraction PDF pendant les tests incrémentaux."""
    nom = os.path.basename(chemin_pdf)
    numero = 1 if "part1" in nom else 2
    return [{
        "num": str(numero),
        "affiche": str(numero),
        "titre": "Premier" if numero == 1 else "Deuxième",
        "source": chemin_pdf,
        "fichier_ordre": fichier_ordre,
        "ordre": 0,
        "texte": ("Phrase de remplissage. " * 30).strip(),
    }]


def test_cache_incremental_et_mise_a_jour_epub(tmp_path, monkeypatch):
    dossier = tmp_path / "roman"
    dossier.mkdir()
    (dossier / "roman_part1_traduit_fr.pdf").write_bytes(b"pdf1")
    (dossier / "roman_part2_traduit_fr.pdf").write_bytes(b"pdf2")

    appels: list[str] = []

    def extraction(chemin, fichier_ordre=0):
        appels.append(os.path.basename(chemin))
        return _faux_chapitres(chemin, fichier_ordre)

    monkeypatch.setattr(ex, "_extraire_chapitres_pdf", extraction)

    analyse = ex.analyser_dossier(str(dossier))
    assert analyse.sources_nouvelles == 2
    assert len(analyse.chapitres) == 2
    assert sorted(appels) == ["roman_part1_traduit_fr.pdf", "roman_part2_traduit_fr.pdf"]

    # Deuxième scan : rien n'a changé → aucun nouvel appel d'extraction.
    appels.clear()
    analyse2 = ex.analyser_dossier(str(dossier))
    assert appels == []
    assert analyse2.sources_connues == 2
    assert analyse2.sources_nouvelles == 0

    # Génération de l'EPUB.
    sortie = tmp_path / "roman.epub"
    chemin = ex.generer_epub(analyse2, chemin_sortie=str(sortie))
    assert os.path.exists(chemin)

    # Ajout d'un PDF : seul ce fichier est ré-extrait.
    (dossier / "roman_part3_traduit_fr.pdf").write_bytes(b"pdf3")
    appels.clear()

    def extraction3(chemin, fichier_ordre=0):
        appels.append(os.path.basename(chemin))
        return [{
            "num": "3", "affiche": "3", "titre": "Troisième",
            "source": chemin, "fichier_ordre": fichier_ordre, "ordre": 0,
            "texte": ("Suite du texte. " * 40).strip(),
        }]

    monkeypatch.setattr(ex, "_extraire_chapitres_pdf", extraction3)
    analyse3 = ex.analyser_dossier(str(dossier))
    assert appels == ["roman_part3_traduit_fr.pdf"]
    assert analyse3.sources_nouvelles == 1
    assert analyse3.sources_connues == 2
    assert len(analyse3.chapitres) == 3
    assert analyse3.epub_existant == str(sortie.resolve())

    chemin3 = ex.generer_epub(analyse3, chemin_sortie=str(sortie))
    assert os.path.exists(chemin3)

    # Vérifie la table des matières et les chapitres de l'EPUB produit.
    from ebooklib import epub
    livre = epub.read_epub(chemin3)
    assert len(livre.toc) == 3
    assert len([i for i in livre.get_items() if i.get_type() == 9]) == 5  # page titre + 3 chapitres + nav


def test_generation_refuse_dossier_vide(tmp_path):
    analyse = ex.AnalyseEpub(dossier=str(tmp_path), chapitres=[])
    with pytest.raises(ValueError):
        ex.generer_epub(analyse, chemin_sortie=str(tmp_path / "vide.epub"))


def test_entete_google_espaces_insecables():
    """Les PDF Google/PDFium utilisent des espaces insécables."""
    chapitres = _chapitres(
        "Chapitre\u00a01\u00a0:\u00a0\u00a0S'abandonner au vice\n"
        "Corps du chapitre un, assez long pour être conservé.\n"
        "Chapitre\u00a02\u00a0:\u00a0\u00a0La fourmilière\n"
        "Corps du chapitre deux, assez long pour être conservé.\n"
    )
    assert [c["num"] for c in chapitres] == ["1", "2"]
    assert chapitres[0]["titre"] == "S'abandonner au vice"
    assert chapitres[1]["titre"] == "La fourmilière"


def test_entete_titre_avant_numero():
    entete = ex._detecter_entete("Défi officiel du chapitre 525")
    assert entete is not None
    assert entete["num"] == "525"
    assert entete["titre"] == "Défi Officiel"


def test_entete_dupliquee_avec_corps_colle():
    texte = """\
Chapitre 497 : Un peu froid
Chapitre 497 Un peu froid Zhou Wen savait qu'il n'était plus qu'un chat.
Il était complètement dépassé par la situation.
"""
    chapitres = _chapitres(texte)
    assert len(chapitres) == 1
    assert chapitres[0]["titre"] == "Un peu froid"
    assert chapitres[0]["texte"].startswith("Zhou Wen savait")
    assert "Chapitre 497" not in chapitres[0]["texte"]


def test_entete_dupliquee_variante_et_corps_sans_ponctuation():
    texte = """\
Chapitre 586 : Deux façons d’accéder au stade mythique
Chapitre 586 Deux voies pour atteindre le stade mythique « Excusez-moi de vous déranger », dit Jiang Yan.
La suite du corps.
"""
    chapitres = _chapitres(texte)
    assert len(chapitres) == 1
    assert chapitres[0]["titre"] == "Deux façons d’accéder au stade mythique"
    assert chapitres[0]["texte"].startswith("« Excusez-moi")


def test_ordre_visuel_des_pages_pdf(tmp_path):
    """Un texte dessiné dans le désordre doit être relu de haut en bas."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    chemin = tmp_path / "ordre.pdf"
    c = canvas.Canvas(str(chemin), pagesize=A4)
    c.drawString(72, 200, "DEUXIEME LIGNE")
    c.drawString(72, 700, "PREMIERE LIGNE")
    c.showPage()
    c.save()

    pages = ex._extraire_pages_pdf(str(chemin))
    texte = "\n".join(pages)
    assert texte.index("PREMIERE LIGNE") < texte.index("DEUXIEME LIGNE")
