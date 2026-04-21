import os
import sys
import subprocess
import shutil

def fuse():
    print("--- [ULTIMATE FUSION] Datarium Single-File Generator ---")
    
    # Files to look for
    installer_exe = "Datarium_Installer_Win_Completo.exe"
    installer_bin = "Datarium_Installer_Win_Completo-1.bin"
    
    if not os.path.exists(installer_exe) or not os.path.exists(installer_bin):
        print(f"ERRORE: Assicurati di aver compilato con Inno Setup!")
        print(f"Mancano: {installer_exe} o {installer_bin}")
        return

    print(f"Fase 1: Preparazione Bootloader per {installer_exe}...")
    
    # Creiamo un piccolo script Python che fungerà da motore di lancio
    boot_script = """
import os
import sys
import subprocess
import tempfile
import shutil

def launch():
    # Crea una cartella temporanea sicura
    temp_dir = tempfile.mkdtemp(prefix='datarium_setup_')
    try:
        # Trova i file estratti (grazie a PyInstaller)
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        
        exe_path = os.path.join(base_path, 'setup_main.exe')
        bin_path = os.path.join(base_path, 'setup_data.bin')
        
        # Copia i file nel temp per permettere l'esecuzione corretta
        shutil.copy2(exe_path, os.path.join(temp_dir, 'installer.exe'))
        shutil.copy2(bin_path, os.path.join(temp_dir, 'installer-1.bin'))
        
        # Avvia l'installer reale
        print("Avvio installazione Datarium...")
        subprocess.run([os.path.join(temp_dir, 'installer.exe')], check=True)
    finally:
        # Pulizia (opzionale, meglio lasciare l'installer gestire la fine)
        pass

if __name__ == '__main__':
    launch()
"""

    with open("boot_engine.py", "w", encoding="utf-8") as f:
        f.write(boot_script)

    print("Fase 2: Fusione Atomica in corso (Creazione Master EXE da 6GB+)...")
    print("Nota: Questa operazione potrebbe richiedere qualche minuto a causa della dimensione.")
    
    try:
        # Usiamo PyInstaller per creare il file unico
        # Rinominiamo i file internamente per chiarezza
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconsole",
            "--onefile",
            "--icon=icon.ico",
            f"--add-data={installer_exe};.",
            f"--add-data={installer_bin};.",
            "--name=Datarium_ULTIMATE_Setup",
            "--contents-directory=internal",
            "boot_engine.py"
        ]
        
        # Modifichiamo il comando per mappare i nomi correttamente dentro lo script
        # Invece di rinominare sul disco, lo facciamo via aggiunta dati
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconsole",
            "--onefile",
            "--icon=icon.ico",
            f"--add-data={installer_exe};setup_main.exe", # Mappatura interna
            f"--add-data={installer_bin};setup_data.bin", # Mappatura interna
            "--name=Datarium_ULTIMATE_Setup",
            "boot_engine.py"
        ]
        
        subprocess.run(cmd, check=True)
        
        print("\n\u2705 FUSIONE COMPLETATA!")
        print("Trovi il tuo unico Master EXE in: dist/Datarium_ULTIMATE_Setup.exe")
        print("Dimensione prevista: ~6.2 GB")
        
    except Exception as e:
        print(f"Errore durante la fusione: {e}")
    finally:
        if os.path.exists("boot_engine.py"): os.remove("boot_engine.py")

if __name__ == "__main__":
    fuse()
