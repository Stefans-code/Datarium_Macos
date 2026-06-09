import os
import re
import sys
import hashlib
import base64
from io import BytesIO
from PIL import Image, ExifTags
try:
    import importlib
    pillow_heif = importlib.import_module("pillow_heif")
    pillow_heif.register_heif_opener()
except ImportError:
    pass
from huggingface_hub import hf_hub_download

class AIEngine:
    def __init__(self):
        self.llm = None
        self.is_vision = False
        self.hardware_info = "CPU"
        
        # --- Configurazione modelli ARGUS: vedi self.PROFILES qui sotto ---
        
        # ==========================================================
        #  ARGUS - modelli rinominati (Apache 2.0; vedi NOTICE.txt accanto ai modelli).
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
            if system == "Windows":
                base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
                path = os.path.join(base, "Datarium", "models")
            elif system == "Darwin": # macOS
                path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium", "models")
            else:
                path = os.path.join(os.path.expanduser("~"), ".datarium", "models")
                
            if force_writable:
                os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            print(f"[AIEngine] Errore risoluzione directory modelli scrivibile: {e}")
            if force_writable:
                os.makedirs(exe_dir_models, exist_ok=True)
            return exe_dir_models

    def check_models_missing(self):
        """Manca qualcosa? False se almeno un profilo (slim/full) ha testo + visione + mmproj."""
        try:
            d = self.get_models_dir()
            if not d or not os.path.exists(d):
                return True
            for prof in self.PROFILES.values():
                t_ok = os.path.exists(os.path.join(d, prof["text"][2]))
                v_ok = os.path.exists(os.path.join(d, prof["vision"][2]))
                p_ok = os.path.exists(os.path.join(d, prof["mmproj"][2]))
                if t_ok and v_ok and p_ok:
                    return False  # almeno un profilo completo presente
            return True
        except Exception:
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

    def download_model_if_needed(self, vision_mode=True, progress_callback=None, quality="full"):
        """Scarica (se serve) e carica i modelli ARGUS del profilo scelto. Ritorna (ok, err_msg)."""
        try:
            prof = self.PROFILES["slim"] if quality == "slim" else self.PROFILES["full"]

            # Ogni voce = (repo, nome_originale_HF, nome_ARGUS_locale)
            tasks = [prof["text"]]
            if vision_mode:
                tasks.append(prof["vision"])
                tasks.append(prof["mmproj"])

            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            os.environ["HF_HUB_DISABLE_XET"] = "1"  # il backend Xet si impicca su alcune reti

            for repo, src_name, argus_name in tasks:
                final_dir = self.get_models_dir()
                if os.path.exists(os.path.join(final_dir, argus_name)):
                    continue  # gia' presente col nome Argus
                dl_dir = self.get_models_dir(force_writable=True)
                if progress_callback: progress_callback(f"Scaricamento {argus_name}...")
                try:
                    src_path = hf_hub_download(repo_id=repo, filename=src_name, local_dir=dl_dir)
                except Exception as e:
                    return False, f"Network Error: {str(e)}"
                # Rinomina il file scaricato col nome ARGUS
                dst_path = os.path.join(dl_dir, argus_name)
                try:
                    if os.path.abspath(src_path) != os.path.abspath(dst_path):
                        if os.path.exists(dst_path): os.remove(dst_path)
                        os.replace(src_path, dst_path)
                except Exception as e:
                    return False, f"Rename Error: {str(e)}"

            if progress_callback: progress_callback("Caricamento... Attendere.")

            # --- Caricamento effettivo ---
            try:
                import importlib
                Llama = importlib.import_module("llama_cpp").Llama

                n_threads = os.cpu_count() or 4
                final_dir = self.get_models_dir()
                t_path = os.path.join(final_dir, prof["text"][2])
                v_path = os.path.join(final_dir, prof["vision"][2])
                p_path = os.path.join(final_dir, prof["mmproj"][2])

                hw = self.detect_hardware()
                ngl = hw["n_gpu_layers"]
                cpu_label = f"CPU ({hw['cpu_cores']} core)"

                if vision_mode:
                    chat_handler = self._select_handler(prof["handler"], p_path)
                    try:
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=2048, n_threads=n_threads, n_gpu_layers=ngl, n_batch=512, verbose=False)
                        self.hardware_info = hw["label"]
                    except Exception:
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=1024, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = cpu_label
                    self.is_vision = True
                    self._active_handler = prof["handler"]
                else:
                    try:
                        self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=ngl, n_batch=512, verbose=False)
                        self.hardware_info = hw["label"]
                    except Exception:
                        self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = cpu_label
                    self.is_vision = False

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

    def extract_context(self, file_path, scan_sidecars=True):
        """Extracts a deep text summary or detailed image description with metadata fusion."""
        self.last_has_people = False
        ext = os.path.splitext(file_path)[1].lower()
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
        # 1. DOCUMENTI
        try:
            if ext == ".pdf":
                import importlib
                fitz = importlib.import_module("fitz")
                doc = fitz.open(file_path)
                text = ""
                for i in range(min(5, len(doc))):
                    text += doc[i].get_text()
                context_res = f"DOC_CONTENT: {text[:1200]}"
            
            elif ext in [".docx", ".doc"]:
                import docx
                doc = docx.Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs[:40]])
                context_res = f"DOC_CONTENT: {text[:1200]}"
                
            elif ext == ".txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    context_res = f"DOC_CONTENT: {f.read(1200)}"
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
                img.thumbnail((1008, 1008))
                buffered = BytesIO()
                img.save(buffered, format="JPEG", quality=85)
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
                
                response_text = response['choices'][0]['message']['content'].strip()
                context_res = f"IMAGE_DESC: {response_text}{meta_str}"
            except Exception as e:
                if metadata:
                    context_res = f"RAW_IMAGE_METADATA: {metadata}"
                else:
                    print(f"Vision error: {e}")

        # 3. VIDEO (Cinema / Video)
        if not context_res and ext in [
            ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".f4v", ".wmv", ".m4v", ".mpg", ".mpeg", ".m2v", ".3gp", ".3g2", 
            ".ts", ".mts", ".m2ts", ".vob", ".ogv", ".divx", ".asf",
            ".braw", ".r3d", ".ari", ".arx", ".mxf", ".cine", ".crm", ".mcw"
        ]:
            if metadata:
                context_res = f"VIDEO_METADATA: {metadata}"
            else:
                context_res = f"VIDEO_FILE: {os.path.basename(file_path)}"

        if context_res and sidecar_str:
            context_res += sidecar_str
        elif not context_res and sidecar_str:
            context_res = f"FILE_TRANSCRIBED: {os.path.basename(file_path)}{sidecar_str}"
            
        return context_res

    def identify_global_themes(self, all_contexts):
        """Brainstorming: Analyse all contexts to find macro-themes and sub-themes."""
        if not self.llm or not all_contexts: return "Generale, Varie"
        
        cleaned_contexts = []
        for c in all_contexts:
            if not c: continue
            for prefix in ["IMAGE_DESC: ", "DOC_CONTENT: ", "VIDEO_METADATA: ", "VIDEO_FILE: ", "RAW_IMAGE_METADATA: "]:
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
        summaries = "\n".join(c[:150] for c in sampled)
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
            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=100,
                temperature=0.5
            )
            return response['choices'][0]['message']['content'].strip()
        except Exception:
            return "Documentazione(Lavoro, Personale), Immagini(Viaggi, Natura), Archivio(Varie)"

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
                cn = re.sub(r'[^a-zA-Z0-9]', '', n.replace(' ', ''))
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
        for prefix in ["IMAGE_DESC: ", "DOC_CONTENT: ", "VIDEO_METADATA: ", "VIDEO_FILE: ", "RAW_IMAGE_METADATA: "]:
            if context.startswith(prefix):
                context = context[len(prefix):]
                break
            
        context_str = f"Descrizione: {context}" if context else ""
        taxo_str = f"Tassonomia consigliata: {taxonomy}" if taxonomy else ""
        
        # Rimosso qualsiasi elenco numerato per evitare il bug di "1_..._2_..._3_" dei modelli
        messages = [
            {"role": "system", "content": (
                "Sei un archivista esperto. Rinomina il file nel formato esatto: Categoria/Sottocategoria/Nome_Descrittivo\n"
                "Regole fondamentali:\n"
                "Il nome descrittivo deve essere in italiano ed estremamente specifico.\n"
                "Usa da 3 a 5 parole significative separate esclusivamente da trattini bassi (_) (esempio: Bambino_Camicia_Rossa_Soridente).\n"
                "Non usare elenchi numerati, preamboli o estensioni.\n"
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
            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=32,
                temperature=0.1
            )
            clean_path = response['choices'][0]['message']['content'].strip()
            
            # Final cleanup
            clean_path = clean_path.strip("'\" ").split('(')[0].split('\'')[0].split('"')[0].strip()
            
            # Normalizzazione degli slash (sostituzione di backslash e rimozione spazi intorno agli slash)
            clean_path = clean_path.replace('\\', '/')
            clean_path = re.sub(r'\s*/\s*', '/', clean_path)
            
            parts = [p.strip() for p in clean_path.split('/') if p.strip()]
            
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
                
            if subcat_override:
                parts[1] = subcat_override
                
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
            
            # Sanifica i caratteri consentiti preservando lo slash
            clean_path = re.sub(r'[^a-zA-Z0-9_/]', '', clean_path)
            
            if len(clean_path) < 3:
                clean_path = f"Generale/Varie/{os.path.splitext(original_name)[0]}"
                
            orig_ext = os.path.splitext(original_name)[1]
            return f"{category}/{clean_path}{orig_ext}"
        except Exception as e:
            return f"{category}/{original_name}"

    def get_album_name(self, context):
        """Generates a short, precise album/theme name (1-2 words in Italian) based on description."""
        if not self.llm or not context: return "Varie"
        
        # Pulizia prefissi dal contesto
        for prefix in ["IMAGE_DESC: ", "DOC_CONTENT: ", "VIDEO_METADATA: ", "VIDEO_FILE: ", "RAW_IMAGE_METADATA: "]:
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
            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=8,
                temperature=0.1
            )
            clean = response['choices'][0]['message']['content'].strip()
            
            # Rimuove prefisso "Tema:" o "Album:" qualora fosse ritornato dall'AI prima della sanificazione
            if clean.lower().startswith("tema:"):
                clean = clean[5:].strip()
            elif clean.lower().startswith("album:"):
                clean = clean[6:].strip()
                
            import re
            clean = re.sub(r'[^a-zA-Z0-9_ ]', '', clean).strip()
            
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
                buf = afile.read(65536)
                while len(buf) > 0:
                    hasher.update(buf); buf = afile.read(65536)
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
                
        # 3. Tentativo finale su Windows in posizioni comuni
        if os.name == "nt":
            common_paths = [
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                r"C:\ffmpeg\bin\ffmpeg.exe"
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

    def generate_proxy(self, video_path, output_dir, ffmpeg_path=None, progress_callback=None, resolution="540p", format_ext="mp4"):
        """
        Genera un proxy leggero H.264 da un video nella risoluzione e formato specificati.
        Ritorna (True, percorso_proxy) o (False, messaggio_errore).
        """
        import subprocess
        
        ok, executable = self.check_ffmpeg(ffmpeg_path)
        if not ok:
            return False, executable
            
        if not os.path.exists(video_path):
            return False, "Video sorgente non trovato."
            
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        proxy_path = os.path.join(output_dir, f"proxy_{base_name}.{format_ext}")
        
        # Se il proxy esiste già, non sovrascriverlo (ottimizzazione)
        if os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 0:
            return True, proxy_path
            
        # Mappa della risoluzione in larghezza per FFMPEG scale filter
        # scale=X:-2 garantisce larghezza X e altezza proporzionale pari (evitando errori ffmpeg per altezze dispari)
        res_map = {
            "1080p": "1920",
            "720p": "1280",
            "540p": "960",
            "480p": "854",
            "360p": "640"
        }
        width = res_map.get(resolution, "960")
        scale_filter = f"scale={width}:-2"
        
        # Comando FFMPEG per proxy leggero (H.264, audio AAC)
        cmd = [
            executable, "-y",
            "-i", video_path,
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-crf", "28",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "128k",
            proxy_path
        ]
        
        try:
            if progress_callback:
                progress_callback(f"Transcodifica in corso: {os.path.basename(video_path)}...")
            
            # Nascondiamo la finestra su Windows per non far apparire schermate nere CMD moleste
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE
                
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )
            
            # Attendiamo la fine del processo
            stdout, stderr = process.communicate()
            
            if process.returncode == 0 and os.path.exists(proxy_path):
                return True, proxy_path
            else:
                err_msg = stderr.decode('utf-8', errors='ignore') if stderr else "Errore generico FFMPEG"
                return False, f"FFMPEG fallito (codice {process.returncode}): {err_msg}"
        except Exception as e:
            return False, f"Eccezione durante transcodifica: {e}"

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


