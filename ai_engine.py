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

# Ottimizzazione SSL per macOS (Critico per il download dei modelli)
try:
    import certifi
    import platform
    if platform.system() == "Darwin":
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except:
    pass


class AIEngine:
    def __init__(self):
        self.llm = None
        self.is_vision = False
        self.hardware_info = "CPU"
        
        # Default Text Model
        self.text_repo = "Qwen/Qwen2.5-3B-Instruct-GGUF"
        self.text_file = "qwen2.5-3b-instruct-q4_k_m.gguf"
        
        # Vision Model (LLaVa v1.5 7B - Second State Version)
        self.vision_repo = "second-state/Llava-v1.5-7B-GGUF"
        self.vision_file = "llava-v1.5-7b-Q4_K_M.gguf"
        self.vision_projector = "llava-v1.5-7b-mmproj-model-f16.gguf"
        
    def get_models_dir(self, force_writable=False):
        """
        Ritorna la cartella dei modelli.
        - Su Windows (frozen): accanto all'exe
        - Su macOS: ~/Library/Application Support/Datarium/models
        """
        import platform
        system = platform.system()

        if system == "Darwin":
            # Percorso standard macOS per dati applicazione
            base = os.path.expanduser("~/Library/Application Support/Datarium")
            models_dir = os.path.join(base, "models")
        elif getattr(sys, 'frozen', False):
            # Percorso accanto all'exe
            models_dir = os.path.join(os.path.dirname(sys.executable), "models")
        else:
            models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

        if force_writable:
            os.makedirs(models_dir, exist_ok=True)
            
        return models_dir

    def check_models_missing(self):
        """Controlla se i modelli esistono nell'unico percorso supportato."""
        try:
            d = self.get_models_dir()
            if not d or not os.path.exists(d): 
                return True
            
            # Controllo incrociato: devono esserci il testo, la visione E il proiettore
            t_ok = os.path.exists(os.path.join(d, self.text_file)) or \
                   os.path.exists(os.path.join(d, "qwen2.5-3b-instruct-q2_k.gguf"))
            
            v_ok = os.path.exists(os.path.join(d, self.vision_file)) or \
                   os.path.exists(os.path.join(d, "llava-v1.5-7b-Q2_K.gguf"))
            
            p_ok = os.path.exists(os.path.join(d, self.vision_projector))
            
            if t_ok and v_ok and p_ok:
                return False # Trovati tutti!
            
            return True # Qualcosa manca
        except:
            return True

    def download_model_if_needed(self, vision_mode=True, progress_callback=None, quality="full"):
        """Ora ritorna (True/False, error_msg) per una gestione UI migliore."""
        try:
            models_dir = self.get_models_dir()
            
            tasks = []
            if quality == "slim":
                tasks.append((self.text_repo, "qwen2.5-3b-instruct-q2_k.gguf"))
                if vision_mode:
                    tasks.append((self.vision_repo, "llava-v1.5-7b-Q2_K.gguf"))
                    tasks.append((self.vision_repo, self.vision_projector))
            else:
                tasks.append((self.text_repo, self.text_file))
                if vision_mode:
                    tasks.append((self.vision_repo, self.vision_file))
                    tasks.append((self.vision_repo, self.vision_projector))

            for repo, filename in tasks:
                # Fallback slim names
                is_slim = False
                alt_filename = filename
                if "qwen" in filename.lower(): alt_filename = "qwen2.5-3b-instruct-q2_k.gguf"
                elif "llava" in filename and "v1.5-7b" in filename and "mmproj" not in filename: alt_filename = "llava-v1.5-7b-Q2_K.gguf"

                # Verifichiamo se il file esiste già nell'unica cartella modelli supportata
                current_dir = self.get_models_dir()
                path = os.path.join(current_dir, filename)
                alt_path = os.path.join(current_dir, alt_filename)

                if not os.path.exists(path) and not os.path.exists(alt_path):
                    # Se manca, scarichiamo nella cartella di installazione
                    download_dir = self.get_models_dir(force_writable=True)
                    target_path = os.path.join(download_dir, filename)
                    
                    if progress_callback: progress_callback(f"Scaricamento {filename}...")
                    try:
                        # Sopprimiamo le barre di progresso tramite env var (compatibile con TUTTE le versioni di huggingface_hub)
                        import os as _os
                        _os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
                        hf_hub_download(
                            repo_id=repo, 
                            filename=filename, 
                            cache_dir=download_dir, 
                            local_dir=download_dir, 
                            local_dir_use_symlinks=False
                        )
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
                if not os.path.exists(t_path): t_path = os.path.join(final_models_dir, "qwen2.5-3b-instruct-q2_k.gguf")
                
                v_path = os.path.join(final_models_dir, self.vision_file)
                if not os.path.exists(v_path): v_path = os.path.join(final_models_dir, "llava-v1.5-7b-Q2_K.gguf")
                
                p_path = os.path.join(final_models_dir, self.vision_projector)

                if vision_mode:
                    chat_handler = Llava15ChatHandler(clip_model_path=p_path)
                    try:
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=2048, n_threads=n_threads, n_gpu_layers=30, n_batch=512, verbose=False)
                        self.hardware_info = "GPU (Accelerata)"
                    except:
                        self.llm = Llama(model_path=v_path, chat_handler=chat_handler, n_ctx=1024, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = "CPU (Standard)"
                    self.is_vision = True
                else:
                    try:
                        self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=30, n_batch=512, verbose=False)
                        self.hardware_info = "GPU (Accelerata)"
                    except:
                        self.llm = Llama(model_path=t_path, n_ctx=2048, n_threads=n_threads, n_gpu_layers=0, n_batch=512, verbose=False)
                        self.hardware_info = "CPU (Standard)"
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

    def extract_context(self, file_path):
        """Extracts a deep text summary or detailed image description with metadata fusion."""
        self.last_has_people = False
        ext = os.path.splitext(file_path)[1].lower()
        metadata = self.extract_metadata(file_path)
        meta_str = f" [Metadata: {metadata}]" if metadata else ""
        
        # 1. DOCUMENTI
        try:
            if ext == ".pdf":
                import importlib
                fitz = importlib.import_module("fitz")
                doc = fitz.open(file_path)
                text = ""
                # Leggiamo più pagine per essere "più intelligenti"
                for i in range(min(5, len(doc))):
                    text += doc[i].get_text()
                return f"DOC_CONTENT: {text[:1200]}"
            
            elif ext in [".docx", ".doc"]:
                import docx
                doc = docx.Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs[:40]])
                return f"DOC_CONTENT: {text[:1200]}"
                
            elif ext == ".txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f"DOC_CONTENT: {f.read(1200)}"
        except Exception as e: print(f"Doc extraction error: {e}")

        # 2. IMMAGINI (Visione Profonda)
        # Supporta tutti i formati fotografici standard, RAW avanzati, output software professionali e 3D
        if ext in [
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
                img.thumbnail((1008, 1008)) # Alta risoluzione per preservare testo e dettagli
                buffered = BytesIO()
                img.save(buffered, format="JPEG", quality=85)
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                data_url = f"data:image/jpeg;base64,{img_str}"
                
                # Prompt intelligente che fonde Visione e Metadati con identificazione persone
                hint = f"Note: This file was created on {metadata.get('DateTimeOriginal', 'unknown date')}." if metadata else ""
                
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
                return f"IMAGE_DESC: {response_text}{meta_str}"
            except Exception as e:
                # Fallback se Pillow fallisce ad aprire il file RAW (es. .NEF, .CR2 senza codec specifici)
                if metadata:
                    return f"RAW_IMAGE_METADATA: {metadata}"
                print(f"Vision error: {e}")

        # 3. VIDEO (Cinema / Video)
        # Supporta tutti i formati video standard, web e cinema RAW professionali
        if ext in [
            ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".f4v", ".wmv", ".m4v", ".mpg", ".mpeg", ".m2v", ".3gp", ".3g2", 
            ".ts", ".mts", ".m2ts", ".vob", ".ogv", ".divx", ".asf",
            ".braw", ".r3d", ".ari", ".arx", ".mxf", ".cine", ".crm", ".mcw"
        ]:
            if metadata:
                return f"VIDEO_METADATA: {metadata}"
            return f"VIDEO_FILE: {os.path.basename(file_path)}"

        return ""

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
        
        # 1. Bypass se l'utente ha identificato manualmente delle persone
        if "Persone identificate dall'utente: " in context:
            user_identified = context.split("Persone identificate dall'utente: ")[-1].strip()
            # Pulisce e normalizza il nome fornito dall'utente
            user_identified = re.sub(r'[^a-zA-Z0-9_ ]', '', user_identified).strip()
            user_identified = re.sub(r'\s+', '_', user_identified)
            if len(user_identified) > 2:
                # Restituisce direttamente il percorso strutturato basato sul nome utente, garantendo 100% fedeltà
                orig_ext = os.path.splitext(original_name)[1]
                return f"{category}/Persone/Identificate/{user_identified}{orig_ext}"

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
