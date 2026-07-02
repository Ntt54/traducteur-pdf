#!/usr/bin/env python3
"""
=============================================================
  STATS MANAGER — Tableau de bord & historique des sessions
  (Feature 4 : Dashboard & Statistics)
=============================================================
"""

import os, json, sqlite3, time, threading
from datetime import datetime

DB_PATH = "./stats_history.db"
_lock = threading.Lock()

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            duration REAL,
            fichiers INTEGER,
            pages INTEGER,
            source TEXT,
            cible TEXT,
            statut TEXT,
            format_export TEXT,
            cache_hit INTEGER,
            fallback_en INTEGER,
            pages_par_seconde REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS traductions_par_jour (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jour TEXT UNIQUE,
            nb_pages INTEGER,
            nb_fichiers INTEGER,
            duree_totale REAL
        )
    """)
    conn.commit()
    return conn

def enregistrer_session(**kwargs):
    with _lock:
        conn = _connect()
        conn.execute("""
            INSERT INTO sessions (date, duration, fichiers, pages, source, cible, statut,
                                  format_export, cache_hit, fallback_en, pages_par_seconde)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            kwargs.get("date", datetime.now().isoformat()),
            kwargs.get("duration", 0),
            kwargs.get("fichiers", 0),
            kwargs.get("pages", 0),
            kwargs.get("source", "?"),
            kwargs.get("cible", "?"),
            kwargs.get("statut", "termine"),
            kwargs.get("format_export", "pdf"),
            kwargs.get("cache_hit", 0),
            kwargs.get("fallback_en", 0),
            kwargs.get("pages_par_seconde", 0),
        ))
        jour = datetime.now().strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO traductions_par_jour (jour, nb_pages, nb_fichiers, duree_totale)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(jour) DO UPDATE SET
                nb_pages = nb_pages + ?,
                nb_fichiers = nb_fichiers + ?,
                duree_totale = duree_totale + ?
        """, (jour, kwargs.get("pages", 0), kwargs.get("fichiers", 0), kwargs.get("duration", 0),
              kwargs.get("pages", 0), kwargs.get("fichiers", 0), kwargs.get("duration", 0)))
        conn.commit()
        conn.close()

def get_historique(limite=50):
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        conn.close()
    return rows

def get_stats_globales():
    with _lock:
        conn = _connect()
        total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        total_pages = conn.execute("SELECT COALESCE(SUM(pages), 0) FROM sessions").fetchone()[0]
        total_fichiers = conn.execute("SELECT COALESCE(SUM(fichiers), 0) FROM sessions").fetchone()[0]
        total_duree = conn.execute("SELECT COALESCE(SUM(duration), 0) FROM sessions").fetchone()[0]
        dernieres = conn.execute(
            "SELECT date, pages, fichiers, duration, source, cible, statut FROM sessions ORDER BY id DESC LIMIT 5"
        ).fetchall()
        conn.close()
    return {
        "total_sessions": total_sessions,
        "total_pages": total_pages,
        "total_fichiers": total_fichiers,
        "total_duree": total_duree,
        "dernieres": dernieres,
    }

def get_stats_hebdomadaires():
    with _lock:
        conn = _connect()
        rows = conn.execute("""
            SELECT jour, nb_pages, nb_fichiers, duree_totale
            FROM traductions_par_jour
            ORDER BY jour DESC LIMIT 14
        """).fetchall()
        conn.close()
    return rows

if __name__ == "__main__":
    print(get_stats_globales())
