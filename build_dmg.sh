#!/bin/bash
# =============================================================
#  Datarium - Build DMG per macOS (Intel + Apple Silicon)
#  Esegui DOPO setup_mac.sh con: bash build_dmg.sh
# =============================================================

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     DATARIUM - Build DMG per macOS           ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ARCH=$(uname -m)

# Controlla il venv
if [ ! -f "venv/bin/activate" ]; then
    echo "❌ Errore: venv non trovato. Esegui prima: bash setup_mac.sh"
    exit 1
fi

source venv/bin/activate
python_exe="$APP_DIR/venv/bin/python3"

# 1. Offuscamento PyArmor
echo "[1/4] Offuscamento codice sorgente..."
$python_exe -m pyarmor.cli gen -O obfuscated main.py ai_engine.py license_manager.py
if [ $? -ne 0 ]; then
    echo "❌ Errore offuscamento!"
    exit 1
fi
echo "    ✓ Codice offuscato"

# 2. Build PyInstaller → .app
echo "[2/4] Compilazione .app bundle..."

# Icona: preferisci .icns (nativa macOS), fallback su .png
ICON_ARG=""
if [ -f "icon.icns" ]; then
    ICON_ARG="--icon=icon.icns"
elif [ -f "icon.png" ]; then
    ICON_ARG="--icon=icon.png"
fi

$python_exe -m PyInstaller \
    --noconsole \
    --onedir \
    --noconfirm \
    --windowed \
    --name="Datarium" \
    --paths obfuscated \
    --collect-all customtkinter \
    --collect-all llama_cpp \
    --collect-all huggingface_hub \
    --collect-all certifi \
    --collect-binaries llama_cpp \
    --hidden-import customtkinter \
    --hidden-import llama_cpp \
    --hidden-import llama_cpp.lib \
    --hidden-import llama_cpp.llama_chat_format \
    --hidden-import ai_engine \
    --hidden-import license_manager \
    --hidden-import PIL \
    --hidden-import fitz \
    --hidden-import docx \
    --hidden-import jwt \
    --hidden-import cryptography \
    --add-data "obfuscated/ai_engine.py:." \
    --add-data "obfuscated/license_manager.py:." \
    $ICON_ARG \
    obfuscated/main.py

if [ $? -ne 0 ]; then
    echo "❌ Errore nella build!"
    exit 1
fi
echo "    ✓ .app creato in dist/Datarium.app"

# 3. Crea la cartella models dentro l'app
echo "[3/4] Preparazione struttura app..."
mkdir -p "dist/Datarium.app/Contents/MacOS/models"
echo "    ✓ Cartella models creata"

# 4. Crea DMG
echo "[4/4] Creazione DMG..."
DMG_NAME="Datarium_Mac.dmg"
DMG_PATH="dist/$DMG_NAME"

# Rimuovi vecchio DMG se esiste
[ -f "$DMG_PATH" ] && rm "$DMG_PATH"

# Crea DMG con layout professionale
hdiutil create \
    -volname "Datarium" \
    -srcfolder "dist/Datarium.app" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_PATH"

if [ $? -eq 0 ]; then
    DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ✅ DMG creato con successo!                 ║"
    echo "║  📦 File: dist/$DMG_NAME"
    echo "║  📏 Dimensione: $DMG_SIZE"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
else
    echo "❌ Errore nella creazione del DMG"
    exit 1
fi
