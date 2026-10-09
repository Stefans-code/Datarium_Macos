"""
Ricerca di ffmpeg/ffprobe e lettura dei metadati video, in UN solo posto.

Ordine di ricerca di ffmpeg:
  1. percorso scelto dall'utente nelle Impostazioni (se valido);
  2. la copia INCLUSA nell'installer (cartella 'ffmpeg' fra le risorse dell'app): da
     1.4.1 Datarium funziona senza che l'utente installi nulla (prima, su un Mac senza
     ffmpeg, proxy e analisi dei video fallivano con "FFMPEG non trovato");
  3. PATH di sistema e posizioni comuni (Homebrew, MacPorts, apt, snap...). Le app avviate
     dal Finder non ereditano il PATH della shell, per questo servono i percorsi espliciti.

ffprobe e' opzionale: su Mac e Linux viene incluso solo ffmpeg (un ffprobe statico pesa
quanto ffmpeg) e i metadati si leggono dall'output di 'ffmpeg -i', con lo stesso formato
del JSON di ffprobe, cosi' chi li usa non deve sapere da dove arrivano.
"""
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys

IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""
_NO_WINDOW = 0x08000000 if IS_WIN else 0   # CREATE_NO_WINDOW: niente console che lampeggia

COMMON_PATHS = (
    [r"C:\Program Files\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"] if IS_WIN else
    ["/opt/homebrew/bin/ffmpeg",            # macOS Apple Silicon (Homebrew)
     "/usr/local/bin/ffmpeg",               # macOS Intel (Homebrew) / build manuali
     "/opt/local/bin/ffmpeg",               # macOS MacPorts
     "/usr/bin/ffmpeg",                     # Linux (apt/dnf/pacman)
     "/snap/bin/ffmpeg",                    # Linux snap
     "/var/lib/flatpak/exports/bin/ffmpeg",
     os.path.expanduser("~/bin/ffmpeg")]
)

_cache = {}


def _bundle_dirs():
    """Cartelle in cui puo' trovarsi la copia inclusa, per ogni modalita' di esecuzione."""
    dirs = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(os.path.join(meipass, "ffmpeg"))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        dirs.append(os.path.join(exe_dir, "ffmpeg"))
        dirs.append(os.path.join(exe_dir, "_internal", "ffmpeg"))
        if platform.system() == "Darwin" and "/Contents/MacOS" in exe_dir.replace("\\", "/"):
            contents = os.path.dirname(exe_dir)
            dirs.append(os.path.join(contents, "Resources", "ffmpeg"))
            dirs.append(os.path.join(contents, "Frameworks", "ffmpeg"))
    else:
        # sviluppo: cartella 'ffmpeg' accanto ai sorgenti (la stessa che finisce nel bundle)
        dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg"))
    return dirs


def _runs(executable):
    try:
        res = subprocess.run([executable, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=8, creationflags=_NO_WINDOW)
        return res.returncode == 0
    except Exception:
        return False


def _ensure_executable(path):
    """Gli archivi a volte perdono il bit di esecuzione: lo si ripristina se possibile."""
    if IS_WIN:
        return
    try:
        mode = os.stat(path).st_mode
        if not mode & stat.S_IXUSR:
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def bundled_ffmpeg():
    for d in _bundle_dirs():
        p = os.path.join(d, "ffmpeg" + EXE)
        if os.path.isfile(p):
            _ensure_executable(p)
            return p
    return None


def find_ffmpeg(custom_path=None):
    """(True, percorso) oppure (False, messaggio per l'utente)."""
    if custom_path:
        custom_path = os.path.abspath(custom_path.strip())
        exe = os.path.join(custom_path, "ffmpeg" + EXE) if os.path.isdir(custom_path) else custom_path
        if os.path.isfile(exe):
            if _runs(exe):
                return True, exe
            return False, "Il file FFMPEG indicato non si avvia. Lascia il campo vuoto per usare quello incluso in Datarium."
        return False, "Percorso FFMPEG non valido o inesistente. Lascia il campo vuoto per usare quello incluso in Datarium."

    if "auto" in _cache and os.path.isfile(_cache["auto"]):
        return True, _cache["auto"]
    candidates = [bundled_ffmpeg(), shutil.which("ffmpeg")] + COMMON_PATHS
    for c in candidates:
        if c and os.path.isfile(c) and _runs(c):
            _cache["auto"] = c
            return True, c
    return False, "FFMPEG non trovato: la copia inclusa in Datarium manca o non si avvia. Reinstalla Datarium oppure indica un ffmpeg con «Sfoglia»."


def is_bundled(path):
    b = bundled_ffmpeg()
    return bool(b and path and os.path.abspath(b) == os.path.abspath(path))


def find_ffprobe(ffmpeg_bin):
    """ffprobe accanto a ffmpeg (stessa distribuzione) o nel PATH; None se assente."""
    if ffmpeg_bin:
        p = os.path.join(os.path.dirname(ffmpeg_bin), "ffprobe" + EXE)
        if os.path.isfile(p):
            return p
    return shutil.which("ffprobe")


# ---------------------------------------------------------------------------------------
# Metadati: JSON di ffprobe se disponibile, altrimenti lo stesso formato ricavato da ffmpeg -i
# ---------------------------------------------------------------------------------------
def probe(file_path, ffmpeg_bin=None, timeout=20):
    """Dizionario {'format': {...}, 'streams': [...]} come 'ffprobe -show_format -show_streams',
    oppure None se il file non e' leggibile."""
    if ffmpeg_bin is None:
        ok, ffmpeg_bin = find_ffmpeg()
        if not ok:
            ffmpeg_bin = None
    ffprobe = find_ffprobe(ffmpeg_bin)
    if ffprobe:
        try:
            res = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, creationflags=_NO_WINDOW)
            if res.returncode == 0 and res.stdout:
                return json.loads(res.stdout.decode("utf-8", errors="ignore"))
        except Exception:
            pass
    if not ffmpeg_bin:
        return None
    try:
        res = subprocess.run([ffmpeg_bin, "-hide_banner", "-i", file_path], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=timeout, creationflags=_NO_WINDOW)
    except Exception:
        return None
    return parse_ffmpeg_info(res.stderr.decode("utf-8", errors="ignore"))


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_BITRATE = re.compile(r"bitrate:\s*(\d+)\s*kb/s")
_STREAM = re.compile(r"^\s*Stream #\d+:\d+.*?:\s*(Video|Audio|Data|Subtitle):\s*([A-Za-z0-9_\-]+)(.*)$")
_RES = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_FPS = re.compile(r"([\d.]+)\s*fps")
_STREAM_BR = re.compile(r"(\d+)\s*kb/s")
_META = re.compile(r"^\s{2,}([A-Za-z0-9_.\-]+(?: [A-Za-z0-9_.\-]+)*)\s*:\s?(.*)$")


def _fps_fraction(value):
    """'25' -> '25/1', '29.97' -> '30000/1001' (come r_frame_rate di ffprobe)."""
    try:
        f = float(value)
    except ValueError:
        return "0/1"
    for num, den in ((24000, 1001), (30000, 1001), (60000, 1001)):
        if abs(f - num / den) < 0.005:
            return f"{num}/{den}"
    return f"{int(round(f * 1000))}/1000" if f != int(f) else f"{int(f)}/1"


def parse_ffmpeg_info(text):
    """Trasforma l'output di 'ffmpeg -i' nel sottoinsieme del JSON di ffprobe usato da
    Datarium. Ritorna None se non c'e' nessun flusso (file non multimediale/illeggibile)."""
    fmt = {"tags": {}}
    streams = []
    current_tags = fmt["tags"]
    in_input = False
    for line in text.splitlines():
        if line.startswith("Input #"):
            in_input = True
            continue
        if not in_input:
            continue
        if line.startswith("Output #") or line.startswith("At least one output"):
            break
        m = _DURATION.search(line)
        if m:
            h, mi, s = m.groups()
            fmt["duration"] = str(int(h) * 3600 + int(mi) * 60 + float(s))
            b = _BITRATE.search(line)
            if b:
                fmt["bit_rate"] = str(int(b.group(1)) * 1000)
            continue
        m = _STREAM.match(line)
        if m:
            kind, codec, rest = m.groups()
            st = {"codec_type": kind.lower(), "codec_name": codec.lower(), "tags": {}}
            if kind == "Video":
                r = _RES.search(rest)
                if r:
                    st["width"], st["height"] = int(r.group(1)), int(r.group(2))
                f = _FPS.search(rest)
                if f:
                    st["r_frame_rate"] = _fps_fraction(f.group(1))
            br = _STREAM_BR.search(rest)
            if br:
                st["bit_rate"] = str(int(br.group(1)) * 1000)
            streams.append(st)
            current_tags = st["tags"]
            continue
        if line.strip() in ("Metadata:", "Side data:", "Chapters:"):
            continue
        m = _META.match(line)
        if m and m.group(1).lower() not in ("duration",):
            key = m.group(1).strip()
            if key not in current_tags:
                current_tags[key] = m.group(2).strip()
    if not streams:
        return None
    return {"format": fmt, "streams": streams}


def duration_seconds(file_path, ffmpeg_bin=None):
    info = probe(file_path, ffmpeg_bin, timeout=10)
    try:
        return float(((info or {}).get("format") or {}).get("duration") or 0) or None
    except (TypeError, ValueError):
        return None
