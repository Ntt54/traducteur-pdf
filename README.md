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
- **Conversion EPUB** — convertir des EPUB en PDF découpés pour Google Traduction
- **Traduit → EPUB** — assembler les PDF traduits en un EPUB avec sommaire
- **Tableau de bord** — statistiques globales
- **Historique** — sessions précédentes
- **Configuration** — styles PDF, proxies, orthographe, fusion

### EPUB → PDF pour Google Traduction

L'onglet **Conversion EPUB** découpe chaque EPUB en un minimum de PDF, tous
**strictement sous la limite gratuite de 300 pages** de Google Traduction.

1. Régler **Pages max/PDF** (299 par défaut).
2. Cliquer sur **Scanner** : seuls les EPUB non convertis ou dont le découpage
   n'est plus optimal sont affichés. Les romans ayant déjà des PDF dans
   `pdfs_traduits/` sont masqués pour ne pas casser le suivi des traductions.
3. Sélectionner les EPUB puis cliquer sur **Convertir**.

Le PDF complet est construit une seule fois puis découpé en parties équilibrées
(`ceil(total / pages_max)`). Une coupure peut donc tomber au milieu d'un
chapitre, mais le nombre de fichiers à traduire est minimal. Le découpage est
mémorisé dans `.conversion.json` : modifier la limite ou l'EPUB source déclenche
une reconversion, et les anciennes parties sont remplacées.

### PDF traduits → EPUB

1. Ouvrir l'onglet **Traduit → EPUB**.
2. Choisir le roman dans la liste **Roman** (ou sélectionner son dossier dans `pdfs_traduits/`).
3. Cliquer sur **Scanner** : les chapitres détectés s'affichent avec leur statut.
4. Cliquer sur **Créer / Mettre à jour l'EPUB**.

L'EPUB est toujours écrit dans `epubs/<nom-du-roman>.epub` : il n'y a plus de
chemin de sortie personnalisé. Lors d'une mise à jour, l'ancien fichier est
remplacé proprement (écriture temporaire puis renommage atomique), sans créer de
doublon ni concaténer l'ancien contenu. Après l'ajout de nouveaux PDF traduits,
un nouveau scan ne ré-extrait que ces fichiers grâce au cache `.epub_build/`
conservé dans le dossier du roman.

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
| `app_gui.py` | Interface graphique complète |
| `moteur/export_epub.py` | Assemblage des PDF traduits en EPUB (cache incrémental) |
| `moteur/convertisseur_epub.py` | Conversion EPUB → PDF découpés par pages |
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
