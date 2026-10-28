#!/usr/bin/env python3
"""Conversion EPUB → PDF (script reportlab ou Calibre)."""

from __future__ import annotations

import json
import math
import os
import subprocess
from typing import Callable, Optional

from .extracteur_epub import (
    diviser_en_parties,
    extraire_texte_epub,
    MOTS_PAR_PARTIE,
    MOTS_PAR_PAGE,
)

# Limite de Google Traduction pour un document : 300 pages.
# On garde une marge d'une page pour rester strictement sous la limite.
PAGES_PAR_PARTIE = 299


def convertir_epub(
    chemin_epub: str,
    dossier_sortie: str,
    methode: str = "script",
    mode_split: bool = True,
    mots_par_partie: int = MOTS_PAR_PARTIE,
    on_log: Optional[Callable[[str], None]] = None,
    pages_par_partie: int = PAGES_PAR_PARTIE,
) -> list[str]:
    """Convertit un EPUB en PDF(s). Retourne les chemins des PDFs générés.

    En mode découpé, la cible est exprimée en pages PDF (``pages_par_partie``)
    et non plus en mots : on construit le PDF complet une fois, puis on le
    découpe en un nombre minimal de fichiers de taille équilibrée, tous
    strictement inférieurs à la limite Google Traduction (300 pages).

    ``mots_par_partie`` reste accepté pour compatibilité : il n'est utilisé
    que si ``pages_par_partie`` vaut 0.
    """
    log = on_log or (lambda _: None)
    nom_base = os.path.splitext(os.path.basename(chemin_epub))[0]

    if methode == "calibre" and not mode_split:
        return _calibre_unique(chemin_epub, dossier_sortie, nom_base, log)

    chapitres = extraire_texte_epub(chemin_epub)
    if not chapitres:
        log(f"⚠️ Aucun texte dans {nom_base}")
        return []

    if not mode_split:
        dest = os.path.join(dossier_sortie, f"{nom_base}.pdf")
        pdf = _script_pdf(chapitres, dest, nom_base, log)
        return [pdf] if pdf else []

    os.makedirs(dossier_sortie, exist_ok=True)

    # Ancien découpage par mots, conservé uniquement si demandé explicitement.
    if not pages_par_partie:
        parties = diviser_en_parties(chapitres, mots_par_partie)
        total_mots = sum(len(c.split()) for c in chapitres)
        log(
            f"📖 {nom_base} : ~{total_mots // MOTS_PAR_PAGE} pages → "
            f"{len(parties)} partie(s)"
        )
        generes = []
        if methode == "calibre":
            generes = _calibre_split_words(
                chemin_epub, dossier_sortie, nom_base, parties, log
            )
        else:
            for idx, partie in enumerate(parties, 1):
                dest = os.path.join(dossier_sortie, f"{nom_base}_part{idx}.pdf")
                pdf = _script_pdf(partie, dest, f"{nom_base}_part{idx}", log)
                if pdf:
                    generes.append(pdf)
        log(f"✅ {len(generes)}/{len(parties)} PDF généré(s)")
        return generes

    max_pages = max(1, min(int(pages_par_partie), PAGES_PAR_PARTIE))
    log(f"📚 {nom_base} : découpage en PDF de {max_pages} pages maximum")

    if methode == "calibre":
        return _calibre_split_pages(
            chemin_epub, dossier_sortie, nom_base, max_pages, log
        )
    return _script_split_pages(
        chapitres, dossier_sortie, nom_base, max_pages, log
    )


def _chemins_parts(dossier: str, nom_base: str) -> list[str]:
    """Liste les anciens PDF découpés, sans dépendre des caractères glob."""
    try:
        noms = os.listdir(dossier)
    except OSError:
        return []
    prefixe = f"{nom_base}_part"
    return [
        os.path.join(dossier, n)
        for n in noms
        if n.startswith(prefixe) and n.lower().endswith(".pdf")
    ]


def _chemin_marqueur(dossier: str) -> str:
    return os.path.join(dossier, ".conversion.json")


def _supprimer_marqueur(dossier: str) -> None:
    try:
        os.remove(_chemin_marqueur(dossier))
    except OSError:
        pass


def _ecrire_marqueur(
    dossier: str, nom_base: str, total_pages: int,
    max_pages: int, nombre_parts: int,
) -> None:
    """Mémorise le découpage pour que le scanner n'ait pas à relire les PDF."""
    donnees = {
        "version": 1,
        "nom_base": nom_base,
        "pages_total": total_pages,
        "pages_max": max_pages,
        "parts": nombre_parts,
    }
    chemin = _chemin_marqueur(dossier)
    tmp = chemin + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=1)
        os.replace(tmp, chemin)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _supprimer_pdf_complet(dossier: str, nom_base: str) -> None:
    """Supprime les PDF complets temporaires d'anciennes conversions."""
    for nom in (f"_{nom_base}_complet.pdf", f"._{nom_base}_complet.pdf"):
        try:
            os.remove(os.path.join(dossier, nom))
        except OSError:
            pass


def _supprimer_anciennes_parts(dossier: str, nom_base: str, log: Callable) -> None:
    for chemin in _chemins_parts(dossier, nom_base):
        try:
            os.remove(chemin)
            log(f"🗑️ Ancienne partie supprimée : {os.path.basename(chemin)}")
        except OSError as exc:
            log(f"⚠️ Impossible de supprimer {os.path.basename(chemin)} : {exc}")


def _repartition_pages(total: int, max_pages: int) -> list[int]:
    """Répartit ``total`` pages en un nombre minimal de blocs ≤ ``max_pages``."""
    if total <= 0:
        return []
    nombre = math.ceil(total / max_pages)
    base, reste = divmod(total, nombre)
    return [base + (1 if i < reste else 0) for i in range(nombre)]


def _split_pdf_pages(
    pdf_complet: str,
    dossier_sortie: str,
    nom_base: str,
    max_pages: int,
    log: Callable,
) -> list[str]:
    """Découpe un PDF complet en parties équilibrées de ≤ ``max_pages`` pages."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        log("❌ pypdf non installé — découpage impossible")
        return []

    try:
        reader = PdfReader(pdf_complet)
        total_pages = len(reader.pages)
    except Exception as exc:
        log(f"❌ Lecture du PDF complet impossible : {exc}")
        return []

    if total_pages == 0:
        log("❌ PDF complet vide")
        return []

    tailles = _repartition_pages(total_pages, max_pages)
    _supprimer_anciennes_parts(dossier_sortie, nom_base, log)
    _supprimer_marqueur(dossier_sortie)

    generes: list[str] = []
    debut = 0
    for idx, taille in enumerate(tailles, 1):
        dest = os.path.join(dossier_sortie, f"{nom_base}_part{idx}.pdf")
        fin = debut + taille
        writer = PdfWriter()
        for page in range(debut, fin):
            writer.add_page(reader.pages[page])
        tmp = dest + ".tmp"
        try:
            with open(tmp, "wb") as f:
                writer.write(f)
            os.replace(tmp, dest)
        except Exception as exc:
            log(f"❌ Écriture de {os.path.basename(dest)} impossible : {exc}")
            try:
                os.remove(tmp)
            except OSError:
                pass
            debut = fin
            continue
        log(
            f"📄 {os.path.basename(dest)} "
            f"(pages {debut + 1}-{fin} / {total_pages})"
        )
        generes.append(dest)
        debut = fin

    if len(generes) == len(tailles):
        _ecrire_marqueur(
            dossier_sortie, nom_base, total_pages, max_pages, len(generes)
        )
    log(
        f"✅ {len(generes)} PDF généré(s) — {total_pages} pages au total, "
        f"{max_pages} pages maximum par fichier"
    )
    return generes


def _script_split_pages(
    chapitres: list[str],
    dossier_sortie: str,
    nom_base: str,
    max_pages: int,
    log: Callable,
) -> list[str]:
    """Construit le PDF complet avec reportlab, puis le découpe par pages."""
    os.makedirs(dossier_sortie, exist_ok=True)
    pdf_complet = os.path.join(dossier_sortie, f"._{nom_base}_complet.pdf")
    _supprimer_pdf_complet(dossier_sortie, nom_base)
    try:
        _script_pdf(
            chapitres, pdf_complet, nom_base,
            lambda m: log(m) if str(m).startswith("❌") else None,
        )
        if not os.path.exists(pdf_complet):
            return []
        return _split_pdf_pages(
            pdf_complet, dossier_sortie, nom_base, max_pages, log
        )
    finally:
        # Ne jamais laisser le PDF complet dans pdfs_originaux : il serait
        # ramassé par le moteur de traduction et traduit une seconde fois.
        try:
            if os.path.exists(pdf_complet):
                os.remove(pdf_complet)
        except OSError:
            pass


def _script_pdf(
    chapitres: list[str],
    dest: str,
    label: str,
    log: Callable,
) -> Optional[str]:
    """Génère un PDF depuis une liste de textes de chapitres (reportlab)."""
    try:
        from xml.sax.saxutils import escape as xml_escape
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except ImportError:
        log("❌ reportlab non installé")
        return None

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    doc = SimpleDocTemplate(
        dest, pagesize=A4,
        rightMargin=2.5 * cm, leftMargin=2.5 * cm,
        topMargin=2.0 * cm, bottomMargin=2.0 * cm,
    )
    style_n = ParagraphStyle(
        "N", fontName="Helvetica", fontSize=11, leading=16, spaceAfter=4,
    )
    style_t = ParagraphStyle(
        "T", fontName="Helvetica-Bold", fontSize=14,
        leading=20, spaceAfter=8, spaceBefore=12,
    )

    contenu = []
    for chapitre in chapitres:
        lignes = chapitre.strip().split("\n")
        for i, ligne in enumerate(lignes):
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                e = xml_escape(ligne)
                if i == 0 and len(ligne) < 100 and any(
                    t in ligne.lower()
                    for t in ["chapter", "chapitre", "prologue", "epilogue"]
                ):
                    contenu.append(Paragraph(e, style_t))
                else:
                    contenu.append(Paragraph(e, style_n))
                contenu.append(Spacer(1, 0.08 * cm))
            except Exception:
                pass
        contenu.append(Spacer(1, 0.3 * cm))

    try:
        doc.build(contenu)
        log(f"📄 {os.path.basename(dest)}")
        return dest
    except Exception as e:
        log(f"❌ {label} : {e}")
        return None


def _calibre_unique(
    chemin_epub: str,
    dossier_sortie: str,
    nom_base: str,
    log: Callable,
) -> list[str]:
    """Convertit un EPUB en un PDF unique via Calibre."""
    dest = os.path.join(dossier_sortie, f"{nom_base}.pdf")
    os.makedirs(dossier_sortie, exist_ok=True)
    log(f"🔃 Calibre : {nom_base}...")
    try:
        subprocess.run(
            ["ebook-convert", chemin_epub, dest],
            check=True, capture_output=True, text=True, timeout=600,
        )
        if os.path.exists(dest):
            log(f"📄 {os.path.basename(dest)}")
            return [dest]
    except subprocess.CalledProcessError as e:
        log(f"❌ Calibre : {e.stderr[:300]}")
    except FileNotFoundError:
        log("❌ ebook-convert introuvable")
    return []


def _calibre_split_pages(
    chemin_epub: str,
    dossier_sortie: str,
    nom_base: str,
    max_pages: int,
    log: Callable,
) -> list[str]:
    """Convertit l'EPUB complet via Calibre, puis découpe par pages."""
    os.makedirs(dossier_sortie, exist_ok=True)
    pdf_complet = os.path.join(dossier_sortie, f"._{nom_base}_complet.pdf")
    _supprimer_pdf_complet(dossier_sortie, nom_base)
    try:
        log(f"🔃 Calibre (complet) : {nom_base}...")
        try:
            subprocess.run(
                ["ebook-convert", chemin_epub, pdf_complet],
                check=True, capture_output=True, text=True, timeout=1800,
            )
        except subprocess.CalledProcessError as exc:
            log(f"❌ Calibre : {exc.stderr[:300]}")
            return []
        except FileNotFoundError:
            log("❌ ebook-convert introuvable")
            return []
        if not os.path.exists(pdf_complet):
            log("❌ Calibre n'a produit aucun PDF")
            return []
        return _split_pdf_pages(
            pdf_complet, dossier_sortie, nom_base, max_pages, log
        )
    finally:
        try:
            if os.path.exists(pdf_complet):
                os.remove(pdf_complet)
        except OSError:
            pass


def _calibre_split_words(
    chemin_epub: str,
    dossier_sortie: str,
    nom_base: str,
    parties: list[list[str]],
    log: Callable,
) -> list[str]:
    """Ancien découpage proportionnel aux mots (compatibilité)."""
    pdf_complet = os.path.join(dossier_sortie, f"_{nom_base}_complet.pdf")
    os.makedirs(dossier_sortie, exist_ok=True)

    if not os.path.exists(pdf_complet):
        log(f"🔃 Calibre (complet) : {nom_base}...")
        try:
            subprocess.run(
                ["ebook-convert", chemin_epub, pdf_complet],
                check=True, capture_output=True, text=True, timeout=600,
            )
        except subprocess.CalledProcessError as e:
            log(f"❌ Calibre : {e.stderr[:300]}")
            return []
        except FileNotFoundError:
            log("❌ ebook-convert introuvable")
            return []

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        log("❌ pypdf non installé — split Calibre impossible")
        return []

    try:
        reader = PdfReader(pdf_complet)
        total_pages = len(reader.pages)
    except Exception as e:
        log(f"❌ Lecture PDF : {e}")
        return []

    if total_pages == 0:
        return []

    mots_parts = [sum(len(c.split()) for c in p) for p in parties]
    total_mots = sum(mots_parts)
    _supprimer_anciennes_parts(dossier_sortie, nom_base, log)

    generes: list[str] = []
    for idx, mp in enumerate(mots_parts, 1):
        debut_mot = sum(mots_parts[:idx - 1])
        part_start = debut_mot * total_pages // total_mots if total_mots else 0
        part_end = (debut_mot + mp) * total_pages // total_mots if total_mots else total_pages
        part_start = min(part_start, max(0, total_pages - 1))
        part_end = max(part_end, part_start + 1)
        part_end = min(part_end, total_pages)

        dest = os.path.join(dossier_sortie, f"{nom_base}_part{idx}.pdf")
        writer = PdfWriter()
        for page in range(part_start, part_end):
            writer.add_page(reader.pages[page])
        with open(dest, "wb") as f:
            writer.write(f)
        log(f"📄 {os.path.basename(dest)} (pages {part_start + 1}-{part_end})")
        generes.append(dest)

    return generes
