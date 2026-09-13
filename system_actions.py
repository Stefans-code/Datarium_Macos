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
            res = subprocess.run(["diskutil", "eject", path], capture_output=True, text=True, timeout=15)
            return res.returncode == 0, (res.stdout or res.stderr).strip()

        elif system == "Windows":
            # Non c'è un "eject" nativo a riga di comando: usiamo l'automazione
            # Shell (stesso verbo "Eject" del tasto destro -> Espelli in Esplora File).
            drive = os.path.splitdrive(os.path.abspath(path))[0]
            if not drive:
                return False, "Impossibile determinare l'unità da espellere."
            ps_cmd = (
                "$sh = New-Object -ComObject Shell.Application; "
                f"$sh.Namespace(17).ParseName('{drive}\\').InvokeVerb('Eject')"
            )
            res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                                  capture_output=True, text=True, timeout=15)
            return res.returncode == 0, (res.stdout or res.stderr).strip() or "Comando di espulsione inviato."

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
