#!/usr/bin/env python3
"""Tests du découpage EPUB → PDF par pages (limite Google Traduction)."""

from __future__ import annotations

import json
import os

import pytest

from moteur import convertisseur_epub as conv


def test_repartition_pages_minimale_et_equilibree():
    assert conv._repartition_pages(587, 299) == [294, 293]
    assert conv._repartition_pages(117, 20) == [20, 20, 20, 19, 19, 19]
    for total, maximum in [(1, 299), (299, 299), (300, 299), (901, 300)]:
        tailles = conv._repartition_pages(total, maximum)
        assert sum(tailles) == total
        assert max(tailles) <= maximum
        assert len(tailles) == -(-total // maximum)


def _pdf_de_n_pages(chemin, nombre):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(chemin), pagesize=A4)
    for i in range(nombre):
        c.drawString(72, 800, f"Page {i + 1}")
        c.showPage()
    c.save()


def test_split_pdf_par_pages_supprime_les_anciennes_parties(tmp_path):
    from pypdf import PdfReader

    complet = tmp_path / "complet.pdf"
    _pdf_de_n_pages(complet, 7)
    (tmp_path / "roman_part99.pdf").write_bytes(b"vieux")

    parties = conv._split_pdf_pages(
        str(complet), str(tmp_path), "roman", 3, lambda m: None)

    assert [len(PdfReader(p).pages) for p in parties] == [3, 2, 2]
    assert sum(len(PdfReader(p).pages) for p in parties) == 7
    assert not (tmp_path / "roman_part99.pdf").exists()
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_conversion_epub_complete_respecte_la_limite(tmp_path):
    from ebooklib import epub
    from pypdf import PdfReader

    source = tmp_path / "roman.epub"
    livre = epub.EpubBook()
    livre.set_identifier("test-conv")
    livre.set_title("Roman test")
    livre.set_language("fr")
    chapitres = []
    for i in range(1, 7):
        item = epub.EpubHtml(title=f"Chapitre {i}", file_name=f"chap{i}.xhtml")
        item.content = (
            f"<h1>Chapitre {i}</h1>"
            + "".join(
                f"<p>Paragraphe {j} du chapitre {i}. "
                + ("Une phrase de remplissage assez longue. " * 6)
                + "</p>"
                for j in range(12)
            )
        )
        livre.add_item(item)
        chapitres.append(item)
    livre.toc = tuple(chapitres)
    livre.add_item(epub.EpubNcx())
    livre.add_item(epub.EpubNav())
    livre.spine = ["nav"] + chapitres
    epub.write_epub(str(source), livre)

    sortie = tmp_path / "sortie"
    pdfs = conv.convertir_epub(
        str(source), str(sortie), methode="script", pages_par_partie=2)

    assert len(pdfs) >= 2
    pages = [len(PdfReader(p).pages) for p in pdfs]
    assert max(pages) <= 2
    assert len(pdfs) == -(-sum(pages) // 2)
    assert not list(sortie.glob(".*_complet.pdf"))
    assert not list(sortie.glob("*.tmp"))
    marqueur = json.loads((sortie / ".conversion.json").read_text(encoding="utf-8"))
    assert marqueur["pages_total"] == sum(pages)
    assert marqueur["parts"] == len(pdfs)
    assert marqueur["pages_max"] == 2
