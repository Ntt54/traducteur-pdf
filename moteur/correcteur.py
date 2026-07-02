#!/usr/bin/env python3
"""
Correction orthographique via LanguageTool (optionnelle).
"""

from __future__ import annotations

from typing import Optional

from . import config as cfg

_HAS_LANGTOOL: bool = False
try:
    import language_tool_python
    _HAS_LANGTOOL = True
except ImportError:
    pass


def init_ortho(langue: str = "fr") -> bool:
    """Initialise LanguageTool pour une langue donnée."""
    if not _HAS_LANGTOOL:
        return False
    with cfg.ortho_lock:
        if cfg.ortho_tool is None:
            try:
                cfg.ortho_tool = language_tool_python.LanguageTool(langue)
            except Exception:
                return False
    return True


def corriger_texte(texte: str) -> str:
    """Corrige l'orthographe d'un texte si la fonctionnalité est activée."""
    conf = cfg.get_config()
    if not conf.correction_ortho or not _HAS_LANGTOOL:
        return texte
    try:
        if cfg.ortho_tool is None:
            init_ortho(conf.langue_ortho)
        if cfg.ortho_tool:
            matches = cfg.ortho_tool.check(texte)
            return language_tool_python.utils.correct(texte, matches)
    except Exception:
        pass
    return texte
