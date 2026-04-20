"""
build_mac.py - Script di build ESCLUSIVO per macOS
Esegui con: python3 build_mac.py
"""
import os
import subprocess
import sys
import shutil

def build_mac():
    print("--- [DATARIUM] Build macOS ---")
    print(f"Python: {sys.executable}")

    app_dir = os.path.dirname(os.path.abspath(__file__))

    # Usa il Python del venv se esiste (percorso macOS: venv/bin/python3)
    python_exe = os.path.join(app_dir, "venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    # 1. Offuscamento PyArmor
    print("\n[1/2] Offuscamento codice sorgente...")
    try:
        subprocess.run([python_exe, "-m", "pyarmor.cli", "gen", "-O", "obfuscated",
                        "main.py", "ai_engine.py", "license_manager.py"], check=True)
    except Exception as e:
        print(f"Errore offuscamento: {e}")
        return

    # Copia icona nella cartella obfuscated se esiste
    icon_src = os.path.join(app_dir, "icon.icns")  # Mac usa .icns
    icon_ico = os.path.join(app_dir, "icon.ico")   # Fallback .ico
    icon_arg = icon_src if os.path.exists(icon_src) else icon_ico
    if os.path.exists(icon_src):
        shutil.copy(icon_src, "obfuscated/icon.icns")
    elif os.path.exists(icon_ico):
        shutil.copy(icon_ico, "obfuscated/icon.ico")

    # 2. Trova il percorso EFFETTIVO di llama_cpp nel venv per includere i .dylib
    try:
        result = subprocess.run(
            [python_exe, "-c", "import llama_cpp; import os; print(os.path.dirname(llama_cpp.__file__))"],
            capture_output=True, text=True, check=True
        )
        llama_cpp_path = result.stdout.strip()
        print(f"llama_cpp trovato in: {llama_cpp_path}")
    except Exception as e:
        print(f"ERRORE: llama_cpp non trovato! Assicurati di aver installato llama-cpp-python nel venv. ({e})")
        return

    # 3. Build PyInstaller per macOS
    print("\n[2/2] Compilazione .app per macOS...")

    dist_cmd = [
        python_exe, "-m", "PyInstaller",
        "--noconsole",
        "--onedir",
        "--noconfirm",
        "--windowed",               # Crea un .app bundle macOS
        "--paths", "obfuscated",
        "--collect-all=customtkinter",
        "--collect-all=llama_cpp",  # Raccoglie tutto llama_cpp inclusi .dylib
        "--collect-all=huggingface_hub",
        "--collect-all=certifi",
        "--collect-all=requests",
        "--collect-binaries=llama_cpp",  # FONDAMENTALE per macOS: raccoglie i .dylib nativi
        "--hidden-import=customtkinter",
        "--hidden-import=llama_cpp",
        "--hidden-import=llama_cpp.lib",
        "--hidden-import=llama_cpp.llama_chat_format",
        "--hidden-import=ai_engine",
        "--hidden-import=license_manager",
        "--hidden-import=PIL",
        "--hidden-import=fitz",
        "--hidden-import=docx",
        "--hidden-import=jwt",
        "--hidden-import=cryptography",
        "--add-data=obfuscated/ai_engine.py:.",
        "--add-data=obfuscated/license_manager.py:.",   # macOS usa ':' invece di ';'
        "--name=Datarium",
        "obfuscated/main.py"
    ]

    # Aggiungi icona se disponibile
    if os.path.exists(icon_src):
        dist_cmd.insert(4, f"--icon={icon_src}")

    subprocess.run(dist_cmd, check=True)

    print("\n✅ Build macOS completata!")
    print("Trovi l'app in: dist/Datarium.app")
    print("\nPer creare il DMG (opzionale):")
    print("  hdiutil create -volname 'Datarium' -srcfolder dist/Datarium.app -ov -format UDZO dist/Datarium.dmg")

if __name__ == "__main__":
    build_mac()
