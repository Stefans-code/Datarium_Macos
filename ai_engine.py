import os
import re
import sys
import time
import json
import difflib
import tempfile
import hashlib
import base64
from io import BytesIO
from PIL import Image, ExifTags
Image.MAX_IMAGE_PIXELS = 500_000_000  # scansioni ad alta risoluzione (default PIL ~179M px)
try:
    import importlib
    pillow_heif = importlib.import_module("pillow_heif")
    pillow_heif.register_heif_opener()
except ImportError:
    pass
# --- Xet OFF: DEVE stare PRIMA dell'import di huggingface_hub ---
# huggingface_hub legge HF_HUB_DISABLE_XET all'import (constants.py -> is_xet_available()):
# impostarla dopo l'import NON ha effetto. Il backend Xet di HF "si impicca" su alcune reti
# sui file multi-GB; forziamo il download HTTP classico (che supporta il resume).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
from huggingface_hub import hf_hub_download
import threading

# Dimensioni approssimative (MB) dei file su Stegeno/Nexflamma_Models, solo per mostrare
# "fatti X/Y MB" nella UI durante il download (vedi _start_progress_monitor). Se HF cambia
# le dimensioni non e' un problema: e' solo un'etichetta informativa, non un controllo.
_MODEL_SIZE_HINTS_MB = {
    "Argus-Maior-text-Q4_K_M.gguf": 2100,
    "Argus-Maior-vision-Q4_K_M.gguf": 4680,
    "Argus-Maior-vision-mmproj.gguf": 1350,
    "Argus-Minor-text-Q2_K.gguf": 1380,
    "Argus-Minor-vision.gguf": 2840,
    "Argus-Minor-vision-mmproj.gguf": 910,
}


def _incomplete_bytes(dl_dir):
    """Somma i byte dei file .incomplete che huggingface_hub scrive durante il download
    (in <dl_dir>/.cache/huggingface/download/). Usata per mostrare progresso reale invece
    della barra "muta" (disabilitata sopra) e per capire se il CDN Xet-bridge si e' impuntato."""
    cache_dir = os.path.join(dl_dir, ".cache", "huggingface", "download")
    total = 0
    if os.path.isdir(cache_dir):
        for root, _dirs, files in os.walk(cache_dir):
            for fn in files:
                if fn.endswith(".incomplete"):
                    try:
                        total += os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        pass
    return total


def _start_progress_monitor(dl_dir, argus_name, expected_mb, progress_callback, stop_event):
    """Thread di sola lettura (non tocca il download in corso): ogni ~3s legge quanti byte
    sono stati scritti finora e aggiorna la UI con MB scaricati + velocita', cosi' l'utente
    vede che il download e' vivo anche quando il CDN Xet-bridge rallenta parecchio."""
    def _run():
        last_bytes, last_t = 0, time.time()
        while not stop_event.is_set():
            if stop_event.wait(3):
                break
            cur_bytes = _incomplete_bytes(dl_dir)
            now = time.time()
            speed_kbs = max(0, (cur_bytes - last_bytes) / max(now - last_t, 0.001) / 1024)
            cur_mb = cur_bytes / (1024 * 1024)
            if progress_callback:
                if expected_mb:
                    pct = min(100, (cur_mb / expected_mb) * 100) if expected_mb > 0 else 0
                    remaining_mb = max(0, expected_mb - cur_mb)
                    eta_s = int((remaining_mb * 1024) / speed_kbs) if speed_kbs > 0 else 0
                    eta_str = f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 60 else f"{eta_s}s"
                    progress_callback(
                        f"Scaricamento {argus_name}... {cur_mb:.0f}/{expected_mb:.0f} MB "
                        f"({speed_kbs:.0f} KB/s) - {pct:.0f}% - ETA {eta_str}"
                    )
                else:
                    progress_callback(f"Scaricamento {argus_name}... {cur_mb:.0f} MB ({speed_kbs:.0f} KB/s)")
            last_bytes, last_t = cur_bytes, now
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    return th


# ==========================================================================================
#  Downloader HTTP multi-connessione (Range) — aggirare il throttling del CDN di HuggingFace
# ==========================================================================================
# Perche' esiste: dal 2026 HF serve i GGUF tramite il backend Xet. Su parecchie reti il
# xet-bridge fa "trickle" (pochi KB/s per connessione) e un file da 2-5 GB sembra bloccato.
# Il throttling e' PER CONNESSIONE: aprendo piu' richieste Range in parallelo la banda
# aggregata torna normale. Qui sotto: N segmenti paralleli, ognuno su un file .partN che
# viene ripreso (resume) se il download si interrompe, poi i pezzi vengono concatenati.
# Se il server non supporta i Range si ricade su un singolo stream con resume, e se anche
# quello fallisce download_model_if_needed ritenta con hf_hub_download (vedi sotto).

_DL_CONNECTIONS = 4          # connessioni parallele per file
_DL_CHUNK = 1024 * 1024      # 1 MB per read()
_DL_SOCKET_TIMEOUT = 60      # secondi senza un solo byte prima di considerare morto il socket
_DL_UA = "Datarium/1.0 (+https://huggingface.co)"


def _hf_resolve_url(repo, filename):
    return "https://huggingface.co/" + repo + "/resolve/main/" + filename + "?download=true"


def _remote_file_info(url, timeout=30):
    """Ritorna (dimensione_byte, supporta_range). Non solleva: (0, False) se non si sa."""
    import urllib.request
    import system_actions
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _DL_UA})
        req.get_method = lambda: "HEAD"
        with urllib.request.urlopen(req, timeout=timeout, context=system_actions.https_context()) as resp:
            size = int(resp.headers.get("Content-Length") or 0)
            accepts = (resp.headers.get("Accept-Ranges") or "").lower()
            # HF espone la dimensione reale del file LFS anche quando Content-Length manca
            linked = resp.headers.get("X-Linked-Size")
            if not size and linked:
                size = int(linked)
        return size, ("bytes" in accepts)
    except Exception:
        return 0, False


def _part_path(dest_path, idx):
    return dest_path + ".part" + str(idx)


def _download_range(url, part_file, start, end, stop_event, errors, idx):
    """Scarica [start, end] (inclusi) in part_file, riprendendo da quanto gia' presente."""
    import urllib.request
    import system_actions
    ssl_ctx = system_actions.https_context()
    for attempt in range(1, 7):
        if stop_event.is_set():
            return
        have = os.path.getsize(part_file) if os.path.exists(part_file) else 0
        if have > (end - start + 1):
            # pezzo sporco da un run precedente: ributtalo via e riparti
            try:
                os.remove(part_file)
            except OSError:
                pass
            have = 0
        if start + have > end:
            return  # segmento gia' completo
        headers = {"User-Agent": _DL_UA, "Range": "bytes=" + str(start + have) + "-" + str(end)}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_DL_SOCKET_TIMEOUT, context=ssl_ctx) as resp:
                with open(part_file, "ab") as fh:
                    while not stop_event.is_set():
                        chunk = resp.read(_DL_CHUNK)
                        if not chunk:
                            break
                        fh.write(chunk)
            if os.path.getsize(part_file) >= (end - start + 1):
                return  # completo
            # stream chiuso prima del previsto: ritenta, il resume riparte da dove siamo
        except Exception as exc:
            errors[idx] = exc
        if attempt < 6 and not stop_event.is_set():
            time.sleep(min(2 * attempt, 10))
    if not stop_event.is_set():
        have = os.path.getsize(part_file) if os.path.exists(part_file) else 0
        if start + have <= end:
            errors[idx] = errors.get(idx) or IOError(
                "segmento " + str(idx) + " incompleto (" + str(have) + "/" + str(end - start + 1) + " byte)")


def _parts_bytes(dest_path, n_parts):
    total = 0
    for i in range(n_parts):
        try:
            total += os.path.getsize(_part_path(dest_path, i))
        except OSError:
            pass
    return total


def _download_parallel(url, dest_path, label, total_size, progress_callback, connections=_DL_CONNECTIONS):
    """Scarica url in dest_path con `connections` richieste Range parallele.
    Solleva un'eccezione se non ci riesce (il chiamante ricade su hf_hub_download)."""
    if total_size <= 0:
        raise IOError("dimensione remota sconosciuta")
    n = max(1, min(connections, 8))
    seg = total_size // n
    bounds = []
    for i in range(n):
        start = i * seg
        end = (total_size - 1) if i == n - 1 else (start + seg - 1)
        bounds.append((start, end))

    stop_event = threading.Event()
    errors = {}
    threads = []
    for i, (start, end) in enumerate(bounds):
        th = threading.Thread(target=_download_range,
                              args=(url, _part_path(dest_path, i), start, end, stop_event, errors, i),
                              daemon=True)
        th.start()
        threads.append(th)

    # progresso: somma dei .partN (nessuna interferenza col download, sola lettura)
    total_mb = total_size / (1024 * 1024)
    last_bytes, last_t = _parts_bytes(dest_path, n), time.time()
    try:
        while any(th.is_alive() for th in threads):
            time.sleep(2)
            cur = _parts_bytes(dest_path, n)
            now = time.time()
            speed = max(0, (cur - last_bytes) / max(now - last_t, 0.001) / 1024)
            if progress_callback:
                pct = (cur / total_size * 100) if total_size else 0
                remaining_bytes = max(0, total_size - cur)
                eta_s = int(remaining_bytes / (speed * 1024)) if speed > 0 else 0
                eta_str = f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 60 else f"{eta_s}s"
                progress_callback("Scaricamento " + label + "... " + str(int(cur / (1024 * 1024))) + "/"
                                  + str(int(total_mb)) + " MB (" + str(int(speed)) + " KB/s, "
                                  + str(n) + " connessioni) - " + f"{pct:.0f}%" + " - ETA " + eta_str)
            last_bytes, last_t = cur, now
    except BaseException:
        stop_event.set()   # interruzione dell'app: i .partN restano per il resume
        raise
    for th in threads:
        th.join(timeout=30)

    got = _parts_bytes(dest_path, n)
    if got < total_size:
        raise IOError("download incompleto: " + str(got) + "/" + str(total_size) + " byte"
                      + (" - " + str(list(errors.values())[0]) if errors else ""))

    # concatena i pezzi nel file finale, poi ripulisce
    if progress_callback:
        progress_callback("Finalizzazione " + label + "...")
    tmp_final = dest_path + ".merging"
    with open(tmp_final, "wb") as out:
        for i in range(n):
            with open(_part_path(dest_path, i), "rb") as pf:
                while True:
                    buf = pf.read(4 * 1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.replace(tmp_final, dest_path)
    for i in range(n):
        try:
            os.remove(_part_path(dest_path, i))
        except OSError:
            pass
    return dest_path


# Lettere accentate italiane (minuscole/maiuscole) da preservare quando si sanificano
# nomi di file/persone: prima venivano tutte cancellate (es. "Città" -> "Citt").
_IT_ACCENTS = "àèéìíîòóùúÀÈÉÌÍÎÒÓÙÚçÇ"


def _parse_taxonomy(taxonomy_str):
    """Converte 'Cat1(Sub1, Sub2), Cat2(Sub1)' in [(Cat1, [Sub1, Sub2]), (Cat2, [Sub1])].
    Tollerante a formati leggermente diversi restituiti dal LLM; non solleva mai."""
    result = []
    if not taxonomy_str:
        return result
    try:
        for chunk in re.findall(r'([^,()]+)\(([^)]*)\)', taxonomy_str):
            cat = chunk[0].strip()
            subs = [s.strip() for s in chunk[1].split(',') if s.strip()]
            if cat:
                result.append((cat, subs))
    except Exception:
        pass
    return result


class AIEngine:
    def __init__(self):
        self.llm = None
        self.is_vision = False
        self.hardware_info = "CPU"

        # Context window / troncamento documenti: adattivi alla qualita' installata
        # (impostati davvero in download_model_if_needed una volta noto il profilo).
        self._n_ctx = 2048
        self._doc_chunk_chars = 1200

        # --- Cache persistente descrizioni AI (per hash file) ---
        # Evita di ridescrivere con l'LLM un file gia' visto in una sessione precedente
        # (stesso identico contenuto, es. copie/backup). Solo per immagini/documenti:
        # per i video l'hash costringerebbe a leggere l'intero file (spesso GB) solo
        # per la cache, vanificando il risparmio.
        self._context_cache = {}
        self._context_cache_path = None
        self._context_cache_dirty = False
        self._CONTEXT_CACHE_MAX = 5000

        # --- Manifest checksum modelli (models_version.json) ---
        # None = non ancora interrogato in questa sessione; {} = interrogato ma
        # non raggiungibile (offline/errore): in quel caso il controllo di
        # integrita' viene saltato, non blocca mai l'utente.
        self._models_manifest = None

        # --- Configurazione modelli ARGUS: vedi self.PROFILES qui sotto ---
        
        # ==========================================================
        #  ARGUS - modelli rinominati
        #  Due PROFILI scelti in fase d'installazione: "slim" (Leggero/Minor) e "full" (Pesante/Maior).
        #  Ogni voce = (repo HuggingFace, nome file ORIGINALE da scaricare, nome ARGUS locale)
        # ==========================================================
        self.PROFILES = {
            # ARGUS MINOR - Leggero. Modelli ospitati su HuggingFace: Stegeno/Nexflamma_Models.
            "slim": {
                "text":   ("Stegeno/Nexflamma_Models", "Argus-Minor-text-Q2_K.gguf",     "Argus-Minor-text-Q2_K.gguf"),
                "vision": ("Stegeno/Nexflamma_Models", "Argus-Minor-vision.gguf",        "Argus-Minor-vision.gguf"),
                "mmproj": ("Stegeno/Nexflamma_Models", "Argus-Minor-vision-mmproj.gguf", "Argus-Minor-vision-mmproj.gguf"),
                "handler": "moondream",
            },
            # ARGUS MAIOR - Pesante. Modelli ospitati su HuggingFace: Stegeno/Nexflamma_Models.
            "full": {
                "text":   ("Stegeno/Nexflamma_Models", "Argus-Maior-text-Q4_K_M.gguf",   "Argus-Maior-text-Q4_K_M.gguf"),
                "vision": ("Stegeno/Nexflamma_Models", "Argus-Maior-vision-Q4_K_M.gguf", "Argus-Maior-vision-Q4_K_M.gguf"),
                "mmproj": ("Stegeno/Nexflamma_Models", "Argus-Maior-vision-mmproj.gguf", "Argus-Maior-vision-mmproj.gguf"),
                "handler": "qwen2.5-vl",
            },
        }
        # Attributi di compatibilita' (default = profilo "full" / Pesante)
        self.text_repo = self.PROFILES["full"]["text"][0]
        self.text_file = self.PROFILES["full"]["text"][2]
        self.vision_repo = self.PROFILES["full"]["vision"][0]
        self.vision_file = self.PROFILES["full"]["vision"][2]
        self.vision_projector = self.PROFILES["full"]["mmproj"][2]

        # Rilevamento hardware universale (CPU/GPU, multipiattaforma e multi-marca).
        # Eseguito una sola volta e messo in cache; alimenta anche l'etichetta delle Impostazioni.
        self._hw_info = None
        try:
            self.hardware_info = self.detect_hardware()["label"]
        except Exception:
            self.hardware_info = "CPU"
        
    def detect_hardware(self, force=False):
        """Rileva CPU e GPU in modo universale (Windows / Linux / macOS; NVIDIA / AMD / Intel / Apple)
        e decide la configurazione d'esecuzione migliore per llama.cpp.

        Logica di scelta:
          - usa la GPU solo se la libreria llama.cpp è compilata con un backend GPU
            (CUDA, ROCm, Metal, Vulkan...) E c'è una GPU "potente" (discreta o Apple Silicon);
          - le GPU integrate Intel di norma non battono la CPU per gli LLM, quindi si preferisce la CPU;
          - in ogni caso l'etichetta riflette ciò che viene REALMENTE usato.

        Il risultato è messo in cache: il rilevamento (subprocess) avviene una sola volta."""
        if self._hw_info is not None and not force:
            return self._hw_info

        import platform
        system = platform.system()
        machine = platform.machine().lower()
        cpu_cores = os.cpu_count() or 4

        info = {
            "os": system,
            "cpu_cores": cpu_cores,
            "gpus": [],
            "gpu_vendor": None,
            "lib_gpu_support": False,
            "use_gpu": False,
            "n_gpu_layers": 0,
            "label": f"CPU ({cpu_cores} core)",
        }

        # 1. La build di llama.cpp è in grado di scaricare layer sulla GPU?
        try:
            import importlib
            _llama = importlib.import_module("llama_cpp")
            if hasattr(_llama, "llama_supports_gpu_offload"):
                info["lib_gpu_support"] = bool(_llama.llama_supports_gpu_offload())
        except Exception:
            info["lib_gpu_support"] = False

        # 2. GPU fisicamente presenti (multipiattaforma, indipendente dalla marca)
        info["gpus"] = self._list_gpus(system)
        info["gpu_vendor"] = self._classify_vendor(info["gpus"])

        # Apple Silicon espone sempre una GPU integrata utilizzabile via Metal
        if system == "Darwin" and machine in ("arm64", "aarch64") and not info["gpu_vendor"]:
            info["gpu_vendor"] = "Apple"

        # 3. Decisione su cosa conviene davvero usare
        strong_gpu = info["gpu_vendor"] in ("NVIDIA", "AMD", "Apple")
        if info["lib_gpu_support"] and strong_gpu:
            info["use_gpu"] = True
            info["n_gpu_layers"] = -1  # offload completo: llama.cpp scarica tutti i layer possibili
            gpu_name = info["gpus"][0] if info["gpus"] else info["gpu_vendor"]
            info["label"] = f"GPU: {gpu_name}"
        else:
            info["use_gpu"] = False
            info["n_gpu_layers"] = 0
            if info["gpu_vendor"] and not info["lib_gpu_support"]:
                info["label"] = f"CPU ({cpu_cores} core) - GPU {info['gpu_vendor']} rilevata ma libreria CPU-only"
            elif info["gpu_vendor"] == "Intel":
                info["label"] = f"CPU ({cpu_cores} core) - GPU Intel integrata (CPU preferita)"
            else:
                info["label"] = f"CPU ({cpu_cores} core)"

        self._hw_info = info
        return info

    def _list_gpus(self, system):
        """Elenca i nomi delle GPU presenti, in modo multipiattaforma e indipendente dalla marca."""
        import subprocess
        gpus = []
        try:
            if system == "Windows":
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                    stderr=subprocess.DEVNULL, timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ).decode(errors="ignore")
                gpus = [ln.strip() for ln in out.splitlines() if ln.strip()]
            elif system == "Darwin":
                out = subprocess.check_output(
                    ["system_profiler", "SPDisplaysDataType"],
                    stderr=subprocess.DEVNULL, timeout=10
                ).decode(errors="ignore")
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("Chipset Model:"):
                        gpus.append(line.split(":", 1)[1].strip())
            else:  # Linux e Unix-like
                out = subprocess.check_output(
                    ["lspci"], stderr=subprocess.DEVNULL, timeout=8
                ).decode(errors="ignore")
                for line in out.splitlines():
                    if any(k in line for k in ("VGA compatible controller", "3D controller", "Display controller")):
                        gpus.append(line.split(":", 2)[-1].strip())
        except Exception:
            pass
        return gpus

    def _classify_vendor(self, gpus):
        """Determina la marca della GPU 'migliore' tra quelle rilevate.
        Preferenza alle GPU discrete potenti (NVIDIA > AMD > Apple) rispetto all'integrata Intel."""
        text = " ".join(gpus).lower()
        if any(k in text for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla", "titan")):
            return "NVIDIA"
        if any(k in text for k in ("radeon", "firepro", "amd ", " rx ")):
            return "AMD"
        if "apple" in text:
            return "Apple"
        if "intel" in text and any(k in text for k in ("arc", "iris", "uhd", "graphics")):
            return "Intel"
        return None

    def _user_models_dir(self):
        """Cartella modelli utente, sempre scrivibile (non la crea)."""
        import platform
        system = platform.system()
        if system == "Windows":
            base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
            return os.path.join(base, "Datarium", "models")
        if system == "Darwin":  # macOS
            return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium", "models")
        return os.path.join(os.path.expanduser("~"), ".datarium", "models")

    def get_models_dir(self, force_writable=False):
        """
        Ritorna la cartella dei modelli, provando prima accanto all'eseguibile (in sola lettura)
        e poi ripiegando su una cartella utente scrivibile (macOS/Windows) se necessario.
        """
        import platform
        system = platform.system()
        
        # 1. Se siamo in ambiente di sviluppo (non frozen), usiamo la cartella locale 'models'
        if not getattr(sys, 'frozen', False):
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
            if force_writable:
                os.makedirs(models_dir, exist_ok=True)
            return models_dir
            
        # 2. Se siamo in ambiente frozen (eseguibile pacchettizzato)
        # Controlliamo prima se i modelli sono presenti accanto all'eseguibile (es. Windows con Inno Setup)
        exe_dir_models = os.path.join(os.path.dirname(sys.executable), "models")
        
        # Se i modelli esistono già accanto all'eseguibile, usiamo quello (modalità lettura)
        if os.path.exists(exe_dir_models):
            # Se la cartella esiste, verifichiamo se non è richiesto forzatamente di scriverci
            if not force_writable:
                return exe_dir_models
                
        # 3. Altrimenti (es. macOS, o Windows se vogliamo scaricare un modello mancante),
        # usiamo una cartella utente scrivibile per non incorrere in PermissionError.
        try:
            path = self._user_models_dir()

            if force_writable:
                os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            print(f"[AIEngine] Errore risoluzione directory modelli scrivibile: {e}")
            if force_writable:
                os.makedirs(exe_dir_models, exist_ok=True)
            return exe_dir_models

    def get_model_dirs(self):
        """Tutte le cartelle in cui possono trovarsi i modelli, in ordine di preferenza:
        accanto all'eseguibile (installer Windows) e cartella utente scrivibile (download
        in-app). Serve perche' le due possono coesistere: se l'installer NON ha scaricato i
        modelli, l'app li mette nella cartella utente e da li' vanno anche riletti."""
        dirs = []
        primary = self.get_models_dir()      # senza effetti collaterali: non crea nulla
        if primary:
            dirs.append(primary)
        if getattr(sys, "frozen", False):
            exe_dir = os.path.join(os.path.dirname(sys.executable), "models")
            if exe_dir not in dirs:
                dirs.append(exe_dir)
            user_dir = self._user_models_dir()
            if user_dir and user_dir not in dirs:
                dirs.append(user_dir)
        return dirs

    def resolve_model_file(self, name):
        """Percorso del modello `name` cercandolo in tutte le cartelle candidate, o None."""
        for d in self.get_model_dirs():
            try:
                candidate = os.path.join(d, name)
                if os.path.exists(candidate):
                    return candidate
            except Exception:
                continue
        return None

    def _load_context_cache(self):
        """Carica (una sola volta) la cache persistente hash -> descrizione AI dalla
        cartella modelli scrivibile. Fallisce in silenzio: la cache e' un'ottimizzazione,
        non deve mai bloccare l'analisi."""
        if self._context_cache_path is not None:
            return  # gia' tentato in questa sessione
        try:
            self._context_cache_path = os.path.join(self.get_models_dir(force_writable=True), "context_cache.json")
            if os.path.exists(self._context_cache_path):
                with open(self._context_cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._context_cache = data
        except Exception:
            self._context_cache = {}

    def _save_context_cache(self):
        if not self._context_cache_dirty or not self._context_cache_path:
            return
        try:
            # Limite dimensione: tiene solo le voci piu' recenti (inserimento = fine dict)
            if len(self._context_cache) > self._CONTEXT_CACHE_MAX:
                keys = list(self._context_cache.keys())[-self._CONTEXT_CACHE_MAX:]
                self._context_cache = {k: self._context_cache[k] for k in keys}
            tmp_path = self._context_cache_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._context_cache, f)
            os.replace(tmp_path, self._context_cache_path)
            self._context_cache_dirty = False
        except Exception:
            pass

    def check_models_missing(self):
        """Manca qualcosa? False se almeno un profilo (slim/full) ha testo + visione + mmproj."""
        try:
            for prof in self.PROFILES.values():
                if (self._profile_text_present(prof)
                        and self.resolve_model_file(prof["vision"][2])
                        and self.resolve_model_file(prof["mmproj"][2])):
                    return False  # almeno un profilo completo presente
            return True
        except Exception:
            return True

    def get_installed_quality(self):
        """Rileva quale profilo e' GIA' installato nei modelli: 'full', 'slim' o None.
        Serve a usare SEMPRE il profilo scelto/installato senza passare da slim a full."""
        try:
            for q in ("full", "slim"):
                prof = self.PROFILES[q]
                if (self._profile_text_present(prof)
                        and self.resolve_model_file(prof["vision"][2])
                        and self.resolve_model_file(prof["mmproj"][2])):
                    return q
        except Exception:
            pass
        return None

    def _fetch_models_manifest(self):
        """
        Interroga models_version.json: checksum SHA-256 attesi per ciascun file
        modello, pubblicati separatamente dalla versione del software (i modelli
        possono cambiare senza una nuova release di Datarium). Il file vive sullo
        stesso sito di version.json.

        Fallisce in silenzio: se non e' raggiungibile (offline, DNS, server giu'),
        il controllo di integrita' viene semplicemente saltato per questa sessione
        e l'app si comporta come prima (nessun blocco per un problema di rete).
        """
        if self._models_manifest is not None:
            return self._models_manifest
        try:
            import urllib.request
            import system_actions
            req = urllib.request.Request("https://nexflamma.net/models_version.json", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5, context=system_actions.https_context()) as resp:
                data = json.loads(resp.read().decode())
            self._models_manifest = data.get("models", {}) if isinstance(data, dict) else {}
        except Exception:
            self._models_manifest = {}
        return self._models_manifest

    def _compute_file_sha256(self, path):
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _is_model_verified(self, path, expected_sha256, progress_callback=None):
        """
        Controlla che il file in `path` corrisponda a expected_sha256. Usa una
        cache su disco (un file '<modello>.verified.json' accanto al modello) per
        NON dover rileggere e hashare da capo file da 1-5 GB ad ogni avvio: la
        rilettura completa scatta solo se dimensione/data modifica del modello
        sono cambiate rispetto all'ultima verifica riuscita, o se non c'e' ancora
        una verifica in cache.

        expected_sha256 mancante (manifest irraggiungibile) => nessun controllo
        possibile, si considera valido (non blocca l'utente per un problema di rete).
        """
        if not expected_sha256:
            return True
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            return False

        marker_path = path + ".verified.json"
        try:
            if os.path.exists(marker_path):
                with open(marker_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if (cached.get("size") == size and cached.get("mtime") == mtime
                        and cached.get("sha256") == expected_sha256):
                    return True  # gia' verificato in passato, file non toccato da allora
        except Exception:
            pass

        if progress_callback:
            progress_callback(f"Verifica integrità {os.path.basename(path)}...")
        actual = self._compute_file_sha256(path)
        if not actual or actual.lower() != expected_sha256.lower():
            return False

        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump({"size": size, "mtime": mtime, "sha256": actual}, f)
        except Exception:
            pass
        return True

    def _select_handler(self, handler_name, clip_model_path):
        """Restituisce il chat handler di visione giusto per il profilo Argus."""
        import importlib
        fmt = importlib.import_module("llama_cpp.llama_chat_format")
        if handler_name == "moondream":
            return fmt.MoondreamChatHandler(clip_model_path=clip_model_path)
        if handler_name == "qwen2.5-vl":
            HandlerCls = (getattr(fmt, "Qwen25VLChatHandler", None)
                          or getattr(fmt, "Qwen2VLChatHandler", None))
            if HandlerCls is None:
                raise RuntimeError(
                    "Il profilo PESANTE (Argus Maior / Qwen2.5-VL) richiede una versione "
                    "recente di llama-cpp-python. Aggiorna la libreria oppure usa il profilo LEGGERO."
                )
            return HandlerCls(clip_model_path=clip_model_path)
        return fmt.Llava15ChatHandler(clip_model_path=clip_model_path) 

    def download_model_if_needed(self, vision_mode=True, progress_callback=None, quality=None):
        """Scarica (se serve) e carica i modelli ARGUS del profilo scelto. Ritorna (ok, err_msg).
        Se quality non e' specificata, usa il profilo GIA' installato: cosi' i servizi
        (Organizer/AutoTag) non passano mai da slim a full ne' riscaricano il modello sbagliato."""
        try:
            if quality not in ("full", "slim"):
                quality = self.get_installed_quality() or "full"
            prof = self.PROFILES["slim"] if quality == "slim" else self.PROFILES["full"]

            # Ogni voce = (repo, nome_originale_HF, nome_ARGUS_locale)
            tasks = [prof["text"]]
            if vision_mode:
                tasks.append(prof["vision"])
                tasks.append(prof["mmproj"])

            # Xet e progress-bar gia' disabilitati a livello di modulo (prima dell'import)

            manifest = self._fetch_models_manifest()

            for repo, src_name, argus_name in tasks:
                expected_sha = (manifest.get(argus_name) or {}).get("sha256")
                existing = self.resolve_model_file(argus_name)
                if existing:
                    if self._is_model_verified(existing, expected_sha, progress_callback):
                        continue  # gia' presente, integro e corrispondente al manifest
                    # Presente ma corrotto o sostituito da una versione diversa sul server:
                    # va ributtato via, altrimenti resterebbe per sempre "gia' presente".
                    if progress_callback:
                        progress_callback(f"{argus_name} non corrisponde alla versione attesa, riscarico...")
                    try:
                        os.remove(existing)
                    except Exception:
                        pass  # es. cartella accanto all'exe non scrivibile: si riscarica altrove
                dl_dir = self.get_models_dir(force_writable=True)
                if progress_callback: progress_callback(f"Scaricamento {argus_name}...")
                # Retry con backoff: hf_hub_download RIPRENDE (resume) i file .incomplete,
                # quindi ritentare e' economico e assorbe gli stalli del CDN Xet-bridge di HF.
                # In parallelo un thread di sola lettura mostra MB scaricati + velocita' reale,
                # cosi' l'utente vede che il download e' vivo anche se il CDN rallenta parecchio
                # (con file da 2-5 GB uno stallo/resume ogni 10s puo' apparire "bloccato" a lungo
                # anche se in realta' sta ancora avanzando, solo molto lentamente).
                expected_mb = _MODEL_SIZE_HINTS_MB.get(src_name)
                src_path = None
                last_err = None
                dst_path = os.path.join(dl_dir, argus_name)

                # --- Strada principale: download multi-connessione (Range) ---
                # Il throttling del CDN Xet e' per-connessione: 4 richieste Range parallele
                # riportano la banda a valori normali su file da 2-5 GB. I .partN sopravvivono
                # a una chiusura dell'app, quindi un riavvio RIPRENDE da dove era arrivato.
                url = _hf_resolve_url(repo, src_name)
                total_size, supports_range = _remote_file_info(url)
                if total_size > 0 and supports_range:
                    for attempt in range(1, 4):
                        try:
                            if progress_callback:
                                suffix = f" (tentativo {attempt}/3)" if attempt > 1 else ""
                                progress_callback(f"Scaricamento {argus_name}...{suffix}")
                            _download_parallel(url, dst_path, argus_name, total_size, progress_callback)
                            src_path = dst_path
                            last_err = None
                            break
                        except Exception as e:
                            last_err = e
                            if attempt < 3:
                                time.sleep(3 * attempt)
                    if src_path:
                        if expected_sha and not self._is_model_verified(dst_path, expected_sha, progress_callback):
                            try:
                                os.remove(dst_path)
                            except Exception:
                                pass
                            return False, f"Il file scaricato ({argus_name}) non corrisponde al checksum atteso: download corrotto."
                        continue  # file pronto, integro, e gia' col nome ARGUS: prossimo modello
                    if progress_callback:
                        progress_callback(f"Download veloce non riuscito, passo alla modalita' classica...")

                # --- Ripiego: hf_hub_download (piu' lento ma con la sua logica di resume) ---
                for attempt in range(1, 6):
                    stop_event = threading.Event()
                    monitor = _start_progress_monitor(dl_dir, argus_name, expected_mb, progress_callback, stop_event)
                    try:
                        if progress_callback and attempt > 1:
                            progress_callback(f"Scaricamento {argus_name}... (tentativo {attempt}/5)")
                        src_path = hf_hub_download(repo_id=repo, filename=src_name, local_dir=dl_dir)
                        last_err = None
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < 5:
                            time.sleep(3 * attempt)
                    finally:
                        stop_event.set()
                        monitor.join(timeout=1)
                if last_err is not None or src_path is None:
                    return False, f"Network Error: {str(last_err)}"
                # Rinomina il file scaricato col nome ARGUS
                try:
                    if os.path.abspath(src_path) != os.path.abspath(dst_path):
                        if os.path.exists(dst_path): os.remove(dst_path)
                        os.replace(src_path, dst_path)
                except Exception as e:
                    return False, f"Rename Error: {str(e)}"

                if expected_sha and not self._is_model_verified(dst_path, expected_sha, progress_callback):
                    try:
                        os.remove(dst_path)
                    except Exception:
                        pass
                    return False, f"Il file scaricato ({argus_name}) non corrisponde al checksum atteso: download corrotto."

            if progress_callback: progress_callback("Caricamento... Attendere.")

            # --- Caricamento effettivo ---
            try:
                import importlib
                Llama = importlib.import_module("llama_cpp").Llama

                n_threads = os.cpu_count() or 4
                final_dir = self.get_models_dir()
                t_path = self.resolve_model_file(prof["text"][2]) or os.path.join(final_dir, prof["text"][2])
                v_path = self.resolve_model_file(prof["vision"][2]) or os.path.join(final_dir, prof["vision"][2])
                p_path = self.resolve_model_file(prof["mmproj"][2]) or os.path.join(final_dir, prof["mmproj"][2])

                hw = self.detect_hardware()
                ngl = hw["n_gpu_layers"]
                cpu_label = f"CPU ({hw['cpu_cores']} core)"

                # Context window / troncamento documenti adattivi: il profilo "full" (Argus
                # Maior) gira su hardware piu' capace e beneficia di un contesto piu' ampio
                # (documenti piu' lunghi analizzati meglio); con GPU forte alziamo ulteriormente.
                # Prima erano fissi a 2048 (1024 in fallback CPU) per qualunque profilo/hardware.
                if quality == "full":
                    self._n_ctx = 8192 if hw["use_gpu"] else 4096
                    self._doc_chunk_chars = 6000 if hw["use_gpu"] else 3000
                else:
                    self._n_ctx = 4096 if hw["use_gpu"] else 2048
                    self._doc_chunk_chars = 3000 if hw["use_gpu"] else 1200
                fallback_ctx = max(1024, self._n_ctx // 2)

                if vision_mode:
                    chat_handler = self._select_handler(prof["handler"], p_path)
                    try:
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=self._n_ctx, n_threads=n_threads, n_gpu_layers=ngl, n_batch=512, verbose=False)
                        self.hardware_info = hw["label"]
                    except Exception:
                        self._n_ctx = fallback_ctx
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=self._n_ctx, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = cpu_label
                    self.is_vision = True
                    self._active_handler = prof["handler"]
                else:
                    try:
                        self.llm = Llama(model_path=t_path, n_ctx=self._n_ctx, n_threads=n_threads, n_gpu_layers=ngl, n_batch=512, verbose=False)
                        self.hardware_info = hw["label"]
                    except Exception:
                        self._n_ctx = fallback_ctx
                        self.llm = Llama(model_path=t_path, n_ctx=self._n_ctx, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = cpu_label
                    self.is_vision = False

                self._load_context_cache()
                return True, ""
            except Exception as le:
                return False, f"Load Error: {str(le)}"

        except Exception as e:
            return False, f"System Error: {str(e)}"

    def extract_metadata(self, file_path):
        """Estrae dati EXIF (Data, Luogo, Camera) dalle immagini."""
        meta = {}
        try:
            img = Image.open(file_path)
            exif_data = img._getexif()
            if exif_data:
                for tag, value in exif_data.items():
                    decoded = ExifTags.TAGS.get(tag, tag)
                    if decoded in ['DateTimeOriginal', 'Make', 'Model', 'Software']:
                        meta[decoded] = str(value)
        except Exception:
            pass
            
        # Fallback: aggiungi data di creazione/modifica del file se non trovata in EXIF
        if 'DateTimeOriginal' not in meta:
            try:
                import datetime
                mtime = os.path.getmtime(file_path)
                dt = datetime.datetime.fromtimestamp(mtime)
                meta['FileModificationDate'] = dt.strftime("%Y:%m:%d %H:%M:%S")
            except Exception:
                pass
        return meta

    _CACHEABLE_EXTS = {
        ".pdf", ".docx", ".doc", ".txt",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico", ".heic", ".heif",
        ".svg", ".avif", ".jxl", ".nef", ".nrw", ".cr2", ".cr3", ".crw", ".arw", ".srf", ".sr2", ".dng",
        ".raf", ".rw2", ".raw", ".orf", ".ori", ".rwl", ".pef", ".ptx", ".cap", ".iiq", ".eip", ".3fr",
        ".fff", ".dcr", ".kdc", ".dcs", ".drf", ".k25", ".mrw", ".srw", ".bay", ".x3f", ".erf", ".mef",
        ".mos", ".pxn", ".gpr", ".rwz", ".obm", ".qtk", ".rdc", ".mdc", ".psd", ".psb", ".ai", ".indd",
        ".cdr", ".xcf", ".afphoto", ".afdesign", ".afpub", ".sketch", ".fig", ".kra", ".clip", ".lip",
        ".pspimage", ".psp", ".qxp", ".dwg", ".dxf", ".eps", ".ps", ".obj", ".fbx", ".stl", ".blend",
        ".c4d", ".max", ".ma", ".mb", ".3ds", ".gltf", ".glb",
    }

    def _cache_key(self, file_path):
        """Chiave di cache leggera: hash del contenuto solo per estensioni "cacheabili"
        (documenti/immagini, tipicamente non enormi). I video ne restano fuori: leggerli
        per intero solo per la cache vanificherebbe il risparmio."""
        try:
            h = self.compute_file_hash(file_path, "MD5")
            return h
        except Exception:
            return None

    def _vision_describe_image(self, img):
        """Chiede al modello vision una descrizione dettagliata di una PIL.Image gia' aperta.
        Condivisa tra analisi foto e frame estratti dai video."""
        img = img.copy()
        img.thumbnail((1008, 1008))
        if img.mode in ("I;16", "I;16L", "I;16B", "I;16N", "I"):
            # 16 bit: riporta a 8 bit scalando (altrimenti convert("RGB") clippa tutto a bianco)
            try:
                img = img.point(lambda v: v * (1 / 256)).convert("L")
            except Exception:
                img = img.convert("L")
        elif img.mode == "F":
            img = img.convert("L")
        buffered = BytesIO()
        img.convert("RGB").save(buffered, format="JPEG", quality=85)
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{img_str}"

        # Prompt adattivo: Moondream rende meglio con richieste brevi,
        # Qwen2.5-VL/altri con istruzioni dettagliate.
        if getattr(self, "_active_handler", None) == "moondream":
            prompt_text = (
                "Describe this image in detail: main subjects, objects, people "
                "(clothing, actions), any visible text or logos, and the setting."
            )
        else:
            prompt_text = (
                "Describe this image with high precision. List:\n"
                "1) The main subject, objects, and people (specify their clothing, age, actions, or details),\n"
                "2) Any visible text, writing, or logos (read word-for-word),\n"
                "3) Setting and background.\n"
                "Be highly descriptive and precise."
            )

        response = self.llm.create_chat_completion(
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            max_tokens=150,
            temperature=0.1
        )
        return response['choices'][0]['message']['content'].strip()

    def _extract_video_frame(self, video_path):
        """Estrae un frame rappresentativo (10% della durata, mai oltre i primi 20s) come
        immagine JPEG temporanea via FFMPEG. Ritorna il percorso del frame o None se FFMPEG
        non e' disponibile o l'estrazione fallisce. Il chiamante deve rimuovere il file."""
        import subprocess
        ok, ffmpeg_bin = self.check_ffmpeg()
        if not ok:
            return None
        try:
            # Durata del video (per posizionare il frame al 10%, non sempre al frame 0
            # che spesso e' nero/titoli). Se ffprobe non e' disponibile o fallisce, ripiega su 1s.
            seek = "1.0"
            try:
                ffprobe_bin = ffmpeg_bin.replace("ffmpeg", "ffprobe")
                out = subprocess.check_output(
                    [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                    stderr=subprocess.DEVNULL, timeout=8
                ).decode(errors="ignore").strip()
                duration = float(out)
                if duration > 0:
                    seek = str(min(duration * 0.1, 20.0))
            except Exception:
                pass

            fd, frame_path = tempfile.mkstemp(suffix=".jpg", prefix="datarium_frame_")
            os.close(fd)
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            cmd = [ffmpeg_bin, "-y", "-ss", seek, "-i", video_path, "-frames:v", "1", "-q:v", "3", frame_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, startupinfo=startupinfo)
            if proc.returncode == 0 and os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
                return frame_path
            try:
                os.remove(frame_path)
            except OSError:
                pass
        except Exception:
            pass
        return None

    def extract_context(self, file_path, scan_sidecars=True):
        """Extracts a deep text summary or detailed image description with metadata fusion."""
        self.last_has_people = False
        ext = os.path.splitext(file_path)[1].lower()

        # --- Cache persistente: stesso file (stesso hash) gia' descritto in passato ---
        # (foto/documenti duplicati, o riesecuzione della stessa cartella). I video sono
        # esclusi apposta (vedi _cache_key). Se manca il file per hashing prosegue normale.
        cache_key = None
        if ext in self._CACHEABLE_EXTS:
            self._load_context_cache()
            cache_key = self._cache_key(file_path)
            if cache_key and cache_key in self._context_cache:
                return self._context_cache[cache_key]

        metadata = self.extract_metadata(file_path)
        meta_str = f" [Metadata: {metadata}]" if metadata else ""

        # Cerca trascrizioni sidecar (es. generate da Vocius)
        sidecar_str = ""
        if scan_sidecars:
            try:
                base_dir = os.path.dirname(file_path)
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                for s_ext in [".txt", ".srt", ".vtt", "_transcript.txt"]:
                    s_path = os.path.join(base_dir, base_name + s_ext)
                    if os.path.exists(s_path) and os.path.isfile(s_path):
                        with open(s_path, "r", encoding="utf-8", errors="ignore") as sf:
                            content = sf.read().strip()
                            if content:
                                if s_ext in [".srt", ".vtt"]:
                                    content = re.sub(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}', '', content)
                                    content = re.sub(r'^\d+\s*$', '', content, flags=re.MULTILINE)
                                    content = re.sub(r'\n+', '\n', content).strip()
                                sidecar_str = f" [Trascrizione Vocius: {content[:1000]}]"
                                break
            except Exception as se:
                print(f"[AIEngine] Errore scansione file sidecar: {se}")

        context_res = ""
        # 1. DOCUMENTI (troncamento adattivo: vedi self._doc_chunk_chars in download_model_if_needed)
        chunk = self._doc_chunk_chars
        try:
            if ext == ".pdf":
                import importlib
                fitz = importlib.import_module("fitz")
                doc = fitz.open(file_path)
                text = ""
                for i in range(min(5, len(doc))):
                    text += doc[i].get_text()
                    if len(text) >= chunk:
                        break
                context_res = f"DOC_CONTENT: {text[:chunk]}"

            elif ext in [".docx", ".doc"]:
                import docx
                doc = docx.Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs[:40]])
                context_res = f"DOC_CONTENT: {text[:chunk]}"

            elif ext == ".txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    context_res = f"DOC_CONTENT: {f.read(chunk)}"
        except Exception as e:
            print(f"Doc extraction error: {e}")

        # 2. IMMAGINI (Visione Profonda)
        if not context_res and ext in [
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico", ".heic", ".heif", ".svg", ".avif", ".jxl",
            ".nef", ".nrw", ".cr2", ".cr3", ".crw", ".arw", ".srf", ".sr2", ".dng", ".raf", ".rw2", ".raw", ".orf", ".ori", 
            ".rwl", ".pef", ".ptx", ".cap", ".iiq", ".eip", ".3fr", ".fff", ".dcr", ".kdc", ".dcs", ".drf", ".k25", ".mrw", 
            ".srw", ".bay", ".x3f", ".erf", ".mef", ".mos", ".pxn", ".gpr", ".rwz", ".obm", ".qtk", ".rdc", ".mdc",
            ".psd", ".psb", ".ai", ".indd", ".cdr", ".xcf", ".afphoto", ".afdesign", ".afpub", ".sketch", ".fig", ".kra", 
            ".clip", ".lip", ".pspimage", ".psp", ".qxp", ".dwg", ".dxf", ".eps", ".ps",
            ".obj", ".fbx", ".stl", ".blend", ".c4d", ".max", ".ma", ".mb", ".3ds", ".gltf", ".glb"
        ] and self.is_vision:
            try:
                img = Image.open(file_path)
                response_text = self._vision_describe_image(img)
                context_res = f"IMAGE_DESC: {response_text}{meta_str}"
            except Exception as e:
                if metadata:
                    context_res = f"RAW_IMAGE_METADATA: {metadata}"
                else:
                    print(f"Vision error: {e}")

        # 3. VIDEO (Cinema / Video)
        # Prima si limitava a metadata/nome file: ora, se il modello vision e' caricato ed
        # FFMPEG e' disponibile, estrae un frame rappresentativo (10% della durata) e lo
        # descrive esattamente come una foto, cosi' il tagging/naming riflette il CONTENUTO
        # del video e non solo i suoi metadata tecnici.
        if not context_res and ext in [
            ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".f4v", ".wmv", ".m4v", ".mpg", ".mpeg", ".m2v", ".3gp", ".3g2",
            ".ts", ".mts", ".m2ts", ".vob", ".ogv", ".divx", ".asf",
            ".braw", ".r3d", ".ari", ".arx", ".mxf", ".cine", ".crm", ".mcw"
        ]:
            frame_path = None
            if self.is_vision:
                try:
                    frame_path = self._extract_video_frame(file_path)
                    if frame_path:
                        img = Image.open(frame_path)
                        response_text = self._vision_describe_image(img)
                        context_res = f"VIDEO_DESC: {response_text}{meta_str}"
                except Exception as e:
                    print(f"Video vision error: {e}")
                finally:
                    if frame_path:
                        try:
                            os.remove(frame_path)
                        except OSError:
                            pass

            if not context_res:
                if metadata:
                    context_res = f"VIDEO_METADATA: {metadata}"
                else:
                    context_res = f"VIDEO_FILE: {os.path.basename(file_path)}"

        if context_res and sidecar_str:
            context_res += sidecar_str
        elif not context_res and sidecar_str:
            context_res = f"FILE_TRANSCRIBED: {os.path.basename(file_path)}{sidecar_str}"

        # Salva in cache (solo estensioni "cacheabili", vedi sopra)
        if cache_key and context_res:
            self._context_cache[cache_key] = context_res
            self._context_cache_dirty = True
            self._save_context_cache()

        return context_res

    def _profile_text_present(self, prof):
        """True se il modello di testo del profilo c'e' (anche col vecchio nome Minor Q2_K)."""
        return bool(self.resolve_model_file(prof["text"][2])
                    or (prof.get("text_legacy") and self.resolve_model_file(prof["text_legacy"])))

    # Grammatiche GBNF: il modello (3B) puo' produrre SOLO testo nel formato atteso. Niente piu'
    # spiegazioni, virgolette, elenchi numerati o percorsi a meta'. Se la libreria non le
    # supporta, _chat ripiega automaticamente sulla generazione libera.
    _GBNF_WORD = "[A-Za-z0-9\u00e0\u00e8\u00e9\u00ec\u00ed\u00ee\u00f2\u00f3\u00f9\u00fa\u00c0\u00c8\u00c9\u00cc\u00cd\u00ce\u00d2\u00d3\u00d9\u00da\u00e7\u00c7]"
    _GBNF_PATH = 'root ::= seg "/" seg "/" seg\nseg ::= word ("_" word)*\nword ::= ' + _GBNF_WORD + '+\n'
    _GBNF_FOLDER = 'root ::= seg "/" seg\nseg ::= word ("_" word)*\nword ::= ' + _GBNF_WORD + '+\n'
    _GBNF_TAXO = ('root ::= item (", " item)*\nitem ::= name "(" name (", " name)* ")"\n'
                  'name ::= [A-Za-z0-9_ \u00e0\u00e8\u00e9\u00ec\u00f2\u00f9\u00c0\u00c8\u00c9\u00cc\u00d2\u00d9]+\n')
    _GBNF_ALBUM = 'root ::= word (" " word)?\nword ::= ' + _GBNF_WORD + '+\n'

    def _chat(self, llm, messages, max_tokens, temperature, grammar=None):
        """create_chat_completion con grammatica opzionale; se la grammatica non e' supportata
        o fallisce, riprova senza (mai peggio di prima)."""
        kwargs = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if grammar:
            try:
                cache = self.__dict__.setdefault("_grammar_cache", {})
                if grammar not in cache:
                    from llama_cpp import LlamaGrammar
                    cache[grammar] = LlamaGrammar.from_string(grammar, verbose=False)
                kwargs["grammar"] = cache[grammar]
            except Exception as e:
                print(f"[AIEngine] Grammatica non disponibile ({e}): generazione libera")
        try:
            return llm.create_chat_completion(**kwargs)
        except Exception as e:
            if "grammar" in kwargs:
                print(f"[AIEngine] Errore con grammatica ({e}): ritento senza")
                kwargs.pop("grammar")
                return llm.create_chat_completion(**kwargs)
            raise

    def _naming_llm(self):
        """Modello da usare per i compiti di SOLO TESTO (tassonomia, nomi, album).
        Il profilo leggero carica per le foto Moondream: un captioner, con un template di
        chat pensato per descrivere immagini, che segue male le istruzioni testuali. In quel
        caso si carica (una volta) il modello di testo Qwen2.5-3B e si usa quello.
        Il profilo Pesante usa gia' Qwen2.5-VL, valido anche per il testo."""
        if not (self.is_vision and getattr(self, "_active_handler", None) == "moondream"):
            return self.llm
        cached = getattr(self, "_text_llm", None)
        if cached is not None:
            return cached
        if getattr(self, "_text_llm_failed", False):
            return self.llm
        try:
            import importlib
            Llama = importlib.import_module("llama_cpp").Llama
            prof = self.PROFILES["slim"]
            t_path = (self.resolve_model_file(prof["text"][2])
                      or (prof.get("text_legacy") and self.resolve_model_file(prof["text_legacy"])))
            if not t_path:
                self._text_llm_failed = True
                return self.llm
            hw = self.detect_hardware()
            n_threads = os.cpu_count() or 4
            try:
                self._text_llm = Llama(model_path=t_path, n_ctx=self._n_ctx, n_threads=n_threads,
                                       n_gpu_layers=hw["n_gpu_layers"], n_batch=512, verbose=False)
            except Exception:
                self._text_llm = Llama(model_path=t_path, n_ctx=self._n_ctx, n_threads=n_threads,
                                       n_gpu_layers=0, n_batch=512, verbose=False)
            return self._text_llm
        except Exception as e:
            print(f"[AIEngine] Modello di testo dedicato non caricabile ({e}): uso il modello visione")
            self._text_llm_failed = True
            return self.llm

    _FALLBACK_TAXONOMY = "Documentazione(Lavoro, Personale), Immagini(Viaggi, Natura), Archivio(Varie)"

    def identify_global_themes(self, all_contexts):
        """Brainstorming: Analyse all contexts to find macro-themes and sub-themes."""
        if not self.llm or not all_contexts: return "Generale, Varie"
        
        cleaned_contexts = []
        for c in all_contexts:
            if not c: continue
            for prefix in ["IMAGE_DESC: ", "VIDEO_DESC: ", "DOC_CONTENT: ", "VIDEO_METADATA: ", "VIDEO_FILE: ", "RAW_IMAGE_METADATA: "]:
                if c.startswith(prefix):
                    c = c[len(prefix):]
                    break
            cleaned_contexts.append(c)
            
        non_empty = [c for c in cleaned_contexts if c]
        if len(non_empty) > 40:
            # Campionamento distribuito sull'intera lista (non solo i primi 40) così la
            # tassonomia è rappresentativa di tutta la cartella, non solo dei file iniziali.
            step = len(non_empty) / 40.0
            sampled = [non_empty[int(i * step)] for i in range(40)]
        else:
            sampled = non_empty
        # Budget in caratteri: 40 descrizioni x 150 char sforavano n_ctx=2048 (italiano ~2.2
        # char/token). llama.cpp allora solleva un errore e finiva sempre nella tassonomia di
        # ripiego generica, che poi _snap_to_taxonomy imponeva a tutte le cartelle.
        char_budget = max(600, int(getattr(self, "_n_ctx", 2048) * 2.2) - 900)
        per_item = max(40, min(150, char_budget // max(1, len(sampled))))
        summaries = "\n".join(c[:per_item] for c in sampled)
        if not summaries: return "Varie"
        
        messages = [
            {"role": "system", "content": (
                "Analyze these file descriptions and create a 2-level hierarchical taxonomy in Italian (Category > Subcategory).\n"
                "Identify 5 main Categories and for each, 1-2 Subcategories.\n"
                "Format: Category1(Sub1, Sub2), Category2(Sub1)... Only return the taxonomy words."
            )},
            {"role": "user", "content": f"Files to analyze:\n{summaries}"}
        ]
        
        try:
            response = self._chat(self._naming_llm(), messages, max_tokens=100, temperature=0.2, grammar=self._GBNF_TAXO)
            return response['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[AIEngine] Tassonomia globale fallita ({e}): uso la tassonomia di ripiego")
            return self._FALLBACK_TAXONOMY

    def _snap_to_taxonomy(self, parts, taxonomy):
        """Corregge piccole variazioni/instabilita' del LLM tra file simili (es. 'Documento'
        vs 'Documenti', 'Viaggio' vs 'Viaggi') agganciando categoria/sottocategoria al nome
        piu' vicino gia' presente nella tassonomia globale, cosi' non nascono cartelle
        duplicate quasi-identiche per lo stesso concetto. Non tocca 'parts' se non trova un
        match sufficientemente vicino (soglia 0.72) o se manca la tassonomia."""
        if taxonomy == self._FALLBACK_TAXONOMY:
            return parts  # tassonomia generica di ripiego: agganciarvi le cartelle le peggiora
        taxo = _parse_taxonomy(taxonomy)
        if not taxo or len(parts) < 2:
            return parts
        categories = [c for c, _ in taxo]
        cat_match = difflib.get_close_matches(parts[0], categories, n=1, cutoff=0.72)
        if cat_match:
            matched_cat = cat_match[0]
            parts[0] = matched_cat
            subs = next((s for c, s in taxo if c == matched_cat), [])
            if subs and parts[1] not in ("Persone_Identificate",):
                sub_match = difflib.get_close_matches(parts[1], subs, n=1, cutoff=0.72)
                if sub_match:
                    parts[1] = sub_match[0]
        return parts

    # Parole "vuote" tipiche dei nomi generati da camera/telefono/screenshot: un nome fatto
    # solo di queste NON e' descrittivo e va rinominato.
    _GENERIC_NAME_WORDS = frozenset([
        "img", "dsc", "dscn", "dscf", "mvi", "vid", "pxl", "gopr", "screenshot", "schermata", "whatsapp",
        "image", "immagine", "video", "scan", "scansione", "foto", "photo", "picture", "untitled",
        "senza", "titolo", "copy", "copia", "documento", "document", "nuovo", "new", "file", "download",
        "mov", "mp4", "clip", "audio", "recording", "registrazione", "alle", "at", "del", "the",
    ])

    def _is_descriptive_name(self, original_name):
        """True se il nome originale gia' descrive il contenuto (es. 'Pubblicazioni film 1973 -
        Il Tempo 14 febbraio 1973 A'): in quel caso va conservato, non sostituito da un nome
        inventato dall'AI (che perdeva lettere/numeri di pagina e creava nomi quasi uguali)."""
        stem = os.path.splitext(original_name)[0]
        words = [w for w in re.split(r'[^A-Za-z' + _IT_ACCENTS + r']+', stem) if len(w) >= 3]
        meaningful = [w for w in words if w.lower() not in self._GENERIC_NAME_WORDS]
        return len(meaningful) >= 2

    def get_smart_name(self, original_name, category, context="", taxonomy=""):
        """Generates a smart name using deep context and hierarchical taxonomy."""
        if not self.llm: return f"{category}/{original_name}"
        
        people_prefix = ""
        subcat_override = None
        
        # 1. Analisi persone identificate dall'utente
        if "Persone identificate dall'utente: " in context:
            user_identified = context.split("Persone identificate dall'utente: ")[-1].strip()
            names_list = [n.strip() for n in user_identified.split(',') if n.strip()]
            
            clean_names = []
            for n in names_list:
                cn = re.sub(r'[^a-zA-Z0-9' + _IT_ACCENTS + r']', '', n.replace(' ', ''))
                if cn: clean_names.append(cn)
                
            if len(clean_names) == 1:
                people_prefix = f"Foto_di_{clean_names[0]}_"
            elif len(clean_names) > 0:
                if len(clean_names) <= 3:
                    people_prefix = f"Foto_di_Gruppo_{'_'.join(clean_names)}_"
                else:
                    initials = "".join([n[0].upper() for n in clean_names])
                    people_prefix = f"Foto_di_Gruppo_{initials}_"
            
            subcat_override = "Persone_Identificate"
            # Pulizia contesto per non confondere l'AI
            context = context.split("Persone identificate dall'utente: ")[0].strip()

        # Pulizia prefissi tecnici dal contesto per non confondere il modello
        for prefix in ["IMAGE_DESC: ", "VIDEO_DESC: ", "DOC_CONTENT: ", "VIDEO_METADATA: ", "VIDEO_FILE: ", "RAW_IMAGE_METADATA: "]:
            if context.startswith(prefix):
                context = context[len(prefix):]
                break

        # Nome originale gia' descrittivo (e conservato): al modello si chiede SOLO la cartella
        # (Categoria/Sottocategoria). Compito piu' corto e semplice = meno errori e meno
        # invenzioni, importante con il modello leggero a 2 bit.
        folders_only = bool(not people_prefix and getattr(self, "keep_descriptive_names", True)
                            and self._is_descriptive_name(original_name))

        context_str = f"Descrizione: {context}" if context else ""
        taxo_str = f"Tassonomia consigliata: {taxonomy}" if taxonomy else ""
        
        # Rimosso qualsiasi elenco numerato per evitare il bug di "1_..._2_..._3_" dei modelli
        messages = [
            {"role": "system", "content": (
                "Sei un archivista esperto. Rinomina il file nel formato esatto: Categoria/Sottocategoria/Nome_Descrittivo\n"
                "Regole fondamentali:\n"
                "Il nome descrittivo deve essere in italiano ed estremamente specifico.\n"
                "Usa da 3 a 5 parole significative separate esclusivamente da trattini bassi (_) (esempio: Bambino_Camicia_Rossa_Sorridente).\n"
                "Se e' presente una tassonomia consigliata, riusa le sue Categorie e Sottocategorie invece di inventarne di nuove.\n"
                "Non usare elenchi numerati, preamboli o estensioni.\n"
                "Esempi:\n"
                "Descrizione: un gatto grigio dorme su un divano -> Animali/Gatti/Gatto_Grigio_Dorme_Divano\n"
                "Descrizione: fattura di Enel Energia di marzo 2023 -> Documenti/Fatture/Fattura_Enel_Energia_Marzo_2023\n"
                "Descrizione: pagina di giornale del 1973 su un processo -> Archivio/Giornali/Articolo_Processo_1973\n"
                "Rispondi SOLO ed ESCLUSIVAMENTE con la stringa Categoria/Sottocategoria/Nome."
            )},
            {"role": "user", "content": (
                f"Original Name: {original_name}\n"
                f"File Type: {category}\n"
                f"{context_str}\n"
                f"{taxo_str}\n\n"
                "Nuovo percorso completo (Categoria/Sottocategoria/Nome_Descrittivo):"
            )}
        ]
        
        try:
            if folders_only:
                messages = [
                    {"role": "system", "content": (
                        "Sei un archivista esperto. Scegli la cartella in cui archiviare il file, nel formato esatto: Categoria/Sottocategoria\n"
                        "Categoria e Sottocategoria: una o due parole italiane, separate da trattini bassi (_) se sono due.\n"
                        "Se e' presente una tassonomia consigliata, riusa le sue Categorie e Sottocategorie invece di inventarne di nuove.\n"
                        "Esempi:\n"
                        "File: Fattura Enel marzo 2023 -> Documenti/Fatture\n"
                        "File: Pubblicazioni film 1973 Il Tempo articolo -> Archivio/Giornali\n"
                        "File: Intervista regista Roma 2019 -> Interviste/Registi\n"
                        "Rispondi SOLO con la stringa Categoria/Sottocategoria."
                    )},
                    {"role": "user", "content": (
                        f"File: {os.path.splitext(original_name)[0]}\n"
                        f"Tipo: {category}\n"
                        f"{context_str}\n"
                        f"{taxo_str}\n\n"
                        "Cartella (Categoria/Sottocategoria):"
                    )}
                ]
            response = self._chat(self._naming_llm(), messages,
                                  max_tokens=(32 if folders_only else 64), temperature=0.1,
                                  grammar=(self._GBNF_FOLDER if folders_only else self._GBNF_PATH))
            clean_path = response['choices'][0]['message']['content'].strip()
            
            # Final cleanup
            first_line = next((ln for ln in clean_path.splitlines() if ln.strip()), "")
            clean_path = first_line.strip("'\" `").split('(')[0].strip()
            clean_path = clean_path.replace("'", "_").replace("\u2019", "_").replace('"', "")
            
            # Normalizzazione degli slash (sostituzione di backslash e rimozione spazi intorno agli slash)
            clean_path = clean_path.replace('\\', '/')
            clean_path = re.sub(r'\s*/\s*', '/', clean_path)
            
            parts = [p.strip() for p in clean_path.split('/') if p.strip()]
            if folders_only:
                # Il modello ha dato solo le cartelle: il nome file e' quello originale
                if not parts:
                    parts = ["Generale", "Varie"]
                elif len(parts) == 1:
                    parts = [parts[0], "Generale"]
                parts = parts[:2] + ["KEEPNAMEPLACEHOLDER"]
            
            # Meccanismo di fallback difensivo a 3 livelli (garantisce sempre la struttura corretta)
            if len(parts) == 1:
                subcat = "Varie"
                if taxonomy and ',' in taxonomy:
                    subcat = taxonomy.split(',')[0].strip()
                name_part = parts[0]
                parts = ["Generale", subcat, name_part]
            elif len(parts) == 2:
                parts = [parts[0], "Generale", parts[1]]
            elif len(parts) > 3:
                name_part = "_".join(parts[2:])
                parts = [parts[0], parts[1], name_part]
            elif len(parts) == 0:
                parts = ["Generale", "Varie", os.path.splitext(original_name)[0]]
                
            if not subcat_override:
                parts = self._snap_to_taxonomy(parts, taxonomy)

            if subcat_override:
                parts[1] = subcat_override

            orig_stem = os.path.splitext(original_name)[0]
            keep_name = (not people_prefix and getattr(self, "keep_descriptive_names", True)
                         and self._is_descriptive_name(original_name))
            if keep_name:
                # Nome originale gia' descrittivo: l'AI decide solo le cartelle
                parts[-1] = "KEEPNAMEPLACEHOLDER"
            else:
                # Nome generato dall'AI: aggiunge il numero finale dell'originale (IMG_0412 ->
                # ..._0412) cosi' file simili restano distinguibili e riconducibili all'originale.
                m = re.search(r'(\d{3,})\D*$', orig_stem)
                if m and m.group(1) not in parts[-1]:
                    parts[-1] = f"{parts[-1]}_{m.group(1)}"

            if people_prefix:
                parts[-1] = f"{people_prefix}{parts[-1]}"
            
            # Sostituzione degli spazi con trattino basso esclusivamente all'interno dei singoli componenti
            parts = [re.sub(r'\s+', '_', p) for p in parts]
            clean_path = '/'.join(parts)
            
            # Rimuove eventuali estensioni residue dall'output dell'AI
            while '.' in clean_path:
                idx = clean_path.rfind('.')
                if idx > len(clean_path)-6: clean_path = clean_path[:idx]
                else: break
            
            # Sanifica i caratteri consentiti preservando lo slash (e le accentate italiane:
            # prima "Città" diventava "Citt", ora resta leggibile)
            clean_path = re.sub(r'[^a-zA-Z0-9_/' + _IT_ACCENTS + r']', '', clean_path)
            
            if len(clean_path) < 3:
                clean_path = f"Generale/Varie/{os.path.splitext(original_name)[0]}"
                
            orig_ext = os.path.splitext(original_name)[1]
            if keep_name:
                clean_path = clean_path.replace("KEEPNAMEPLACEHOLDER", orig_stem)
            return f"{category}/{clean_path}{orig_ext}"
        except Exception as e:
            return f"{category}/{original_name}"

    def get_album_name(self, context):
        """Generates a short, precise album/theme name (1-2 words in Italian) based on description."""
        if not self.llm or not context: return "Varie"
        
        # Pulizia prefissi dal contesto
        for prefix in ["IMAGE_DESC: ", "VIDEO_DESC: ", "DOC_CONTENT: ", "VIDEO_METADATA: ", "VIDEO_FILE: ", "RAW_IMAGE_METADATA: "]:
            if context.startswith(prefix):
                context = context[len(prefix):]
                break
                
        messages = [
            {"role": "system", "content": (
                "Sei un assistente esperto. Ritorna solo un nome di album o tema estremamente sintetico (massimo 1 o 2 parole in ITALIANO) in base alla descrizione.\n"
                "Non usare elenchi numerati o spiegazioni. Rispondi solo con il nome del tema."
            )},
            {"role": "user", "content": f"Descrizione: {context}\nTema/Album:"}
        ]
        
        try:
            response = self._chat(self._naming_llm(), messages, max_tokens=16, temperature=0.1, grammar=self._GBNF_ALBUM)
            clean = response['choices'][0]['message']['content'].strip()
            
            # Rimuove prefisso "Tema:" o "Album:" qualora fosse ritornato dall'AI prima della sanificazione
            if clean.lower().startswith("tema:"):
                clean = clean[5:].strip()
            elif clean.lower().startswith("album:"):
                clean = clean[6:].strip()
                
            clean = re.sub(r'[^a-zA-Z0-9_ ' + _IT_ACCENTS + r']', '', clean).strip()
            
            # Forza il limite rigoroso di 1 o 2 parole al massimo in italiano
            words = clean.split()
            if len(words) > 2:
                clean = " ".join(words[:2])
                
            return clean.capitalize() if clean else "Varie"
        except Exception:
            return "Varie"

    def compute_file_hash(self, file_path, algo="MD5"):
        try:
            if algo == "MD5":
                hasher = hashlib.md5()
            elif algo == "SHA-1":
                hasher = hashlib.sha1()
            elif algo == "xxHash64":
                import importlib
                xxhash = importlib.import_module("xxhash")
                hasher = xxhash.xxh64()
            else:
                hasher = hashlib.sha256()
            with open(file_path, 'rb') as afile:
                buf = afile.read(4 * 1024 * 1024)
                while len(buf) > 0:
                    hasher.update(buf); buf = afile.read(4 * 1024 * 1024)
            return getattr(hasher, "hexdigest")()
        except Exception: return None

    def check_ffmpeg(self, custom_path=None):
        """
        Verifica la presenza di FFMPEG nel sistema.
        Ritorna (True, percorso) o (False, messaggio_errore).
        """
        import subprocess
        import shutil
        
        # 1. Se viene fornito un percorso personalizzato dall'utente
        if custom_path:
            custom_path = os.path.abspath(custom_path.strip())
            if os.path.exists(custom_path):
                # Se è una cartella che contiene ffmpeg.exe, proviamo a risolverlo
                if os.path.isdir(custom_path):
                    executable = os.path.join(custom_path, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
                else:
                    executable = custom_path
                    
                if os.path.exists(executable) and os.path.isfile(executable):
                    try:
                        res = subprocess.run([executable, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                        if res.returncode == 0:
                            return True, executable
                    except Exception as e:
                        return False, f"Errore esecuzione FFMPEG custom: {e}"
            return False, "Percorso FFMPEG non valido o inesistente."
            
        # 2. Altrimenti cerchiamo nel PATH di sistema
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            try:
                res = subprocess.run([ffmpeg_bin, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                if res.returncode == 0:
                    return True, ffmpeg_bin
            except Exception as e:
                return False, f"Errore esecuzione FFMPEG in PATH: {e}"
                
        # 3. Tentativo finale in posizioni comuni.
        # NB macOS/Linux: le app avviate da Finder/launcher NON ereditano il PATH della
        # shell (su macOS resta /usr/bin:/bin:/usr/sbin:/sbin), quindi shutil.which() non
        # vede ffmpeg installato con Homebrew/MacPorts anche quando c'e'.
        if os.name == "nt":
            common_paths = [
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                r"C:\ffmpeg\bin\ffmpeg.exe"
            ]
        else:
            common_paths = [
                "/opt/homebrew/bin/ffmpeg",   # macOS Apple Silicon (Homebrew)
                "/usr/local/bin/ffmpeg",      # macOS Intel (Homebrew) / build manuali
                "/opt/local/bin/ffmpeg",      # macOS MacPorts
                "/usr/bin/ffmpeg",            # Linux (apt/dnf/pacman)
                "/snap/bin/ffmpeg",           # Linux snap
                "/var/lib/flatpak/exports/bin/ffmpeg",
                os.path.expanduser("~/bin/ffmpeg"),
            ]
        for p in common_paths:
            if os.path.exists(p):
                try:
                    res = subprocess.run([p, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                    if res.returncode == 0:
                        return True, p
                except Exception:
                    pass
                        
        return False, "FFMPEG non trovato nel sistema. Configuralo nelle Impostazioni."

    # Profili proxy sul modello di DaVinci Resolve: formato (codec) + risoluzione relativa
    # all'originale. La chiave e' il testo mostrato nei menu delle Impostazioni.
    PROXY_RESOLUTIONS = {
        "Original": 1,
        "Half": 2,
        "Quarter": 4,
        "One-eighth": 8,
    }
    PROXY_FORMATS = ["DNxHR SQ (.mov)", "H.264 (.mp4)"]
    DEFAULT_PROXY_RESOLUTION = "Half"
    DEFAULT_PROXY_FORMAT = "H.264 (.mp4)"

    @classmethod
    def normalize_proxy_resolution(cls, value):
        """Riporta un valore (anche di versioni vecchie, es. '540p (960x540)') a una chiave valida."""
        v = str(value or "").strip().lower().replace("_", "-")
        for key in cls.PROXY_RESOLUTIONS:
            if v == key.lower() or v.startswith(key.lower() + " "):
                return key
        if v in ("1/2", "half"):
            return "Half"
        return cls.DEFAULT_PROXY_RESOLUTION

    @classmethod
    def normalize_proxy_format(cls, value):
        v = str(value or "").lower()
        if "dnx" in v:
            return "DNxHR SQ (.mov)"
        return cls.DEFAULT_PROXY_FORMAT

    def generate_proxy(self, video_path, output_dir, ffmpeg_path=None, progress_callback=None,
                       resolution="Half", format_key="H.264 (.mp4)"):
        """
        Genera un proxy da un video. resolution: Original/Half/Quarter/One-eighth (rispetto
        all'originale); format_key: 'DNxHR SQ (.mov)' oppure 'H.264 (.mp4)'.
        Ritorna (True, percorso_proxy) o (False, messaggio_errore).
        """
        import subprocess

        ok, executable = self.check_ffmpeg(ffmpeg_path)
        if not ok:
            return False, executable

        if not os.path.exists(video_path):
            return False, "Video sorgente non trovato."

        resolution = self.normalize_proxy_resolution(resolution)
        format_key = self.normalize_proxy_format(format_key)
        divisor = self.PROXY_RESOLUTIONS[resolution]
        is_dnx = format_key.startswith("DNxHR")
        ext = "mov" if is_dnx else "mp4"

        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        suffix = f"{resolution.lower()}_{'dnxhr' if is_dnx else 'h264'}"
        proxy_path = os.path.join(output_dir, f"proxy_{base_name}_{suffix}.{ext}")

        # Se il proxy esiste gia', non rigenerarlo
        if os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 0:
            return True, proxy_path

        # Dimensioni divise per il fattore e arrotondate a numeri pari (richiesto da H.264/yuv42x)
        scale_filter = f"scale=trunc(iw/{divisor}/2)*2:trunc(ih/{divisor}/2)*2"
        if is_dnx and divisor > 1:
            # DNxHR non accetta larghezze < 256: sotto quella soglia si ferma a 256 px
            scale_filter = f"scale=max(256\\,trunc(iw/{divisor}/2)*2):-2"

        if is_dnx:
            codec_args = ["-c:v", "dnxhd", "-profile:v", "dnxhr_sq", "-pix_fmt", "yuv422p",
                          "-c:a", "pcm_s16le"]
            muxer = "mov"
        else:
            codec_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
            muxer = "mp4"

        # Scrive su file temporaneo e rinomina a fine lavoro: un proxy interrotto non resta
        # a meta' sul disco e non viene scambiato per completo alla prossima esecuzione.
        tmp_path = proxy_path + ".part"
        cmd = [executable, "-y", "-nostdin", "-i", video_path,
               "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn",
               "-vf", scale_filter, *codec_args, "-f", muxer, tmp_path]

        try:
            if progress_callback:
                progress_callback(f"Transcodifica in corso: {os.path.basename(video_path)}...")

            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW su Windows
            process = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     creationflags=flags)
            if process.returncode == 0 and os.path.exists(tmp_path):
                os.replace(tmp_path, proxy_path)
                return True, proxy_path
            err_msg = process.stderr.decode('utf-8', errors='ignore')[-500:] if process.stderr else "Errore generico FFMPEG"
            return False, f"FFMPEG fallito (codice {process.returncode}): {err_msg}"
        except Exception as e:
            return False, f"Eccezione durante transcodifica: {e}"
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def apply_custom_rules(self, file_path, rules_list):
        """
        Applica una lista di regole personalizzate a un file.
        Ritorna il percorso di destinazione relativo (es. 'Foto/nome.jpg') se combacia, altrimenti None.
        """
        import os
        if not os.path.exists(file_path):
            return None
            
        original_name = os.path.basename(file_path)
        ext = os.path.splitext(original_name)[1].lower()
        name_no_ext = os.path.splitext(original_name)[0].lower()
        
        for rule in rules_list:
            r_type = rule.get('type')
            r_val = rule.get('value', '').strip()
            r_folder = rule.get('folder', '').strip()
            
            if not r_type or not r_folder:
                continue
                
            matched = False
            if r_type == 'Estensione':
                extensions = [e.strip().lower() for e in r_val.split(',') if e.strip()]
                # Supporta sia ".jpg" che "jpg"
                if ext in extensions or ext.replace('.', '') in extensions or ('.' + ext.replace('.', '')) in extensions:
                    matched = True
            elif r_type == 'Nome contiene':
                keywords = [k.strip().lower() for k in r_val.split(',') if k.strip()]
                if any(kw in name_no_ext for kw in keywords):
                    matched = True
            elif r_type == 'Dimensione > (MB)':
                try:
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    if size_mb > float(r_val):
                        matched = True
                except Exception:
                    pass
            elif r_type == 'Dimensione < (MB)':
                try:
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    if size_mb < float(r_val):
                        matched = True
                except Exception:
                    pass
                    
            if matched:
                r_folder = r_folder.replace('\\', '/')
                # Pulisce slash doppi o in eccesso
                parts = [p.strip() for p in r_folder.split('/') if p.strip()]
                r_folder = '/'.join(parts)
                return f"{r_folder}/{original_name}"
                
        return None


