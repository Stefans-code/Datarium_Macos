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
        
        # Default Text Model
        self.text_repo = "Qwen/Qwen2.5-3B-Instruct-GGUF"
        self.text_file = "documentatio.gguf"
        
        # Vision Model (LLaVa v1.5 7B - Second State Version)
        self.vision_repo = "second-state/Llava-v1.5-7B-GGUF"
        self.vision_file = "vision.gguf"
        self.vision_projector = "projector.gguf"
        
        # Rilevamento hardware GPU e CPU
        self.hardware_info = "CPU"
        self.gpu_detected, self.gpu_details = self.detect_gpu_hardware()
        
        self.llama_gpu_supported = False
        if sys.platform != "dummy_platform":
            try:
                import importlib
                llama_cpp = importlib.import_module("llama_cpp")
                self.llama_gpu_supported = getattr(llama_cpp, 'llama_supports_gpu_offload', lambda: False)()
            except ImportError:
                # Evita il type narrowing statico di Pylance
                self.llama_gpu_supported = os.environ.get("DATARIUM_FORCE_GPU") == "1"
            
        if self.gpu_detected and self.llama_gpu_supported:
            self.hardware_info = "GPU"
        else:
            self.hardware_info = "CPU"

    def detect_gpu_hardware(self):
        """
        Rileva le GPU disponibili nel sistema.
        Ritorna una tupla (gpu_detected, gpu_details)
        """
        import subprocess
        import platform
        
        gpu_detected = False
        gpu_details = []
        system = platform.system()
        
        try:
            if system == "Windows":
                # Esegui PowerShell per ottenere il nome del controller video (moderno e robusto)
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE
                try:
                    res = subprocess.run(
                        ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        startupinfo=startupinfo
                    )
                    if res.returncode == 0:
                        lines = [line.strip() for line in res.stdout.split('\n') if line.strip()]
                        for line in lines:
                            if any(x in line.upper() for x in ["NVIDIA", "AMD", "RADEON", "INTEL", "GEFORCE"]):
                                if "MICROSOFT" not in line.upper():
                                    gpu_detected = True
                                    gpu_details.append(line)
                except Exception as ps_err:
                    print(f"[AIEngine] Errore query PowerShell: {ps_err}")
                
                # Fallback a wmic se powershell non trova nulla o fallisce
                if not gpu_detected:
                    try:
                        res = subprocess.run(
                            ["wmic", "path", "win32_VideoController", "get", "name"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            startupinfo=startupinfo
                        )
                        if res.returncode == 0:
                            lines = [line.strip() for line in res.stdout.split('\n') if line.strip()]
                            # Salta l'header "Name"
                            for line in lines[1:]:
                                if any(x in line.upper() for x in ["NVIDIA", "AMD", "RADEON", "INTEL", "GEFORCE"]):
                                    if "MICROSOFT" not in line.upper():
                                        gpu_detected = True
                                        gpu_details.append(line)
                    except Exception as wmic_err:
                        print(f"[AIEngine] Errore query wmic: {wmic_err}")
            elif system == "Darwin": # macOS
                # Controlla se è Apple Silicon
                machine = platform.machine()
                if "arm" in machine.lower() or "aac" in machine.lower():
                    gpu_detected = True
                    gpu_details.append("Apple Silicon GPU")
                else:
                    # Esegui system_profiler
                    res = subprocess.run(
                        ["system_profiler", "SPDisplaysDataType"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    if res.returncode == 0:
                        for line in res.stdout.split('\n'):
                            if "Chipset Model:" in line:
                                name = line.split("Chipset Model:")[1].strip()
                                gpu_detected = True
                                gpu_details.append(name)
            else: # Linux / altro
                res = subprocess.run(
                    ["lspci"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                if res.returncode == 0:
                    for line in res.stdout.split('\n'):
                        if "VGA" in line or "3D" in line:
                            gpu_detected = True
                            gpu_details.append(line.split(":")[-1].strip())
        except Exception as e:
            print(f"[AIEngine] Errore durante il rilevamento hardware GPU: {e}")
            
        details_str = ", ".join(gpu_details) if gpu_details else "Nessuna"
        return gpu_detected, details_str
        
    def get_models_dir(self, force_writable=False, quality=None):
        """
        Ritorna la cartella dei modelli sul Desktop dell'utente.
        """
        home = os.path.expanduser("~")
        desktop = home
        for name in ["Desktop", "Scrivania", "Schreibtisch", "Escritorio", "Bureau"]:
            path = os.path.join(home, name)
            if os.path.exists(path):
                desktop = path
                break
                
        if quality == "slim":
            models_path = os.path.join(desktop, "documentatio_leggero")
        elif quality == "full":
            models_path = os.path.join(desktop, "documentatio_pesante")
        else:
            # Auto-rilevazione dinamica
            pesante = os.path.join(desktop, "documentatio_pesante")
            leggero = os.path.join(desktop, "documentatio_leggero")
            if os.path.exists(os.path.join(pesante, "documentatio.gguf")):
                models_path = pesante
            elif os.path.exists(os.path.join(leggero, "documentatio.gguf")):
                models_path = leggero
            else:
                models_path = pesante
                
        if force_writable:
            os.makedirs(models_path, exist_ok=True)
        return models_path

    def check_models_missing(self):
        """Controlla se i modelli esistono sul Desktop."""
        try:
            home = os.path.expanduser("~")
            desktop = home
            for name in ["Desktop", "Scrivania", "Schreibtisch", "Escritorio", "Bureau"]:
                path = os.path.join(home, name)
                if os.path.exists(path):
                    desktop = path
                    break
                    
            for folder in ["documentatio_leggero", "documentatio_pesante"]:
                path = os.path.join(desktop, folder)
                if os.path.exists(path):
                    t_ok = os.path.exists(os.path.join(path, "documentatio.gguf"))
                    v_ok = os.path.exists(os.path.join(path, "vision.gguf"))
                    p_ok = os.path.exists(os.path.join(path, "projector.gguf"))
                    if t_ok and v_ok and p_ok:
                        return False # Trovati!
            return True
        except:
            return True

    def download_model_if_needed(self, vision_mode=True, progress_callback=None, quality="full"):
        """Scarica i modelli necessari rinominandoli con nomi proprietari nel Desktop, e poi li carica."""
        import shutil
        try:
            download_dir = self.get_models_dir(force_writable=True, quality=quality)
            
            # (Repo, HF Name, Local Name)
            tasks = []
            if quality == "slim":
                tasks.append(("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q2_k.gguf", "documentatio.gguf"))
                if vision_mode:
                    tasks.append(("second-state/Llava-v1.5-7B-GGUF", "llava-v1.5-7b-Q2_K.gguf", "vision.gguf"))
                    tasks.append(("second-state/Llava-v1.5-7B-GGUF", "llava-v1.5-7b-mmproj-model-f16.gguf", "projector.gguf"))
            else:
                tasks.append(("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q8_0.gguf", "documentatio.gguf"))
                if vision_mode:
                    tasks.append(("second-state/Llava-v1.5-7B-GGUF", "llava-v1.5-7b-Q8_0.gguf", "vision.gguf"))
                    tasks.append(("second-state/Llava-v1.5-7B-GGUF", "llava-v1.5-7b-mmproj-model-f16.gguf", "projector.gguf"))

            for repo, hf_file, local_name in tasks:
                target_path = os.path.join(download_dir, local_name)
                
                # Se il file finale esiste già, salta il download
                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                    continue
                    
                if progress_callback: 
                    progress_callback(f"Scaricamento {local_name}...")
                    
                try:
                    import os as _os
                    _os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
                    temp_path = hf_hub_download(
                        repo_id=repo, 
                        filename=hf_file, 
                        cache_dir=download_dir, 
                        local_dir=download_dir, 
                        local_dir_use_symlinks=False
                    )
                    
                    # Rinomina al nome proprietario locale
                    if os.path.exists(temp_path) and temp_path != target_path:
                        if os.path.exists(target_path):
                            os.remove(target_path)
                        shutil.move(temp_path, target_path)
                except Exception as e:
                    return False, f"Network Error: {str(e)}"

            if progress_callback: progress_callback("Caricamento... Attendere.")
            
            # Caricamento effettivo: usiamo get_models_dir() che risolve il percorso migliore
            try:
                import importlib
                llama_cpp = importlib.import_module("llama_cpp")
                Llama = llama_cpp.Llama
                llama_chat_format = importlib.import_module("llama_cpp.llama_chat_format")
                Llava15ChatHandler = llama_chat_format.Llava15ChatHandler
                
                n_threads = os.cpu_count() or 4
                final_models_dir = self.get_models_dir()
                
                # Identifica i percorsi reali (main o slim)
                t_path = os.path.join(final_models_dir, self.text_file)
                v_path = os.path.join(final_models_dir, self.vision_file)
                p_path = os.path.join(final_models_dir, self.vision_projector)

                if vision_mode:
                    chat_handler = Llava15ChatHandler(clip_model_path=p_path)
                    loaded = False
                    if self.llama_gpu_supported:
                        # 1. Prova GPU Completa (30 layers)
                        try:
                            self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=2048, n_threads=n_threads, n_gpu_layers=30, n_batch=512, verbose=False)
                            self.hardware_info = "GPU"
                            loaded = True
                        except Exception as e_gpu:
                            print(f"[AIEngine] Caricamento GPU max fallito: {e_gpu}. Provo modalità combo...")
                            # 2. Provo Combo (15 layers)
                            try:
                                self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=2048, n_threads=n_threads, n_gpu_layers=15, n_batch=512, verbose=False)
                                self.hardware_info = "Both"
                                loaded = True
                            except Exception as e_combo:
                                print(f"[AIEngine] Caricamento GPU combo fallito: {e_combo}. Ripiego su CPU...")
                    
                    if not loaded:
                        # 3. CPU Fallback (0 layers)
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=1024, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = "CPU"
                    self.is_vision = True
                else:
                    loaded = False
                    if self.llama_gpu_supported:
                        # 1. Prova GPU Completa (30 layers)
                        try:
                            self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=30, n_batch=512, verbose=False)
                            self.hardware_info = "GPU"
                            loaded = True
                        except Exception as e_gpu:
                            print(f"[AIEngine] Caricamento GPU max fallito: {e_gpu}. Provo modalità combo...")
                            # 2. Provo Combo (15 layers)
                            try:
                                self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=15, n_batch=512, verbose=False)
                                self.hardware_info = "Both"
                                loaded = True
                            except Exception as e_combo:
                                print(f"[AIEngine] Caricamento GPU combo fallito: {e_combo}. Ripiego su CPU...")
                    
                    if not loaded:
                        # 3. CPU Fallback (0 layers)
                        self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = "CPU"
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
        except:
            pass
            
        # Fallback: aggiungi data di creazione/modifica del file se non trovata in EXIF
        if 'DateTimeOriginal' not in meta:
            try:
                import datetime
                mtime = os.path.getmtime(file_path)
                dt = datetime.datetime.fromtimestamp(mtime)
                meta['FileModificationDate'] = dt.strftime("%Y:%m:%d %H:%M:%S")
            except:
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
            
        summaries = "\n".join([c[:150] for c in cleaned_contexts if c][:40])
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
        except:
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
        except:
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
        except: return None

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
                    except:
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
                except:
                    pass
            elif r_type == 'Dimensione < (MB)':
                try:
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    if size_mb < float(r_val):
                        matched = True
                except:
                    pass
                    
            if matched:
                r_folder = r_folder.replace('\\', '/')
                # Pulisce slash doppi o in eccesso
                parts = [p.strip() for p in r_folder.split('/') if p.strip()]
                r_folder = '/'.join(parts)
                return f"{r_folder}/{original_name}"
                
        return None


