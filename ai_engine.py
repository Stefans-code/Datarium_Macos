import os
import sys
import hashlib
import base64
from io import BytesIO
from PIL import Image, ExifTags
from huggingface_hub import hf_hub_download

class AIEngine:
    def __init__(self):
        self.llm = None
        self.is_vision = False
        self.hardware_info = "CPU"
        
        # Default Text Model
        self.text_repo = "TheBloke/phi-2-GGUF"
        self.text_file = "phi-2.Q4_K_M.gguf"
        
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
            # Percorso Windows accanto all'exe
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
                   os.path.exists(os.path.join(d, "phi-2.Q2_K.gguf"))
            
            v_ok = os.path.exists(os.path.join(d, self.vision_file)) or \
                   os.path.exists(os.path.join(d, "llava-v1.5-7b-Q2_K.gguf"))
            
            p_ok = os.path.exists(os.path.join(d, self.vision_projector))
            
            if t_ok and v_ok and p_ok:
                return False # Trovati tutti!
            
            return True # Qualcosa manca
        except:
            return True

    def download_model_if_needed(self, vision_mode=True, progress_callback=None):
        """Ora ritorna (True/False, error_msg) per una gestione UI migliore."""
        try:
            models_dir = self.get_models_dir()
            
            tasks = []
            tasks.append((self.text_repo, self.text_file))
            if vision_mode:
                tasks.append((self.vision_repo, self.vision_file))
                tasks.append((self.vision_repo, self.vision_projector))

            for repo, filename in tasks:
                # Fallback slim names
                is_slim = False
                alt_filename = filename
                if "phi-2" in filename: alt_filename = "phi-2.Q2_K.gguf"
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
                from llama_cpp import Llama
                from llama_cpp.llama_chat_format import Llava15ChatHandler
                
                n_threads = os.cpu_count() or 4
                final_models_dir = self.get_models_dir()
                
                # Identifica i percorsi reali (main o slim)
                t_path = os.path.join(final_models_dir, self.text_file)
                if not os.path.exists(t_path): t_path = os.path.join(final_models_dir, "phi-2.Q2_K.gguf")
                
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
        except: pass
        return meta

    def extract_context(self, file_path):
        """Extracts a deep text summary or detailed image description with metadata fusion."""
        ext = os.path.splitext(file_path)[1].lower()
        metadata = self.extract_metadata(file_path)
        meta_str = f" [Metadata: {metadata}]" if metadata else ""
        
        # 1. DOCUMENTI
        try:
            if ext == ".pdf":
                import fitz
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
        if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"] and self.is_vision:
            try:
                img = Image.open(file_path)
                img.thumbnail((448, 448)) # Risoluzione ideale per LLaVA 1.5
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                data_url = f"data:image/jpeg;base64,{img_str}"
                
                # Prompt intelligente che fonde Visione e Metadati
                hint = f"Note: This file was created on {metadata.get('DateTimeOriginal', 'unknown date')}." if metadata else ""
                
                response = self.llm.create_chat_completion(
                    messages=[
                        {"role": "user", "content": [
                            {"type": "text", "text": "Describe this image with focus on main objects and context for archiving purposes."},
                            {"type": "image_url", "image_url": {"url": data_url}}
                        ]}
                    ],
                    max_tokens=50,
                    temperature=0.1
                )
                return f"IMAGE_DESC: {response['choices'][0]['message']['content'].strip()}{meta_str}"
            except Exception as e: print(f"Vision error: {e}")

        return ""

    def identify_global_themes(self, all_contexts):
        """Brainstorming: Analyse all contexts to find macro-themes and sub-themes."""
        if not self.llm or not all_contexts: return "Generale, Varie"
        
        summaries = "\n".join([c[:150] for c in all_contexts if c][:40])
        if not summaries: return "Varie"
        
        prompt = f"""Instruct: Analyze these descriptions and create a 2-level taxonomy (Category > Subcategory).
Identify 5 main Categories and for each, 1-2 Subcategories.
Format: Category1(Sub1, Sub2), Category2(Sub1)...
Only the words.

Files:
{summaries}

Taxonomy:"""
        
        try:
            output = self.llm(prompt, max_tokens=100, temperature=0.5, stop=["\n"])
            return output["choices"][0]["text"].strip()
        except:
            return "Documentazione(Lavoro, Personale), Immagini(Viaggi, Natura), Archivio(Varie)"

    def get_smart_name(self, original_name, category, context="", taxonomy=""):
        """Generates a smart name using deep context and hierarchical taxonomy."""
        if not self.llm: return f"{category}/{original_name}"
            
        context_str = f"\nContext: {context}" if context else ""
        taxo_str = f"\nAllowed Taxonomy: {taxonomy}" if taxonomy else ""
        
        prompt = f"""Instruct: You are an expert archivist. Rename the file into: CATEGORY/SUBCATEGORY/FILENAME.
Rules:
- Filename must be descriptive but MAX 5 WORDS.
- Detailed and professional.
- No extensions. Underscores only.
- Format: Category/Subcategory/Smart_Name_Of_Five_Words
- Use Allowed Taxonomy.

Examples:
Original: image_801.jpg
Context: Family photo at the Eiffel Tower, summer 2023.
Taxonomy: Viaggi(Francia)
New Path: Viaggi/Francia/Famiglia_Sotto_Torre_Eiffel_2023

Original: {original_name} (Type: {category}){context_str}{taxo_str}
New Path:"""
        
        try:
            output = self.llm(
                prompt,
                max_tokens=32,
                stop=["\n", "Original:", "Instruct:"],
                temperature=0.2,
                repeat_penalty=1.4
            )
            clean_path = output["choices"][0]["text"].strip()
            
            # Final cleanup
            clean_path = clean_path.strip("'\" ").split('(')[0].split('\'')[0].split('"')[0].strip()
            clean_path = clean_path.replace(" ", "_")
            
            # Remove any trailing extensions from AI
            while '.' in clean_path:
                idx = clean_path.rfind('.')
                if idx > len(clean_path)-6: clean_path = clean_path[:idx]
                else: break
            
            # Sanitize but keep the '/' for themes
            import re
            clean_path = re.sub(r'[^a-zA-Z0-9_/]', '', clean_path)
            
            if len(clean_path) < 3:
                clean_path = f"Generale/{os.path.splitext(original_name)[0]}"
                
            orig_ext = os.path.splitext(original_name)[1]
            # Assicuriamoci che il percorso finale sia Categoria/Tema/Nome.ext
            return f"{category}/{clean_path}{orig_ext}"
        except Exception as e:
            return f"{category}/{original_name}"
        except Exception as e:
            return f"{category}/{original_name}"
            
    def compute_file_hash(self, file_path):
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as afile:
                buf = afile.read(65536)
                while len(buf) > 0:
                    hasher.update(buf); buf = afile.read(65536)
            return hasher.hexdigest()
        except: return None
