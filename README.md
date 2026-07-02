# 🌍 Traducteur PDF v8

Application Linux (interface graphique) pour traduire en masse des PDF,
avec **12 fonctionnalités avancées** intégrées.

## ✨ Fonctionnalités

| # | Fonctionnalité | Statut |
|---|---------------|--------|
| 1 | **Sélection intelligente des PDF** — cases à cocher, tout sélectionner/désélectionner | ✅ |
| 2 | **Prévisualisation avant/après** — texte original et traduction côte à côte, édition | ✅ |
| 3 | *Moteurs multiples* (prévu) | 🔄 |
| 4 | **Tableau de bord & statistiques** — historique, métriques, activité hebdomadaire | ✅ |
| 5 | **Mise en page PDF configurable** — police, taille, marges, couleurs | ✅ |
| 6 | **Recherche & filtre dans les logs** — barre de recherche en temps réel | ✅ |
| 7 | **Gestion de projets** — sauvegarder/charger la configuration complète | ✅ |
| 8 | **Correction orthographique** — via LanguageTool (optionnel) | ✅ |
| 9 | **Export multi-format** — PDF, TXT, Markdown, DOCX | ✅ |
| 10 | **Proxy rotation** — liste de proxies pour éviter les blocages | ✅ |
| 11 | **6 thèmes** — Catppuccin, Dracula, Nord, Gruvbox, etc. | ✅ |
| 12 | **Fusion de PDF** — assembler tous les fichiers en un seul | ✅ |

## 📦 Installation

```bash
pip install -r requirements.txt --break-system-packages

# Pour la correction orthographique (optionnel) :
pip install language-tool-python --break-system-packages

# Pour l'export DOCX (optionnel) :
pip install python-docx --break-system-packages

# tkinter si absent (Fedora / Nobara) :
sudo dnf install python3-tkinter
```

## ▶️ Utilisation

```bash
python3 app_gui.py
```

### Interface à onglets

- **Traduction** — paramètres + sélection des fichiers + lancement
- **Aperçu** — visualisation originale ↔ traduite
- **Tableau de bord** — statistiques globales
- **Historique** — sessions précédentes
- **Configuration** — styles PDF, proxies, orthographe, fusion

### Sauvegarde automatique

La configuration est automatiquement sauvegardée dans `projet_sauvegarde.json`
à la fermeture et chargée au démarrage.

### Vérification qualité

```bash
python3 verifier_traductions.py
python3 verifier_traductions.py --purge        # supprime les PDF défaillants
python3 verifier_traductions.py --html          # génère un rapport HTML
```

### Ligne de commande (moteur seul)

```bash
python3 traduire_pdfs_v2.py
```

## 🏗️ Structure

| Fichier | Rôle |
|---------|------|
| `app_gui.py` | Interface graphique complète (5 onglets) |
| `traduire_pdfs_v2.py` | Moteur v8 (proxy, multi-format, merge, spell, styles) |
| `verifier_traductions.py` | Contrôle qualité v2 (rapport HTML) |
| `stats_manager.py` | Historique et métriques (SQLite) |
| `themes.py` | 6 thèmes de couleur |
| `extraction_cache/` | Cache du texte extrait |
| `translation_cache.db` | Cache des traductions |
| `stats_history.db` | Base de données des statistiques |
| `checkpoints/` | Reprise en cas d'interruption |

## 🔧 Options avancées

### Proxies

Ajoutez une liste de proxies dans l'onglet Configuration (un par ligne) :
```
http://proxy1:port
http://user:pass@proxy2:port
```

### Styles PDF

Personnalisez la police, la taille, les marges et les couleurs
du PDF généré dans l'onglet Configuration.

### Thèmes

Choisissez parmi 6 thèmes : Catppuccin Mocha, Catppuccin Latte,
Dracula, Nord, Gruvbox Dark, Gruvbox Light.
