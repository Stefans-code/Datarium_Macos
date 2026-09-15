"""
system_actions.py — azioni di sistema legate a Offload:

1. Impedire che il PC vada in sospensione/schermata di blocco durante una copia
   lunga: su Mac bloccare lo schermo (es. con Touch ID) mentre Offload sta
   scrivendo interrompe la copia a metà — Datarium deve tenere il sistema sveglio
   per tutta la durata del job, come fanno Silverstack/ShotPut Pro.
2. Espellere in sicurezza la sorgente (es. la SD card della camera) a fine copia.
3. Spegnere il PC a fine copia, con un ritardo che lascia il tempo di annullare.

Tutte le funzioni sono "best effort": un fallimento non deve mai far crashare
Offload né bloccare l'interfaccia, solo essere segnalato con (ok, messaggio).
"""
import os
import platform
import subprocess
import time


class SleepInhibitor:
    """Context manager: impedisce la sospensione/spegnimento schermo del sistema
    per tutta la sua durata. Usare con `with SleepInhibitor(): ...` attorno al
    ciclo di copia di Offload/Ingest."""

    def __init__(self):
        self._system = platform.system()
        self._proc = None  # macOS/Linux: processo esterno da tenere vivo

    def __enter__(self):
        try:
            if self._system == "Windows":
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_DISPLAY_REQUIRED = 0x00000002
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
            elif self._system == "Darwin":
                # 'caffeinate' senza -t resta attivo finché non lo si termina noi:
                # -d (schermo), -i (sistema), -m (disco), -s (system sleep su AC).
                self._proc = subprocess.Popen(["caffeinate", "-dims"])
            else:
                # Linux: systemd-inhibit blocca sleep/idle/shutdown finché il
                # comando che avvolge (qui una sleep lunga) resta vivo.
                self._proc = subprocess.Popen([
                    "systemd-inhibit", "--what=sleep:idle:shutdown",
                    "--why=Datarium Offload in corso", "sleep", "999999"
                ])
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._system == "Windows":
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            elif self._proc is not None:
                self._proc.terminate()
        except Exception:
            pass
        return False


def eject_volume(path):
    """
    Espelle in sicurezza il volume che contiene `path` (tipicamente la SD card
    sorgente di un Offload). Ritorna (ok: bool, messaggio: str) — non solleva mai.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            # Se `path` è una sottocartella del volume (es. l'utente ha scelto come
            # sorgente una cartella dentro la SD card, non la card stessa), diskutil
            # può non risolverla correttamente: risaliamo ai genitori fino al vero
            # mount point prima di espellere.
            mount_path = os.path.abspath(path)
            while not os.path.ismount(mount_path) and os.path.dirname(mount_path) != mount_path:
                mount_path = os.path.dirname(mount_path)
            res = subprocess.run(["diskutil", "eject", mount_path], capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                return True, (res.stdout or res.stderr).strip()
            # Il volume può risultare "busy" per una frazione di secondo subito dopo
            # l'ultima scrittura/chiusura file: un secondo tentativo breve copre la
            # maggior parte di questi falsi negativi, senza mai forzare (-force).
            time.sleep(1.0)
            res2 = subprocess.run(["diskutil", "eject", mount_path], capture_output=True, text=True, timeout=15)
            return res2.returncode == 0, (res2.stdout or res2.stderr).strip()

        elif system == "Windows":
            # Non c'è un "eject" nativo a riga di comando: primo tentativo con
            # l'automazione Shell (stesso verbo "Eject" del tasto destro -> Espelli
            # in Esplora File). Il COM però NON segnala errore se il verbo non esiste
            # per quel tipo di unità: molti HDD USB esterni sono visti da Windows come
            # "Fixed" (non "Removable") e semplicemente non hanno il verbo "Eject",
            # quindi la chiamata "riesce" senza scollegare nulla. Per questo verifichiamo
            # DAVVERO se l'unità è sparita, invece di fidarci del solo returncode.
            drive = os.path.splitdrive(os.path.abspath(path))[0]
            if not drive:
                return False, "Impossibile determinare l'unità da espellere."
            drive_root = drive + "\\"

            def _still_present():
                return os.path.exists(drive_root)

            ps_cmd = (
                "$sh = New-Object -ComObject Shell.Application; "
                f"$item = $sh.Namespace(17).ParseName('{drive_root}'); "
                "if ($item) { $item.InvokeVerb('Eject') }"
            )
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                            capture_output=True, text=True, timeout=15)
            time.sleep(1.5)
            if not _still_present():
                return True, "Sorgente espulsa."

            # Fallback: smonta il volume via WMI (Win32_Volume.Dismount). Copre il caso,
            # molto comune con gli HDD USB esterni, in cui il verbo "Eject" non esiste:
            # qui non si "espelle" fisicamente il disco (niente notifica "sicuro da
            # rimuovere"), ma si smonta il file system, il che è comunque sufficiente e
            # sicuro per lo scollegamento.
            ps_cmd2 = (
                f"$vol = Get-WmiObject -Class Win32_Volume -Filter \"DriveLetter='{drive}'\"; "
                "if ($vol) { $vol.Dismount($false, $false) }"
            )
            res2 = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd2],
                                   capture_output=True, text=True, timeout=15)
            time.sleep(1.0)
            if not _still_present():
                return True, "Sorgente smontata."
            return False, (res2.stdout or res2.stderr).strip() or "Espulsione non riuscita: l'unità risulta ancora presente."

        else:
            # Linux: risali dal path al device montato, poi smontalo con udisksctl
            # (funziona senza sudo per i dispositivi rimovibili dell'utente corrente).
            res = subprocess.run(["findmnt", "-n", "-o", "SOURCE", "--target", path],
                                  capture_output=True, text=True, timeout=10)
            device = res.stdout.strip()
            if not device:
                return False, "Impossibile determinare il device da smontare."
            res2 = subprocess.run(["udisksctl", "unmount", "-b", device],
                                   capture_output=True, text=True, timeout=15)
            return res2.returncode == 0, (res2.stdout or res2.stderr).strip()
    except Exception as e:
        return False, str(e)


def shutdown_computer(delay_seconds=60):
    """
    Avvia lo spegnimento del PC con un ritardo (in secondi) per lasciare il tempo
    di annullare. Ritorna (ok: bool, messaggio: str, handle) — handle è il processo
    da terminare per annullare su macOS (dove non esiste un comando di annullamento
    a parte), None sulle altre piattaforme (annullabile con cancel_shutdown()).
    """
    system = platform.system()
    try:
        if system == "Windows":
            res = subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)],
                                  capture_output=True, text=True, timeout=10)
            return res.returncode == 0, (res.stdout or res.stderr).strip() or f"Spegnimento tra {delay_seconds}s.", None

        elif system == "Darwin":
            # 'shutdown -h' richiede privilegi elevati; passando da System Events non
            # serve sudo. Il ritardo è simulato con 'delay' nello script stesso, quindi
            # per annullare bisogna terminare QUESTO processo prima che scada.
            script = f'delay {delay_seconds}\ntell application "System Events" to shut down'
            proc = subprocess.Popen(["osascript", "-e", script])
            return True, f"Spegnimento programmato tra {delay_seconds}s.", proc

        else:
            minutes = max(1, delay_seconds // 60)
            res = subprocess.run(["shutdown", "-h", f"+{minutes}"],
                                  capture_output=True, text=True, timeout=10)
            return res.returncode == 0, (res.stdout or res.stderr).strip() or f"Spegnimento tra {minutes} min.", None
    except Exception as e:
        return False, str(e), None


def https_context():
    """
    Contesto SSL basato sulla CA bundle di certifi, non su quella di sistema.

    Nei build PyInstaller su macOS il Python "imbustato" spesso non trova un
    certificate store di sistema valido (manca il passo "Install Certificates.command"
    che i build python.org normali eseguono all'installazione): ogni
    urllib.request.urlopen su https fallisce con
    "SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate"
    anche se il sito ha un certificato perfettamente valido. certifi porta con sé
    una CA bundle propria, indipendente dal sistema, che risolve il problema.
    """
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def cancel_shutdown(handle=None):
    """Annulla uno spegnimento programmato con shutdown_computer(). Su Windows/Linux
    usa il comando di sistema; su macOS termina il processo `handle` (l'AppleScript
    con 'delay' non è annullabile altrimenti). Best effort, non solleva mai."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(["shutdown", "/a"], capture_output=True, text=True, timeout=10)
        elif system == "Darwin":
            if handle is not None:
                handle.terminate()
        else:
            subprocess.run(["shutdown", "-c"], capture_output=True, text=True, timeout=10)
    except Exception:
        pass
