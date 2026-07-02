#!/bin/bash
# Traducteur PDF - Installer
set -e
echo "=== Traducteur PDF v8 Installer ==="

# Check for pip deps
echo "[1/3] Checking Python dependencies..."
pip3 install --break-system-packages pdfplumber deep_translator reportlab pypdf 2>/dev/null || true

# Copy files
APP_DIR="${HOME}/.local/share/traducteur-pdf"
BIN_DIR="${HOME}/.local/bin"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
DESKTOP_DIR="${HOME}/.local/share/applications"

mkdir -p "$APP_DIR" "$BIN_DIR" "$ICON_DIR" "$DESKTOP_DIR"

echo "[2/3] Installing application..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/app_gui.py" "$APP_DIR/"
cp "$SCRIPT_DIR/traduire_pdfs_v2.py" "$APP_DIR/"
cp "$SCRIPT_DIR/stats_manager.py" "$APP_DIR/"
cp "$SCRIPT_DIR/themes.py" "$APP_DIR/"
cp "$SCRIPT_DIR/verifier_traductions.py" "$APP_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/"
cp "$SCRIPT_DIR/README.md" "$APP_DIR/"

# Icon
if [ -f "$SCRIPT_DIR/assets/icons/traducteur-pdf-256.png" ]; then
    cp "$SCRIPT_DIR/assets/icons/traducteur-pdf-256.png" "$ICON_DIR/traducteur-pdf.png"
fi

# Launcher
cat > "$BIN_DIR/traducteur-pdf" << LAUNCHER
#!/usr/bin/env python3
import os, sys, subprocess
APP_DIR = "${APP_DIR}"
def ensure_deps():
    try:
        import pdfplumber, deep_translator, reportlab, pypdf
        return
    except ImportError:
        pass
    req = os.path.join(APP_DIR, "requirements.txt")
    if os.path.exists(req):
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", req],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if __name__ == "__main__":
    os.chdir(APP_DIR)
    sys.path.insert(0, APP_DIR)
    try:
        ensure_deps()
    except Exception:
        pass
    from app_gui import main
    main()
LAUNCHER
chmod +x "$BIN_DIR/traducteur-pdf"

# Desktop entry
cat > "$DESKTOP_DIR/traducteur-pdf.desktop" << DESK
[Desktop Entry]
Type=Application
Name=Traducteur PDF
GenericName=PDF Translator
Comment=Mass PDF translator - 12 features
Exec=${BIN_DIR}/traducteur-pdf
Icon=${ICON_DIR}/traducteur-pdf.png
Terminal=false
Categories=Office;Utility;
StartupNotify=true
MimeType=application/pdf;
DESK

echo "[3/3] Updating desktop database..."
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true

echo ""
echo "=== Installation complete ==="
echo "Run: ${BIN_DIR}/traducteur-pdf"
echo "Or find 'Traducteur PDF' in your applications menu."
