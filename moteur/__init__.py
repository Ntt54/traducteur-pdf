"""
Moteur de traduction PDF — modules spécialisés.

Point d'entrée unique : tout le nécessaire est accessible via ce package.
Pour la rétrocompatibilité, voir traduire_pdfs_v2.py.

Modules :
  config      – ConfigMoteur (dataclass), état global, configurer()
  utils       – Journalisation, tri naturel, polices, checkpoints
  extracteur  – Extraction et nettoyage de texte depuis des PDF
  traducteur  – Traduction Google, cache SQLite, proxy, workers
  exportateur – Export PDF/TXT/MD/DOCX + fusion
  correcteur  – Correction orthographique LanguageTool (optionnel)
"""

from . import config as config
from . import utils as utils
from . import extracteur as extracteur
from . import traducteur as traducteur
from . import exportateur as exportateur
from . import correcteur as correcteur
from . import editeur as editeur
from . import profils as profils
