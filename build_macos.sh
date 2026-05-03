#!/bin/bash
echo "==========================================="
echo "[INFO] Building Datarium for macOS..."
echo "==========================================="

# Install requirements
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller

echo "[INFO] 1. Creating macOS app bundle with PyInstaller..."
pyinstaller --noconfirm --onedir --windowed --icon=icon.ico --name=Datarium --add-data="icon.ico:." --add-data="assets:assets" main.py

echo "[INFO] 2. Packaging app into DMG..."
# Check for create-dmg tool
if command -v create-dmg &> /dev/null
then
    create-dmg \
      --volname "Datarium Installer" \
      --window-pos 200 120 \
      --window-size 600 400 \
      --icon-size 100 \
      --icon "Datarium.app" 175 120 \
      --hide-extension "Datarium.app" \
      --app-drop-link 425 120 \
      "Datarium_Installer_macOS.dmg" \
      "dist/"
else
    echo "[INFO] create-dmg command not found. Creating a simple dmg using hdiutil..."
    hdiutil create -volname "Datarium" -srcfolder "dist/Datarium.app" -ov -format UDZO "Datarium_Setup_macOS.dmg"
fi

echo "[SUCCESS] macOS Build completed successfully!"
