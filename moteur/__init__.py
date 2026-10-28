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
  extracteur_epub – Extraction et découpage de fichiers EPUB
  export_epub – Assemblage des PDF traduits en EPUB (cache incrémental)
  nllb        – Traduction hors ligne NLLB-200 (optionnel)
  post_process – Post-traitement des traductions (optionnel)
  revision    – Vérification qualité des traductions
  maintenance – Inventaire et nettoyage des caches/checkpoints
  glossaire   – Lecture/écriture du glossaire de termes
"""

from . import config as config
from . import utils as utils
from . import extracteur as extracteur
from . import traducteur as traducteur
try:
    from . import nllb as nllb
except ImportError:
    nllb = None
from . import exportateur as exportateur
from . import correcteur as correcteur
from . import editeur as editeur
from . import profils as profils
try:
    from . import post_process as post_process
except ImportError:
    post_process = None
from . import extracteur_epub as extracteur_epub
from . import revision as revision
from . import maintenance as maintenance
from . import glossaire as glossaire
