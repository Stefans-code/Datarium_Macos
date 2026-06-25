"""
build_protected.py - Build di Datarium con CODICE PROTETTO (Cython).

Compila i moduli Python core in binari nativi (.pyd su Windows, .so su macOS/Linux)
cosi' il codice NON e' decompilabile dopo l'installazione. La logica principale
(oggi in main.py) viene compilata come modulo 'datarium_app'; resta in chiaro solo
un entry-point minimale che non contiene logica sensibile.

IMPORTANTE: i file sorgente originali NON vengono modificati. Tutto avviene in una
cartella di staging temporanea ('build_src/').

Requisiti:
  - cython, pyinstaller
  - un compilatore C: MSVC (Build Tools) su Windows, clang su macOS, gcc su Linux

Uso:
  python build_protected.py
Output:
  dist/Datarium/  (bundle PyInstaller con i moduli core compilati)
"""
import os
import sys
import shutil
import subprocess
import platform
import shlex

# Prefisso opzionale per forzare l'architettura dei comandi (es. "arch -x86_64" nella CI Intel).
ARCH_PREFIX = os.environ.get("BUILD_ARCH_PREFIX", "").strip()

ROOT = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(ROOT, "build_src")

# Moduli core compilati in binario (protetti). main.py -> datarium_app (logica completa).
CORE_MODULES = ["ai_engine.py", "license_manager.py", "face_memory.py", "report_generator.py"]
APP_SRC = "main.py"
APP_DST = "datarium_app.py"

# Entry-point minimale: nessuna logica sensibile, solo bootstrap + import del modulo compilato.
ENTRY_CODE = '''# Entry-point Datarium (auto-generato da build_protected.py).
import os
import sys
import tempfile

try:
    os.chdir(tempfile.gettempdir())
except Exception:
    pass

if os.name == "nt":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

if getattr(sys, "frozen", False):
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

# Import forzati per far includere a PyInstaller le C-extension e i moduli compilati.
if False:
    import xxhash
    import pillow_heif
    import fitz
    import docx
    import llama_cpp
    import llama_cpp.llama_chat_format
    import cv2
    import ai_engine
    import license_manager
    import face_memory
    import report_generator
    import datarium_app

from datarium_app import DatariumApp

def _main():
    try:
        app = DatariumApp()
        app.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(f"CRITICAL ERROR AT STARTUP: {e}\\n")
            f.write(traceback.format_exc())

if __name__ == "__main__":
    _main()
'''


def run(cmd, cwd=None):
    if ARCH_PREFIX:
        cmd = shlex.split(ARCH_PREFIX) + list(cmd)
    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    py = sys.executable
    is_win = platform.system() == "Windows"
    ext = ".pyd" if is_win else ".so"
    sep = ";" if is_win else ":"  # separatore --add-data di PyInstaller

    print("=== [1/4] Preparazione cartella di staging ===")
    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)

    # Copia i moduli core
    for m in CORE_MODULES:
        shutil.copy2(os.path.join(ROOT, m), os.path.join(STAGE, m))
    # main.py -> datarium_app.py (diventa modulo compilato)
    shutil.copy2(os.path.join(ROOT, APP_SRC), os.path.join(STAGE, APP_DST))
    # Risorse
    if os.path.exists(os.path.join(ROOT, "icon.ico")):
        shutil.copy2(os.path.join(ROOT, "icon.ico"), os.path.join(STAGE, "icon.ico"))
    if os.path.exists(os.path.join(ROOT, "assets")):
        shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(STAGE, "assets"))

    print("=== [2/4] Compilazione moduli con Cython (binari nativi) ===")
    to_compile = CORE_MODULES + [APP_DST]
    run([py, "-m", "Cython.Build.Cythonize", "-i", "-3"] + to_compile, cwd=STAGE)

    # Rimuove i .py e .c sorgente: nel bundle resteranno solo i binari compilati
    for m in to_compile:
        base = m[:-3]
        for junk in (m, base + ".c"):
            p = os.path.join(STAGE, junk)
            if os.path.exists(p):
                os.remove(p)
        # verifica che il binario esista
        produced = [f for f in os.listdir(STAGE) if f.startswith(base) and f.endswith(ext)]
        if not produced:
            raise SystemExit(f"ERRORE: compilazione fallita per {m} (nessun {ext} prodotto)")
        print(f"   protetto: {produced[0]}")

    # Scrive l'entry-point minimale
    entry_path = os.path.join(STAGE, "main.py")
    with open(entry_path, "w", encoding="utf-8") as f:
        f.write(ENTRY_CODE)

    print("=== [3/4] Bundling con PyInstaller ===")
    icon_arg = ["--icon=icon.ico"] if os.path.exists(os.path.join(STAGE, "icon.ico")) else []
    add_data = [f"--add-data=icon.ico{sep}.", f"--add-data=assets{sep}assets"]
    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--onedir", "--windowed",
        "--name=Datarium",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", STAGE,
        "--paths", ".",
        "--collect-all=customtkinter",
        "--collect-all=llama_cpp",
        "--collect-all=huggingface_hub",
        "--collect-all=certifi",
        "--collect-all=requests",
        "--hidden-import=customtkinter",
        "--hidden-import=llama_cpp",
        "--hidden-import=ai_engine",
        "--hidden-import=license_manager",
        "--hidden-import=face_memory",
        "--hidden-import=report_generator",
        "--hidden-import=datarium_app",
        "--hidden-import=PIL",
        "--hidden-import=fitz",
        "--hidden-import=docx",
        "--hidden-import=jwt",
    ] + icon_arg + add_data + ["main.py"]
    run(cmd, cwd=STAGE)

    print("=== [4/4] Completato ===")
    print(f"Bundle protetto in: {os.path.join(ROOT, 'dist', 'Datarium')}")
    print("I moduli core sono binari compilati (.pyd/.so), non decompilabili.")


if __name__ == "__main__":
    main()
