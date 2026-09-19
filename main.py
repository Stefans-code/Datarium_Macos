import os
import sys
import tempfile
try:
    os.chdir(tempfile.gettempdir())
except Exception:
    pass

# Dummy imports block to prevent linter errors and force PyInstaller to statically package C-extensions
if False:
    import xxhash
    import pillow_heif
    import fitz
    import docx
    import llama_cpp
    import llama_cpp.llama_chat_format
    import cv2
    import face_memory

# Windows DPI Awareness for crisp UI
if os.name == 'nt':
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# Ridirezione standard output/error per evitare crash in modalità --noconsole
# se qualche libreria (es. tqdm/huggingface) prova a scrivere sul terminale inesistente.
if getattr(sys, 'frozen', False):
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

import customtkinter as ctk
import re
import platform
import threading
import shutil
import pathlib
from tkinter import filedialog
import disk_benchmark
from ai_engine import AIEngine
from license_manager import LicenseManager
import cv2
from face_memory import FaceMemoryManager

# Unica fonte di verita' per la versione installata: usata sia nella UI che nel check
# aggiornamenti, cosi' non si scorda di allinearle a mano ad ogni release.
APP_VERSION = "1.3.0"

def _version_tuple(v):
    """'1.10.2' -> (1, 10, 2). Confrontare tuple di interi, non le stringhe: '1.10.0' > '1.2.0'
    e' False come confronto lessicografico di stringhe (il carattere '1' < '2'), quindi un
    aggiornamento reale da 1.2.x a 1.10.x smetteva di essere rilevato. Pezzi non numerici
    (es. suffissi '-beta') vengono ignorati per sicurezza invece di far esplodere il parsing."""
    parts = []
    for p in str(v).strip().split('.'):
        digits = ''.join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)

def _is_newer_version(remote_version, current_version):
    return _version_tuple(remote_version) > _version_tuple(current_version)

ctk.set_appearance_mode("Dark")


def _resource_dir():
    """
    Cartella base delle risorse bundlate (assets/, icon.ico...), corretta per ogni
    piattaforma e modalità (sviluppo vs frozen).

    Su macOS un bundle .app mette le risorse aggiunte con --add-data in
    Contents/Resources/, un percorso DIVERSO da sys._MEIPASS (che punta dentro
    Contents/MacOS/): usare solo _MEIPASS lì fa fallire in silenzio ogni
    caricamento di risorsa (tema colori, icone) — l'app parte comunque, ma con
    l'aspetto di default, senza nessun errore visibile. Su Windows/Linux invece
    _MEIPASS combacia con dove PyInstaller mette davvero i dati.
    """
    if getattr(sys, 'frozen', False):
        if platform.system() == "Darwin":
            exe_path = os.path.abspath(sys.executable).replace("\\", "/")
            if "/Contents/MacOS/" in exe_path:
                contents_dir = os.path.dirname(os.path.dirname(sys.executable))  # .../Contents
                resources_dir = os.path.join(contents_dir, "Resources")
                if os.path.isdir(resources_dir):
                    return resources_dir
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


theme_path = os.path.join(_resource_dir(), "assets", "material_theme.json")

if os.path.exists(theme_path):
    ctk.set_default_color_theme(theme_path)
else:
    ctk.set_default_color_theme("blue")

class ImageIdentificationDialog(ctk.CTkToplevel):
    def __init__(self, parent, image_path, filename):
        super().__init__(parent)
        self.title("Identifica Persone")
        self.geometry("550x550")
        self.resizable(False, False)
        
        # Rendi la finestra modale e in primo piano
        self.transient(parent)
        self.grab_set()
        
        self.user_input = None
        
        # Carica e ridimensiona l'immagine con PIL
        try:
            from PIL import Image
            img = Image.open(image_path)
            # Calcola dimensioni mantenendo le proporzioni
            img.thumbnail((450, 300))
            self.photo = ctk.CTkImage(light_image=img, size=img.size)
            
            # Label per l'immagine
            self.img_lbl = ctk.CTkLabel(self, text="", image=self.photo)
            self.img_lbl.pack(pady=15)
        except Exception as e:
            # Fallback se non si riesce a caricare
            self.img_lbl = ctk.CTkLabel(self, text=f"[Anteprima non disponibile]\n{e}", text_color="red")
            self.img_lbl.pack(pady=50)
            
        # Domanda
        self.lbl_question = ctk.CTkLabel(self, text=f"Chi c'è nella foto '{filename}'?", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_question.pack(pady=5)
        
        self.lbl_sub = ctk.CTkLabel(self, text="Inserisci i nomi (es. Marco, Maria) o lascia vuoto:", font=ctk.CTkFont(size=11), text_color="gray")
        self.lbl_sub.pack(pady=2)
        
        # Campo di testo
        self.entry = ctk.CTkEntry(self, width=400, placeholder_text="Nomi delle persone...")
        self.entry.pack(pady=10)
        self.entry.focus()
        
        # Premi Invio per confermare
        self.entry.bind("<Return>", lambda e: self.on_ok())
        
        # Pulsanti
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=15)
        
        self.btn_cancel = ctk.CTkButton(btn_frame, text="Salta", width=100, fg_color="transparent", border_width=1, command=self.on_cancel)
        self.btn_cancel.pack(side="left", padx=10)
        
        self.btn_ok = ctk.CTkButton(btn_frame, text="Conferma", width=120, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), command=self.on_ok)
        self.btn_ok.pack(side="left", padx=10)
        
        # Blocca l'esecuzione finché non si chiude la finestra
        self.wait_window(self)
        
    def on_ok(self):
        self.user_input = self.entry.get().strip()
        self.destroy()
        
    def on_cancel(self):
        self.user_input = ""
        self.destroy()

class FaceIdentificationDialog(ctk.CTkToplevel):
    def __init__(self, parent, face_pil_img, filename, face_idx, total_faces):
        super().__init__(parent)
        self.title(f"Identifica Volto {face_idx}/{total_faces}")
        self.geometry("450x420")
        self.resizable(False, False)
        
        # Rendi la finestra modale e in primo piano
        self.transient(parent)
        self.grab_set()
        
        self.user_input = None
        
        # Mostra il ritaglio della faccia
        try:
            face_pil_img = face_pil_img.copy()
            face_pil_img.thumbnail((200, 200))
            self.photo = ctk.CTkImage(light_image=face_pil_img, size=face_pil_img.size)
            self.img_lbl = ctk.CTkLabel(self, text="", image=self.photo)
            self.img_lbl.pack(pady=15)
        except Exception as e:
            self.img_lbl = ctk.CTkLabel(self, text=f"[Anteprima non disponibile]\n{e}", text_color="red")
            self.img_lbl.pack(pady=40)
            
        # Domanda
        self.lbl_question = ctk.CTkLabel(self, text="Chi è questa persona?", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_question.pack(pady=5)
        
        self.lbl_sub = ctk.CTkLabel(self, text=f"Volto rilevato nell'immagine '{filename}'", font=ctk.CTkFont(size=11), text_color="gray")
        self.lbl_sub.pack(pady=2)
        
        # Campo di testo
        self.entry = ctk.CTkEntry(self, width=320, placeholder_text="Inserisci il nome (es. Stefan) o lascia vuoto...")
        self.entry.pack(pady=12)
        self.entry.focus()
        
        # Premi Invio per confermare
        self.entry.bind("<Return>", lambda e: self.on_ok())
        
        # Pulsanti
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)
        
        self.btn_cancel = ctk.CTkButton(btn_frame, text="Salta Faccia", width=110, fg_color="transparent", border_width=1, command=self.on_cancel)
        self.btn_cancel.pack(side="left", padx=10)
        
        self.btn_ok = ctk.CTkButton(btn_frame, text="Salva in Memoria", width=140, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), command=self.on_ok)
        self.btn_ok.pack(side="left", padx=10)
        
        self.wait_window(self)
        
    def on_ok(self):
        self.user_input = self.entry.get().strip()
        self.destroy()
        
    def on_cancel(self):
        self.user_input = ""
        self.destroy()

class DatariumApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Datarium: AI File Organizer")
        self.geometry("1100x700")
        self.minsize(900, 600)
        
        # Carica l'icona della finestra
        try:
            # Tenta di trovare l'icona nell'eseguibile o nella cartella locale
            self.icon_path = os.path.join(_resource_dir(), "icon.ico")

            if os.path.exists(self.icon_path):
                self.iconbitmap(self.icon_path)
        except Exception: pass

        # Core Engines
        self.ai = AIEngine()
        self.license = LicenseManager()
        self.face_mem = FaceMemoryManager()  # i dati volti vivono in LOCALAPPDATA/faces, non in models/

        # Check aggiornamenti automatico e silenzioso all'avvio (non blocca la UI: parte
        # su un thread dopo che la finestra e' gia' visibile, e non disturba se offline).
        self.after(3000, self.check_software_updates_silent)

        # State
        self.source_folder = ctk.StringVar(value="")
        self.control_folder = ctk.StringVar(value="")
        self.backup_folder = ctk.StringVar(value="")
        self.is_licensed, self.license_status = self.license.verify_license()
        self.is_ai_loaded = False
        self.stop_ai = False
        self.last_groups = {}

        # Hash Feature State
        self.hash_source_file = ctk.StringVar(value="")
        self.selected_hash_files_list = []
        self.hash_source_folder = ctk.StringVar(value="")
        self.hash_source_folder_2 = ctk.StringVar(value="")
        self.hash_shutdown_after = ctk.BooleanVar(value=False)
        self.hash_quick_mode = ctk.BooleanVar(value=False)
        self.selected_hash_algo = ctk.StringVar(value="-Scegli-")
        self.highlight_dups = ctk.BooleanVar(value=True)
        self.compare_contents = ctk.BooleanVar(value=False)
        self.recent_hash_files = []
        self.autotag_folder = ctk.StringVar(value="")
        self.autotag_source_folder = ctk.StringVar(value="")
        self.autotag_dest_folder = ctk.StringVar(value="")
        self.autotag_accept_ai = ctk.BooleanVar(value=True)
        self.autotag_rename = ctk.BooleanVar(value=True)
        self.organizer_identify_people = ctk.BooleanVar(value=True)
        self.organizer_keep_names = ctk.BooleanVar(value=True)

        # Offload Feature State
        import datetime
        self.offload_source_folder = ctk.StringVar(value="")
        self.offload_dest_folder_1 = ctk.StringVar(value="")
        self.offload_dest_folder_2 = ctk.StringVar(value="")
        self.offload_algo = ctk.StringVar(value="xxHash64")
        self.offload_report_id = ctk.StringVar(value="A" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

        # Metadati produzione (stile Silverstack), inclusi nel report MHL dell'Offload
        self.offload_meta_fields = [
            ("production", "Produzione"),
            ("director", "Regista"),
            ("dop", "Dir. Fotografia"),
            ("scene", "Scena"),
            ("shot", "Inquadratura"),
            ("take", "Take"),
            ("reel", "Reel / Card"),
            ("camera", "Camera"),
            ("camera_model", "Modello Camera"),
            ("lens", "Obiettivo"),
            ("fps", "FPS"),
            ("location", "Luogo"),
        ]
        self.offload_meta_vars = {key: ctk.StringVar(value="") for key, _ in self.offload_meta_fields}
        self.offload_notes_text = None
        self.offload_make_proxy = ctk.BooleanVar(value=False)
        self.offload_eject_source = ctk.BooleanVar(value=False)
        self.offload_shutdown_after = ctk.BooleanVar(value=False)

        # Naming destinazione configurabile (come ShotPut Pro: sottocartella generata a partire
        # da uno schema, invece di mirror-are sempre e solo il path relativo della sorgente).
        # Default "Nessuna" = comportamento identico a prima, nessuna regressione per chi non la tocca.
        self.offload_naming_scheme = ctk.StringVar(value="Nessuna (mirror sorgente)")
        self.offload_naming_prefix = ctk.StringVar(value="")

        # Preset: gruppi salvati di {destinazioni, algoritmo, naming, prefix} riutilizzabili,
        # persistiti in config.json insieme alle altre impostazioni dell'app.
        self.offload_presets = {}
        self.offload_selected_preset = ctk.StringVar(value="")


        # Sincronizza Dischi (confronto A/B stile FreeFileSync)
        self.sync_path_a = ctk.StringVar(value="")
        self.sync_path_b = ctk.StringVar(value="")
        self.sync_deep = ctk.BooleanVar(value=False)
        self.sync_verify = ctk.BooleanVar(value=True)
        self.sync_exclude = ctk.StringVar(value="")
        self.sync_mode_var = ctk.StringVar(value="Aggiorna A ▶ B (copia il nuovo, non elimina)")
        self.sync_show = {k: ctk.BooleanVar(value=(k != "identical")) for k in ("only_a", "only_b", "different", "identical")}
        self.sync_rows = []
        self.sync_busy = False

        # Settings state
        self.load_settings()
        self.scan_sidecars_var = ctk.BooleanVar(value=self.scan_sidecars_enabled)
        self.proxy_gen_var = ctk.BooleanVar(value=self.proxy_gen_enabled)
        self.proxy_resolution_var = ctk.StringVar(value=self.proxy_resolution)
        self.proxy_format_var = ctk.StringVar(value=self.proxy_format)
        self.use_custom_rules_var = ctk.BooleanVar(value=True)

        # UI Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.setup_sidebar()
        self.setup_main_content()
        
        # Default Page
        if self.ai.check_models_missing():
            self.show_page("Setup")
        else:
            self.show_page("Home")

    def get_config_path(self):
        import platform
        system = platform.system()
        if system == "Windows":
            base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
            path = os.path.join(base, "Datarium")
        elif system == "Darwin":
            path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium")
        else:
            path = os.path.join(os.path.expanduser("~"), ".datarium")
        os.makedirs(path, exist_ok=True)
        return os.path.join(path, "config.json")

    def get_job_history_path(self):
        return os.path.join(os.path.dirname(self.get_config_path()), "job_history.json")

    def load_settings(self):
        import json
        config_path = self.get_config_path()
        self.custom_rules = []
        self.ffmpeg_path = ""
        self.scan_sidecars_enabled = True
        self.proxy_gen_enabled = False
        self.proxy_resolution = "Half"
        self.proxy_format = "H.264 (.mp4)"
        self.offload_presets = {}
        self.job_history_max = 50

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.custom_rules = data.get("custom_rules", [])
                    self.ffmpeg_path = data.get("ffmpeg_path", "")
                    self.scan_sidecars_enabled = data.get("scan_sidecars_enabled", True)
                    self.proxy_gen_enabled = data.get("proxy_gen_enabled", False)
                    self.proxy_resolution = self.ai.normalize_proxy_resolution(data.get("proxy_resolution"))
                    self.proxy_format = self.ai.normalize_proxy_format(data.get("proxy_format"))
                    self.offload_presets = data.get("offload_presets", {})
                    self.job_history_max = data.get("job_history_max", 50)
            except Exception as e:
                print(f"Errore caricamento impostazioni: {e}")
                
    def save_settings(self):
        import json
        config_path = self.get_config_path()
        data = {
            "custom_rules": self.custom_rules,
            "ffmpeg_path": self.ffmpeg_path,
            "scan_sidecars_enabled": self.scan_sidecars_var.get(),
            "proxy_gen_enabled": self.proxy_gen_var.get(),
            "proxy_resolution": self.proxy_resolution_var.get(),
            "proxy_format": self.proxy_format_var.get(),
            "offload_presets": self.offload_presets,
            "job_history_max": self.job_history_max
        }
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Errore salvataggio impostazioni: {e}")

    def go_to_organizer(self):
        if self.source_folder.get():
            self.show_page("Options")
        else:
            self.show_page("OrganizerHome")

    def setup_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        self.logo_lbl = ctk.CTkLabel(self.sidebar, text="DATARIUM", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_lbl.grid(row=0, column=0, padx=20, pady=(30, 40))

        # Voci di navigazione: niente emoji (solo testo), con uno stato attivo
        # visibile (sfondo tonale blu) che prima non esisteva -- l'utente non aveva
        # modo di vedere a colpo d'occhio in che pagina si trovava, solo l'hover al
        # passaggio del mouse.
        self.NAV_INACTIVE = {"fg_color": "transparent", "text_color": ("gray10", "gray90")}
        self.NAV_ACTIVE = {"fg_color": ("#dbeafe", "#1e3a5f"), "text_color": ("#1d4ed8", "#7dd3fc")}
        self._nav_buttons = {}

        self.btn_home = ctk.CTkButton(self.sidebar, text="Home", hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Home"), **self.NAV_INACTIVE)
        self.btn_home.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        self._nav_buttons["Home"] = self.btn_home

        self.btn_organizer = ctk.CTkButton(self.sidebar, text="Organizer", hover_color=("gray70", "gray30"), anchor="w", command=self.go_to_organizer, **self.NAV_INACTIVE)
        self.btn_organizer.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        self._nav_buttons["Organizer"] = self.btn_organizer

        self.btn_autotag = ctk.CTkButton(self.sidebar, text="Auto Tag", hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("AutoTag"), **self.NAV_INACTIVE)
        self.btn_autotag.grid(row=3, column=0, padx=20, pady=5, sticky="ew")
        self._nav_buttons["AutoTag"] = self.btn_autotag

        self.btn_hash = ctk.CTkButton(self.sidebar, text="Hash Check", hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("HashHome"), **self.NAV_INACTIVE)
        self.btn_hash.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        self._nav_buttons["Hash"] = self.btn_hash

        self.btn_offload = ctk.CTkButton(self.sidebar, text="Offload", hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("OffloadHome"), **self.NAV_INACTIVE)
        self.btn_offload.grid(row=5, column=0, padx=20, pady=5, sticky="ew")
        self._nav_buttons["Offload"] = self.btn_offload

        self.btn_sync = ctk.CTkButton(self.sidebar, text="Sincronizza Dischi", hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Sync"), **self.NAV_INACTIVE)
        self.btn_sync.grid(row=6, column=0, padx=20, pady=5, sticky="ew")
        self._nav_buttons["Sync"] = self.btn_sync

        # Bottom Buttons
        self.sidebar.grid_rowconfigure(7, weight=1)

        self.btn_settings = ctk.CTkButton(self.sidebar, text="Impostazioni", hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Settings"), **self.NAV_INACTIVE)
        self.btn_settings.grid(row=8, column=0, padx=20, pady=10, sticky="ew")
        self._nav_buttons["Settings"] = self.btn_settings

        self.appearance_mode_segmented = ctk.CTkSegmentedButton(self.sidebar, values=["Scuro", "Chiaro"], command=self.change_appearance_mode)
        self.appearance_mode_segmented.grid(row=9, column=0, padx=20, pady=(10, 30), sticky="ew")
        self.appearance_mode_segmented.set("Scuro")

    def setup_main_content(self):
        self.content_container = ctk.CTkFrame(self, fg_color="transparent")
        self.content_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        
        self.pages = {}
        self.init_home_page()
        self.init_organizer_page()
        self.init_options_page()
        self.init_preview_page()
        self.init_settings_page()
        self.init_setup_page()
        self.init_hash_pages()
        self.init_autotag_page()
        self.init_offload_pages()
        self.init_sync_page()

    def init_organizer_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["OrganizerHome"] = page
        
        ctk.CTkLabel(page, text="Organizer AI", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))
        
        box = ctk.CTkFrame(page, corner_radius=15, border_width=1, border_color=("gray85", "gray15"))
        box.pack(fill="both", expand=True, padx=5, pady=5)
        
        ctk.CTkLabel(box, text="Inizia l'organizzazione", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=30, pady=(30, 5))
        ctk.CTkLabel(box, text="Seleziona la cartella principale che contiene i file da analizzare e organizzare.", text_color="gray").pack(anchor="w", padx=30)
        
        btn_open = ctk.CTkButton(box, text="📂 Seleziona Cartella", font=ctk.CTkFont(size=18, weight="bold"), height=60, width=280, corner_radius=12, command=self.open_source_folder)
        btn_open.place(relx=0.5, rely=0.5, anchor="center")

    def init_setup_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Setup"] = page
        
        # Centered Panel
        login_box = ctk.CTkFrame(page, width=600, height=450, corner_radius=20)
        login_box.place(relx=0.5, rely=0.5, anchor="center")
        login_box.pack_propagate(False)
        
        ctk.CTkLabel(login_box, text="DATARIUM", font=ctk.CTkFont(size=36, weight="bold")).pack(pady=(30, 10))
        ctk.CTkLabel(login_box, text="Completamento dell'installazione...", font=ctk.CTkFont(size=18), text_color="gray").pack()
        
        # Default = profilo GIA' installato (se c'e'), cosi' non si propone uno switch slim<->full
        self.model_choice_var = ctk.StringVar(value=(self.ai.get_installed_quality() or "full"))
        opt_f = ctk.CTkFrame(login_box, fg_color="transparent")
        opt_f.pack(pady=10)
        ctk.CTkRadioButton(opt_f, text="Qualità Massima AI (Consigliato - 6GB)", variable=self.model_choice_var, value="full").pack(anchor="w", pady=5)
        ctk.CTkRadioButton(opt_f, text="Installazione Leggera (Modelli Compressi - 4GB)", variable=self.model_choice_var, value="slim").pack(anchor="w", pady=5)

        self.btn_start_setup = ctk.CTkButton(login_box, text="Inizia Download", command=lambda: threading.Thread(target=self.start_setup_flow, daemon=True).start())
        self.btn_start_setup.pack(pady=10)

        self.setup_status_lbl = ctk.CTkLabel(login_box, text="Scegli il modello e clicca Inizia", font=ctk.CTkFont(size=14, weight="bold"))
        self.setup_status_lbl.pack(pady=(10, 10))
        
        self.setup_progress = ctk.CTkProgressBar(login_box, width=450, height=15)
        self.setup_progress.pack(pady=10)
        self.setup_progress.set(0)
        
        ctk.CTkLabel(login_box, text="L'operazione potrebbe richiedere alcuni minuti in base alla connessione.", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=10)

    def start_setup_flow(self):
        self.btn_start_setup.configure(state="disabled")
        quality = getattr(self, 'model_choice_var', ctk.StringVar(value="full")).get()
        success, error_msg = self.ai.download_model_if_needed(True, self.update_setup_status, quality)
        if success:
            self.after(0, lambda: self.show_page("Home"))
        else:
            self.after(0, lambda: self.setup_status_lbl.configure(
                text=f"Errore: {error_msg}\nRiprova tra poco.", 
                text_color="#ef4444"
            ))
            self.after(0, lambda: self.btn_start_setup.configure(state="normal"))

    def update_setup_status(self, text):
        if self.setup_status_lbl.winfo_exists():
            self.after(0, lambda: self.setup_status_lbl.configure(text=text))
            # Il testo del downloader (vedi ai_engine.py) include "NN%" quando si conosce
            # la dimensione attesa: un regex sul numero prima del simbolo e' molto più
            # robusto del vecchio split su '%'/'|', che si rompeva a ogni cambio di formato
            # del messaggio (e infatti restava sempre fermo a 0: il testo reale non
            # conteneva mai un '%' prima di questa correzione).
            match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
            if match:
                try:
                    pct = float(match.group(1)) / 100
                    self.after(0, lambda: self.setup_progress.set(pct))
                except Exception:
                    pass

    def init_home_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Home"] = page

        # Welcome Header Banner
        header = ctk.CTkFrame(page, fg_color=("gray95", "gray11"), corner_radius=15, height=140)
        header.pack(fill="x", pady=(0, 20))
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="Benvenuto in Datarium", font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", padx=30, pady=(25, 2))
        ctk.CTkLabel(header, text="Il tuo assistente intelligente per l'organizzazione di file, immagini e video basato sull'AI.", font=ctk.CTkFont(size=13), text_color="gray").pack(anchor="w", padx=30)

        # Quick access grid or container
        cards_container = ctk.CTkFrame(page, fg_color="transparent")
        cards_container.pack(fill="both", expand=True)

        # Let's configure columns for grid
        cards_container.columnconfigure(0, weight=1)
        cards_container.columnconfigure(1, weight=1)
        cards_container.columnconfigure(2, weight=1)
        cards_container.columnconfigure(3, weight=1)
        
        from PIL import Image
        base_dir = _resource_dir()
        folder_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "folder.png")), size=(64, 64))
        key_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "key.png")), size=(64, 64))
        tag_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "tag.png")), size=(64, 64))
        flash_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "flash.png")), size=(64, 64))

        # Card 1: Organizer
        c1 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c1.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        c1.pack_propagate(False)

        ctk.CTkLabel(c1, text="", image=folder_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c1, text="Organizer AI", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c1, text="Scansiona, ordina e rinomina i tuoi file e documenti in base al contenuto.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c1, text="Apri Organizer", font=ctk.CTkFont(weight="bold"), height=38, corner_radius=8, command=self.go_to_organizer).pack(side="bottom", pady=30, padx=20, fill="x")

        # Card 3: Auto Tag
        c3 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c3.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        c3.pack_propagate(False)

        ctk.CTkLabel(c3, text="", image=tag_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c3, text="Auto Tag & Album", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c3, text="Raggruppa foto e video in album intelligenti generati dall'AI.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c3, text="Vai ad Album", font=ctk.CTkFont(weight="bold"), height=38, corner_radius=8, command=lambda: self.show_page("AutoTag")).pack(side="bottom", pady=30, padx=20, fill="x")

        # Card 2: Hash Check
        c2 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c2.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        c2.pack_propagate(False)

        ctk.CTkLabel(c2, text="", image=key_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c2, text="Verifica Hash", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c2, text="Calcola l'hash dei file e confronta duplicati esatti byte-a-byte.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c2, text="Vai ad Hash", font=ctk.CTkFont(weight="bold"), height=38, corner_radius=8, command=lambda: self.show_page("HashHome")).pack(side="bottom", pady=30, padx=20, fill="x")

        # Card 4: Offload & PDF
        c4 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c4.grid(row=0, column=3, padx=10, pady=10, sticky="nsew")
        c4.pack_propagate(False)

        ctk.CTkLabel(c4, text="", image=flash_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c4, text="Offload", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c4, text="Copia sicura SSD multidisco con verifica checksum ed esportazione report.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c4, text="Vai ad Offload", font=ctk.CTkFont(weight="bold"), height=38, corner_radius=8, command=lambda: self.show_page("OffloadHome")).pack(side="bottom", pady=30, padx=20, fill="x")


    def init_options_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Options"] = page

        # Centered Modal-like box
        modal = ctk.CTkFrame(page, width=750, height=600, corner_radius=20, border_width=2, border_color=("gray80", "gray20"))
        modal.place(relx=0.5, rely=0.5, anchor="center")
        modal.pack_propagate(False)

        ctk.CTkLabel(modal, text="Configurazione Archivio", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(30, 20))

        # --- GRID FOR FOLDERS ---
        grid_f = ctk.CTkFrame(modal, fg_color="transparent")
        grid_f.pack(fill="x", padx=40, pady=5)
        grid_f.columnconfigure(1, weight=1)

        # Row 1: Cartella di Controllo
        ctk.CTkLabel(grid_f, text="Cartella di Controllo:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", pady=(5, 0))
        ctk.CTkLabel(grid_f, textvariable=self.control_folder, text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, anchor="w", justify="left").grid(row=0, column=1, padx=20, pady=(5, 0), sticky="ew")
        ctk.CTkButton(grid_f, text="📂", width=40, command=self.open_dest_folder).grid(row=0, column=2, pady=(5, 0), sticky="e")
        ctk.CTkLabel(grid_f, text="La cartella che l'AI scansionerà per organizzare i file.", font=ctk.CTkFont(size=11, slant="italic"), text_color="#38bdf8").grid(row=1, column=0, columnspan=3, sticky="w", padx=5, pady=(2, 5))

        # Row 2: Posto Salvataggio ZIP
        ctk.CTkLabel(grid_f, text="Posto di Salvataggio ZIP:", font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, sticky="w", pady=(5, 0))
        ctk.CTkLabel(grid_f, textvariable=self.backup_folder, text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, anchor="w", justify="left").grid(row=2, column=1, padx=20, pady=(5, 0), sticky="ew")
        ctk.CTkButton(grid_f, text="📂", width=40, command=self.open_backup_folder).grid(row=2, column=2, pady=(5, 0), sticky="e")
        ctk.CTkLabel(grid_f, text="La cartella in cui verrà salvato l'archivio ZIP di backup di sicurezza dei file originali.", font=ctk.CTkFont(size=11, slant="italic"), text_color="#38bdf8").grid(row=3, column=0, columnspan=3, sticky="w", padx=5, pady=(2, 5))

        # --- FILE TYPES ---
        ctk.CTkLabel(modal, text="File da analizzare", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 5))
        self.filter_frame = ctk.CTkFrame(modal, fg_color="transparent")
        self.filter_frame.pack(pady=10)
        
        self.no_files_lbl = ctk.CTkLabel(self.filter_frame, text="Seleziona una cartella per analizzare i tipi", text_color="gray")
        self.no_files_lbl.pack()

        # --- ADVANCED OPTIONS ---
        ctk.CTkLabel(modal, text="Opzioni", font=ctk.CTkFont(weight="bold")).pack(pady=(10, 2))
        
        opts_container = ctk.CTkFrame(modal, fg_color="transparent")
        opts_container.pack(pady=5)
        
        opts_row1 = ctk.CTkFrame(opts_container, fg_color="transparent")
        opts_row1.pack(pady=3)
        
        self.check_ai = ctk.CTkCheckBox(opts_row1, text="Scelta AI")
        self.check_ai.pack(side="left", padx=8); self.check_ai.select()
        
        self.check_dup = ctk.CTkCheckBox(opts_row1, text="Check Duplicati")
        self.check_dup.pack(side="left", padx=8); self.check_dup.select()
        
        self.check_identify_people_cb = ctk.CTkCheckBox(opts_row1, text="Identifica Persone", variable=self.organizer_identify_people)
        self.check_identify_people_cb.pack(side="left", padx=8); self.check_identify_people_cb.select()
        
        opts_row2 = ctk.CTkFrame(opts_container, fg_color="transparent")
        opts_row2.pack(pady=3)
        
        self.check_sidecars_cb = ctk.CTkCheckBox(opts_row2, text="Leggi Trascrizioni Vocius", variable=self.scan_sidecars_var)
        self.check_sidecars_cb.pack(side="left", padx=8)
        
        self.check_rules_cb = ctk.CTkCheckBox(opts_row2, text="Usa Regole Smistamento", variable=self.use_custom_rules_var)
        self.check_rules_cb.pack(side="left", padx=8)
        
        self.check_proxies_cb = ctk.CTkCheckBox(opts_row2, text="Genera Video Proxy", variable=self.proxy_gen_var)
        self.check_proxies_cb.pack(side="left", padx=8)

        opts_row3 = ctk.CTkFrame(opts_container, fg_color="transparent")
        opts_row3.pack(pady=3)
        self.check_keep_names_cb = ctk.CTkCheckBox(opts_row3, text="Mantieni i nomi originali già descrittivi", variable=self.organizer_keep_names)
        self.check_keep_names_cb.pack(side="left", padx=8)




        # --- FOOTER ---
        btn_f = ctk.CTkFrame(modal, fg_color="transparent")
        btn_f.pack(side="bottom", fill="x", padx=40, pady=30)
        ctk.CTkButton(btn_f, text="Annulla", fg_color="transparent", text_color=("gray10", "gray90"), border_width=2, width=120, command=lambda: self.show_page("Home")).pack(side="left")
        ctk.CTkButton(btn_f, text="Conferma", width=140, fg_color="#10b981", hover_color="#059669", command=self.go_to_preview).pack(side="right")

    def auto_detect_file_types(self, folder):
        for widget in self.filter_frame.winfo_children():
            widget.destroy()
            
        counts = {"Immagini": 0, "Video": 0, "Documenti": 0, "Altro": 0}
        for root, dirs, files in os.walk(folder):
            # Saltiamo le cartelle di backup create dall'app stessa
            if "Backup_Datarium_" in root: continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in [
                    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.ico', '.heic', '.heif', '.svg', '.avif', '.jxl',
                    '.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.sr2', '.dng', '.raf', '.rw2', '.raw', '.orf', '.ori', 
                    '.rwl', '.pef', '.ptx', '.cap', '.iiq', '.eip', '.3fr', '.fff', '.dcr', '.kdc', '.dcs', '.drf', '.k25', '.mrw', 
                    '.srw', '.bay', '.x3f', '.erf', '.mef', '.mos', '.pxn', '.gpr', '.rwz', '.obm', '.qtk', '.rdc', '.mdc',
                    '.psd', '.psb', '.ai', '.indd', '.cdr', '.xcf', '.afphoto', '.afdesign', '.afpub', '.sketch', '.fig', '.kra', 
                    '.clip', '.lip', '.pspimage', '.psp', '.qxp', '.dwg', '.dxf', '.eps', '.ps',
                    '.obj', '.fbx', '.stl', '.blend', '.c4d', '.max', '.ma', '.mb', '.3ds', '.gltf', '.glb'
                ]: counts["Immagini"] += 1
                elif ext in [
                    '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.f4v', '.wmv', '.m4v', '.mpg', '.mpeg', '.m2v', '.3gp', '.3g2', 
                    '.ts', '.mts', '.m2ts', '.vob', '.ogv', '.divx', '.asf',
                    '.braw', '.r3d', '.ari', '.arx', '.mxf', '.cine', '.crm', '.mcw'
                ]: counts["Video"] += 1
                elif ext in ['.pdf', '.doc', '.docx', '.txt', '.xlsx', '.xls', '.pptx', '.csv']: counts["Documenti"] += 1
                else: counts["Altro"] += 1
                
        self.doc_filters = {}
        row_f = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
        row_f.pack()
        
        for ctype, count in counts.items():
            if count > 0:
                var = ctk.BooleanVar(value=True)
                self.doc_filters[ctype] = var
                chk = ctk.CTkCheckBox(row_f, text=f"{ctype} ({count})", variable=var)
                chk.pack(side="left", padx=10)

    def init_preview_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Preview"] = page

        self.preview_title = ctk.CTkLabel(page, text="Anteprima Organizzazione", font=ctk.CTkFont(size=22, weight="bold"))
        self.preview_title.pack(anchor="w", pady=(0, 10))
        
        # Table Header
        header_f = ctk.CTkFrame(page, fg_color="transparent")
        header_f.pack(fill="x", padx=10)
        ctk.CTkLabel(header_f, text="Struttura Cartelle / File", font=ctk.CTkFont(size=12, weight="bold"), text_color="gray").pack(side="left")
        ctk.CTkLabel(header_f, text="Accept", font=ctk.CTkFont(size=12, weight="bold"), text_color="gray").pack(side="right", padx=10)

        self.scroll_frame = ctk.CTkScrollableFrame(page, fg_color=("gray95", "gray10"))
        self.scroll_frame.pack(fill="both", expand=True, pady=(5, 10))

        footer = ctk.CTkFrame(page, fg_color="transparent")
        footer.pack(fill="x", side="bottom", pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(footer, height=12)
        self.progress_bar.pack(fill="x", pady=(0, 5)); self.progress_bar.set(0)
        self.status_lbl = ctk.CTkLabel(footer, text="In attesa di avvio...", font=ctk.CTkFont(size=12, weight="bold"))
        self.status_lbl.pack(side="left")

        ctk.CTkButton(footer, text="Conferma", width=120, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), command=self.execute_organization).pack(side="right")
        ctk.CTkButton(footer, text="Annulla", fg_color="transparent", border_width=1, width=100, command=self.cancel_organization).pack(side="right", padx=10)

    def init_settings_page(self):
        page = ctk.CTkScrollableFrame(self.content_container, fg_color="transparent", label_text="", border_width=0)
        self.pages["Settings"] = page

        ctk.CTkLabel(page, text="Impostazioni", font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", pady=(0, 20))

        # Configurazione FFMPEG Box
        ff_box = ctk.CTkFrame(page, corner_radius=10)
        ff_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(ff_box, text="Configurazione FFMPEG (Proxy Video)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        
        ff_row = ctk.CTkFrame(ff_box, fg_color="transparent")
        ff_row.pack(fill="x", padx=20, pady=5)
        
        self.ffmpeg_path_entry = ctk.CTkEntry(ff_row, width=450, placeholder_text="Lascia vuoto per cercare nel PATH...")
        if self.ffmpeg_path:
            self.ffmpeg_path_entry.insert(0, self.ffmpeg_path)
        self.ffmpeg_path_entry.pack(side="left", padx=(0, 10), fill="x", expand=True)
        
        btn_pick_ff = ctk.CTkButton(ff_row, text="📂 Sfoglia", width=100, command=self.pick_ffmpeg_path)
        btn_pick_ff.pack(side="left", padx=5)
        
        btn_test_ff = ctk.CTkButton(ff_row, text="⚡ Verifica", width=100, fg_color="#10b981", hover_color="#059669", command=self.test_ffmpeg_path)
        btn_test_ff.pack(side="left", padx=5)
        
        self.ffmpeg_status_lbl = ctk.CTkLabel(ff_box, text="Stato FFMPEG: In attesa di verifica", font=ctk.CTkFont(size=11), text_color="gray")
        self.ffmpeg_status_lbl.pack(anchor="w", padx=20, pady=(5, 5))
        # Esegui un controllo silenzioso iniziale
        self.after(500, lambda: self.test_ffmpeg_path(silent=True))

        # Riga per le impostazioni dei proxy (Risoluzione e Formato)
        proxy_settings_row = ctk.CTkFrame(ff_box, fg_color="transparent")
        proxy_settings_row.pack(fill="x", padx=20, pady=(5, 15))
        
        ctk.CTkLabel(proxy_settings_row, text="Risoluzione Proxy:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 10))
        self.proxy_resolution_menu = ctk.CTkOptionMenu(
            proxy_settings_row, 
            values=list(self.ai.PROXY_RESOLUTIONS.keys()),
            variable=self.proxy_resolution_var,
            command=lambda v: self.save_settings()
        )
        self.proxy_resolution_menu.pack(side="left", padx=(0, 30))
        
        ctk.CTkLabel(proxy_settings_row, text="Formato Proxy:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 10))
        self.proxy_format_menu = ctk.CTkOptionMenu(
            proxy_settings_row, 
            values=list(self.ai.PROXY_FORMATS),
            variable=self.proxy_format_var,
            command=lambda v: self.save_settings()
        )
        self.proxy_format_menu.pack(side="left")

        # Custom Rules Box
        rules_box = ctk.CTkFrame(page, corner_radius=10)
        rules_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(rules_box, text="Regole di Smistamento Personalizzate", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        
        form_row = ctk.CTkFrame(rules_box, fg_color="transparent")
        form_row.pack(fill="x", padx=20, pady=5)
        
        ctk.CTkLabel(form_row, text="Tipo:").pack(side="left", padx=5)
        self.rule_type_menu = ctk.CTkOptionMenu(form_row, values=["Estensione", "Nome contiene", "Dimensione > (MB)", "Dimensione < (MB)"], width=150)
        self.rule_type_menu.pack(side="left", padx=5)
        
        ctk.CTkLabel(form_row, text="Valore:").pack(side="left", padx=5)
        self.rule_value_entry = ctk.CTkEntry(form_row, width=150, placeholder_text="es. jpg,vacanza,10")
        self.rule_value_entry.pack(side="left", padx=5)
        
        ctk.CTkLabel(form_row, text="Cartella:").pack(side="left", padx=5)
        self.rule_folder_entry = ctk.CTkEntry(form_row, width=150, placeholder_text="es. Foto/JPG")
        self.rule_folder_entry.pack(side="left", padx=5)
        
        btn_add_rule = ctk.CTkButton(form_row, text="➕ Aggiungi", width=90, fg_color="#10b981", hover_color="#059669", command=self.add_custom_rule)
        btn_add_rule.pack(side="left", padx=10)
        
        self.rules_list_frame = ctk.CTkScrollableFrame(rules_box, height=150, fg_color=("gray90", "gray15"), label_text="Regole Attive")
        self.rules_list_frame.pack(fill="x", padx=20, pady=(5, 15))
        self.render_rules_list()

        # Hardware status
        hw_box = ctk.CTkFrame(page, corner_radius=10)
        hw_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(hw_box, text="Status Hardware", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        self.hw_info_lbl = ctk.CTkLabel(hw_box, text=f"Rilevato: {self.ai.hardware_info}", text_color="#38bdf8")
        self.hw_info_lbl.pack(anchor="w", padx=20, pady=(0, 15))

        # License
        lic_box = ctk.CTkFrame(page, corner_radius=10)
        lic_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(lic_box, text="Licenza", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        
        hwid_entry = ctk.CTkEntry(lic_box, width=450)
        hwid_entry.insert(0, f"HWID: {self.license.get_hwid()}")
        hwid_entry.configure(state="readonly")
        hwid_entry.pack(anchor="w", padx=20)
        
        btn_file = ctk.CTkButton(lic_box, text="📁 Carica File Licenza (.datarium)", command=self.load_license_file)
        btn_file.pack(anchor="w", padx=20, pady=10)

        self.lic_status_lbl = ctk.CTkLabel(lic_box, text=f"Stato: {self.license_status}", text_color="#10b981" if self.is_licensed else "#ef4444")
        self.lic_status_lbl.pack(anchor="w", padx=20, pady=(0, 15))

        # Updates
        upd_box = ctk.CTkFrame(page, corner_radius=10)
        upd_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(upd_box, text="Aggiornamenti Software", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(upd_box, text=f"Versione corrente: v{APP_VERSION}", text_color="gray").pack(anchor="w", padx=20)
        self.btn_check_upd = ctk.CTkButton(upd_box, text="Verifica Aggiornamenti", command=self.check_software_updates)
        self.btn_check_upd.pack(anchor="w", padx=20, pady=(10, 5))

        self.upd_progress = ctk.CTkProgressBar(upd_box)
        self.upd_progress.set(0)
        self.upd_progress.pack(fill="x", padx=20, pady=(5, 2))
        self.upd_status_lbl = ctk.CTkLabel(upd_box, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.upd_status_lbl.pack(anchor="w", padx=20, pady=(0, 15))

        # Test velocità disco (diagnosi hardware vs software)
        bench_box = ctk.CTkFrame(page, corner_radius=10)
        bench_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(bench_box, text="Test velocità disco", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(
            bench_box,
            text="Copia dati reali tra due cartelle e misura i MB/s, per capire se un rallentamento\n"
                 "dipende dai dischi/hub o dal software.",
            justify="left", text_color="gray"
        ).pack(anchor="w", padx=20, pady=(0, 10))

        bench_row = ctk.CTkFrame(bench_box, fg_color="transparent")
        bench_row.pack(fill="x", padx=20, pady=(0, 5))
        self.bench_source_entry = ctk.CTkEntry(bench_row, width=300, placeholder_text="Cartella sorgente (es. su HDD)")
        self.bench_source_entry.pack(side="left", padx=(0, 10))
        ctk.CTkButton(bench_row, text="Scegli", width=80, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.pick_bench_source).pack(side="left")

        bench_row2 = ctk.CTkFrame(bench_box, fg_color="transparent")
        bench_row2.pack(fill="x", padx=20, pady=(0, 10))
        self.bench_dest_entry = ctk.CTkEntry(bench_row2, width=300, placeholder_text="Cartella destinazione (es. su SSD)")
        self.bench_dest_entry.pack(side="left", padx=(0, 10))
        ctk.CTkButton(bench_row2, text="Scegli", width=80, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.pick_bench_dest).pack(side="left")

        bench_row3 = ctk.CTkFrame(bench_box, fg_color="transparent")
        bench_row3.pack(fill="x", padx=20, pady=(0, 5))
        ctk.CTkLabel(bench_row3, text="Limite dati (GB):").pack(side="left", padx=(0, 10))
        self.bench_size_entry = ctk.CTkEntry(bench_row3, width=70)
        self.bench_size_entry.insert(0, "20")
        self.bench_size_entry.pack(side="left", padx=(0, 20))
        self.btn_run_bench = ctk.CTkButton(bench_row3, text="Avvia test", fg_color="#10b981", hover_color="#059669", command=self.run_disk_benchmark)
        self.btn_run_bench.pack(side="left")

        self.bench_progress = ctk.CTkProgressBar(bench_box)
        self.bench_progress.set(0)
        self.bench_progress.pack(fill="x", padx=20, pady=(14, 2))

        self.bench_eta_lbl = ctk.CTkLabel(bench_box, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.bench_eta_lbl.pack(anchor="w", padx=20, pady=(0, 8))

        # Grafico a barre nativo (niente testo a muro): una barra per la lettura pura
        # e una per la copia end-to-end, con una linea tratteggiata sulla soglia oltre
        # la quale il rallentamento è compatibile con l'hardware, non col software.
        import tkinter as tk_native
        self.bench_chart_canvas = tk_native.Canvas(bench_box, height=95, highlightthickness=0, bd=0)
        self.bench_chart_canvas.pack(fill="x", padx=20, pady=(0, 5))
        self._bench_last_result = None
        self.bench_chart_canvas.bind("<Configure>", lambda e: self._redraw_bench_chart())

        self.bench_result_lbl = ctk.CTkLabel(bench_box, text="Nessun test eseguito.", font=ctk.CTkFont(weight="bold"), text_color="gray")
        self.bench_result_lbl.pack(anchor="w", padx=20, pady=(0, 15))

        # Disinstallazione / reset dati
        uninstall_box = ctk.CTkFrame(page, corner_radius=10)
        uninstall_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(uninstall_box, text="Disinstallazione", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(
            uninstall_box,
            text=f"I dati personali (licenza, modelli AI, cache volti, configurazione) sono in:\n{self.get_config_path().rsplit(os.sep, 1)[0]}",
            justify="left", text_color="gray"
        ).pack(anchor="w", padx=20, pady=(0, 10))
        ctk.CTkButton(
            uninstall_box, text="Disinstalla Datarium completamente...",
            fg_color="#ef4444", hover_color="#b91c1c", command=self.full_uninstall
        ).pack(anchor="w", padx=20, pady=(0, 15))

    def _bench_canvas_bg(self):
        mode = 0 if ctk.get_appearance_mode() == "Light" else 1
        try:
            fg = ctk.ThemeManager.theme["CTkFrame"]["fg_color"]
            return fg[mode] if isinstance(fg, (list, tuple)) else fg
        except Exception:
            return "#dbdbdb" if mode == 0 else "#2b2b2b"

    def _bench_text_color(self):
        return "#111827" if ctk.get_appearance_mode() == "Light" else "#e5e7eb"

    def _redraw_bench_chart(self):
        if not hasattr(self, "bench_chart_canvas") or not self.bench_chart_canvas.winfo_exists():
            return
        read_mbps, copy_mbps = self._bench_last_result if self._bench_last_result else (0, None)
        self._draw_bench_chart(read_mbps, copy_mbps)

    def _draw_bench_chart(self, read_mbps, copy_mbps=None):
        c = self.bench_chart_canvas
        c.delete("all")
        c.configure(bg=self._bench_canvas_bg())
        w = c.winfo_width()
        if w < 50:
            return

        text_color = self._bench_text_color()
        threshold = disk_benchmark.SLOW_HARDWARE_THRESHOLD_MBPS
        max_scale = max(read_mbps, copy_mbps or 0, threshold) * 1.3 or 1
        margin_left, margin_right = 60, 75
        track_w = max(w - margin_left - margin_right, 10)

        def bar(y, label, value, color, bar_h=26):
            bw = (min(value, max_scale) / max_scale) * track_w
            c.create_text(margin_left - 8, y + bar_h / 2, anchor="e", text=label, fill=text_color, font=("Segoe UI", 10))
            c.create_rectangle(margin_left, y, margin_left + track_w, y + bar_h, outline=text_color, width=1)
            if bw > 0:
                c.create_rectangle(margin_left, y, margin_left + bw, y + bar_h, fill=color, outline="")
            c.create_text(margin_left + track_w + 8, y + bar_h / 2, anchor="w", text=f"{value:.0f} MB/s",
                          fill=text_color, font=("Segoe UI", 10, "bold"))

        green, orange = "#10b981", "#f59e0b"
        bar(6, "Lettura", read_mbps, green if read_mbps >= threshold else orange)
        bottom = 6 + 26
        if copy_mbps is not None:
            bar(6 + 26 + 12, "Copia", copy_mbps, green if copy_mbps >= threshold else orange)
            bottom = 6 + 26 + 12 + 26

        threshold_x = margin_left + (min(threshold, max_scale) / max_scale) * track_w
        c.create_line(threshold_x, 2, threshold_x, bottom, dash=(3, 2), fill="#ef4444")
        c.create_text(threshold_x, bottom + 10, text=f"soglia bottleneck ({threshold:.0f} MB/s)", fill="#ef4444", font=("Segoe UI", 9))

    def pick_bench_source(self):
        d = filedialog.askdirectory(title="Scegli la cartella sorgente da leggere (es. i tuoi dati su HDD)")
        if d:
            self.bench_source_entry.delete(0, "end")
            self.bench_source_entry.insert(0, d)

    def pick_bench_dest(self):
        d = filedialog.askdirectory(title="Scegli la cartella destinazione dove scrivere (es. un SSD)")
        if d:
            self.bench_dest_entry.delete(0, "end")
            self.bench_dest_entry.insert(0, d)

    def run_disk_benchmark(self):
        from tkinter import messagebox
        import time
        source = self.bench_source_entry.get().strip()
        dest = self.bench_dest_entry.get().strip()
        if not source or not os.path.isdir(source):
            messagebox.showerror("Test Velocità Disco", "Scegli una cartella sorgente valida.")
            return
        try:
            size_limit = float(self.bench_size_entry.get().strip() or "20")
        except ValueError:
            size_limit = 20

        self.btn_run_bench.configure(state="disabled", text="Test in corso...")
        self.bench_progress.set(0)
        self.bench_eta_lbl.configure(text="")
        self.bench_result_lbl.configure(text="Lettura in corso dalla sorgente...", text_color="gray")

        def make_progress_updater():
            # Un cronometro per fase (lettura, poi copia), cosi' la stima del tempo
            # rimanente riparte pulita a ogni fase invece di trascinare la velocita' media
            # della fase precedente.
            state = {"start": time.time()}

            def reset():
                state["start"] = time.time()

            def update_progress(done, total):
                elapsed = max(0.001, time.time() - state["start"])
                speed_bps = done / elapsed
                remaining_bytes = max(0, total - done)
                eta_s = int(remaining_bytes / speed_bps) if speed_bps > 0 else 0
                speed_str = self.format_file_size(int(speed_bps)) + "/s"
                eta_str = (f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 60 else f"{eta_s}s")
                frac = min(done / total, 1.0) if total else 0
                self.after(0, lambda: self.bench_progress.set(frac))
                self.after(0, lambda: self.bench_eta_lbl.configure(
                    text=f"{self.format_file_size(done)} / {self.format_file_size(total)} · {speed_str} · tempo rimanente {eta_str}"
                ))

            return update_progress, reset

        def worker():
            try:
                update_progress, reset_timer = make_progress_updater()
                read_res = disk_benchmark.run_read_benchmark(source, size_limit_gb=size_limit, progress_callback=update_progress)
                copy_res = None
                if dest and os.path.isdir(dest):
                    self.after(0, lambda: self.bench_result_lbl.configure(text="Copia end-to-end verso la destinazione in corso..."))
                    self.after(0, lambda: self.bench_progress.set(0))
                    reset_timer()
                    copy_res = disk_benchmark.run_copy_benchmark(source, dest, size_limit_gb=size_limit, progress_callback=update_progress)

                copy_mbps = copy_res['mbps'] if copy_res else None
                verdict_mbps = min(read_res['mbps'], copy_mbps) if copy_mbps is not None else read_res['mbps']
                verdict_text = disk_benchmark.verdict(verdict_mbps)
                verdict_color = "#f59e0b" if verdict_mbps < disk_benchmark.SLOW_HARDWARE_THRESHOLD_MBPS else "#10b981"

                self._bench_last_result = (read_res['mbps'], copy_mbps)
                self.after(0, self._redraw_bench_chart)
                self.after(0, lambda: self.bench_result_lbl.configure(text=verdict_text, text_color=verdict_color))
            except Exception as e:
                self.after(0, lambda err=str(e): self.bench_result_lbl.configure(text=f"Errore durante il test: {err}", text_color="#ef4444"))
            finally:
                self.after(0, lambda: self.btn_run_bench.configure(state="normal", text="🧪 Avvia Test"))
                self.after(0, lambda: self.bench_progress.set(1))

        threading.Thread(target=worker, daemon=True).start()

    def full_uninstall(self):
        """
        Rimuove tutti i dati personali di Datarium (licenza, modelli AI, cache volti,
        configurazione) dalla cartella dati dell'app e, su Windows, avvia anche il
        disinstallatore ufficiale (Inno Setup) per rimuovere i file di programma.
        Su macOS/Linux non esiste un disinstallatore: dopo la pulizia dei dati si
        chiede all'utente di rimuovere manualmente l'app/AppImage (niente auto-delete
        del bundle in esecuzione: mai testato su queste piattaforme, troppo rischioso
        da automatizzare alla cieca). Azione distruttiva e irreversibile: richiede
        doppia conferma.
        """
        from tkinter import messagebox
        import platform
        data_dir = os.path.dirname(self.get_config_path())

        if not messagebox.askyesno(
            "Disinstalla Datarium",
            "Questa operazione elimina in modo IRREVERSIBILE:\n"
            "• la licenza attivata\n"
            "• i modelli AI scaricati (diversi GB)\n"
            "• la cache di riconoscimento volti\n"
            "• le impostazioni e le regole personalizzate\n\n"
            f"Cartella dati: {data_dir}\n\n"
            "Vuoi continuare?",
            icon="warning",
        ):
            return

        if not messagebox.askyesno("Conferma finale", "Sei assolutamente sicuro? L'operazione non può essere annullata."):
            return

        try:
            if os.path.isdir(data_dir):
                shutil.rmtree(data_dir, ignore_errors=True)
        except Exception as e:
            messagebox.showerror("Disinstalla Datarium", f"Errore durante la rimozione dei dati: {e}")
            return

        system = platform.system()
        if system == "Windows":
            # Prova a lanciare il disinstallatore ufficiale (creato da Inno Setup) per
            # rimuovere anche i file di programma; se non lo trova, si ferma qui: i dati
            # personali sono comunque già stati rimossi.
            uninstaller = None
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
                candidate = os.path.join(app_dir, "unins000.exe")
                if os.path.isfile(candidate):
                    uninstaller = candidate

            if uninstaller:
                messagebox.showinfo(
                    "Disinstalla Datarium",
                    "Dati personali rimossi. Ora verrà avviato il disinstallatore di Windows "
                    "per rimuovere anche i file di programma. Datarium si chiuderà."
                )
                import subprocess
                subprocess.Popen([uninstaller])
                self.after(300, lambda: os._exit(0))
                return
            messagebox.showinfo(
                "Disinstalla Datarium",
                "Dati personali rimossi con successo.\n"
                "Per rimuovere anche i file di programma, usa 'App installate' di Windows "
                "oppure 'Disinstalla Datarium' dal menu Start."
            )
        elif system == "Darwin":
            messagebox.showinfo(
                "Disinstalla Datarium",
                "Dati personali rimossi con successo.\n"
                "Per completare la disinstallazione, trascina Datarium dalla cartella "
                "Applicazioni al Cestino."
            )
        else:
            messagebox.showinfo(
                "Disinstalla Datarium",
                "Dati personali rimossi con successo.\n"
                "Per completare la disinstallazione, elimina il file AppImage di Datarium."
            )

    def pick_ffmpeg_path(self):
        file_path = filedialog.askopenfilename(title="Seleziona eseguibile ffmpeg", filetypes=[("Eseguibile ffmpeg", "ffmpeg.exe ffmpeg")])
        if file_path:
            self.ffmpeg_path_entry.delete(0, "end")
            self.ffmpeg_path_entry.insert(0, file_path)
            self.ffmpeg_path = file_path
            self.save_settings()
            self.test_ffmpeg_path()
            
    def test_ffmpeg_path(self, silent=False):
        if not hasattr(self, 'ffmpeg_path_entry') or not self.ffmpeg_path_entry.winfo_exists():
            return
        path = self.ffmpeg_path_entry.get().strip()
        self.ffmpeg_path = path
        self.save_settings()
        
        ok, msg = self.ai.check_ffmpeg(path if path else None)
        if ok:
            self.ffmpeg_status_lbl.configure(text=f"✓ FFMPEG Rilevato con successo: {msg}", text_color="#10b981")
            if not silent:
                from tkinter import messagebox
                messagebox.showinfo("FFMPEG", f"Verifica completata con successo!\nPercorso: {msg}")
        else:
            self.ffmpeg_status_lbl.configure(text=f"❌ Errore FFMPEG: {msg}", text_color="#ef4444")
            if not silent:
                from tkinter import messagebox
                messagebox.showerror("Errore FFMPEG", f"Impossibile avviare FFMPEG:\n{msg}")

    def render_rules_list(self):
        for w in self.rules_list_frame.winfo_children():
            w.destroy()
            
        if not self.custom_rules:
            ctk.CTkLabel(self.rules_list_frame, text="Nessuna regola definita. I file useranno la catalogazione AI.", text_color="gray", font=ctk.CTkFont(size=11, slant="italic")).pack(pady=10)
            return
            
        for idx, rule in enumerate(self.custom_rules):
            row = ctk.CTkFrame(self.rules_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            
            rule_text = f"SE {rule['type']} è '{rule['value']}' ➜ SPOSTA IN '{rule['folder']}'"
            ctk.CTkLabel(row, text=rule_text, font=ctk.CTkFont(size=11), anchor="w").pack(side="left", padx=10, fill="x", expand=True)
            
            btn_del = ctk.CTkButton(row, text="❌", width=30, height=22, fg_color="transparent", text_color="#ef4444", font=ctk.CTkFont(size=10, weight="bold"), command=lambda i=idx: self.delete_custom_rule(i))
            btn_del.pack(side="right", padx=10)
            
    def add_custom_rule(self):
        r_type = self.rule_type_menu.get()
        r_val = self.rule_value_entry.get().strip()
        r_folder = self.rule_folder_entry.get().strip()
        
        if not r_val or not r_folder:
            from tkinter import messagebox
            messagebox.showwarning("Dati incompleti", "Inserisci sia il valore che la cartella per aggiungere la regola.")
            return
            
        new_rule = {"type": r_type, "value": r_val, "folder": r_folder}
        self.custom_rules.append(new_rule)
        self.save_settings()
        
        self.rule_value_entry.delete(0, "end")
        self.rule_folder_entry.delete(0, "end")
        self.render_rules_list()
        
    def delete_custom_rule(self, index):
        if 0 <= index < len(self.custom_rules):
            self.custom_rules.pop(index)
            self.save_settings()
            self.render_rules_list()

    def send_local_notification(self, title, message):
        """Invia una notifica desktop locale in modo sicuro e senza dipendenze internet."""
        try:
            import importlib
            plyer = importlib.import_module("plyer")
            plyer.notification.notify(
                title=title,
                message=message,
                app_name="Datarium",
                timeout=5
            )
            return
        except Exception:
            pass
            
        try:
            if os.name == 'nt':
                # I valori vengono passati come variabili d'ambiente (NON interpolati nello
                # script): così apici o virgolette nei nomi file non possono rompere lo script
                # PowerShell né iniettare comandi.
                ps_script = (
                    '[void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");'
                    '$notification = New-Object System.Windows.Forms.NotifyIcon;'
                    '$notification.Icon = [System.Drawing.SystemIcons]::Information;'
                    '$notification.BalloonTipIcon = "Info";'
                    '$notification.BalloonTipTitle = $env:DATARIUM_NOTIF_TITLE;'
                    '$notification.BalloonTipText = $env:DATARIUM_NOTIF_TEXT;'
                    '$notification.Visible = $True;'
                    '$notification.ShowBalloonTip(5000);'
                )
                import subprocess
                env = os.environ.copy()
                env["DATARIUM_NOTIF_TITLE"] = str(title)
                env["DATARIUM_NOTIF_TEXT"] = str(message)
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    startupinfo=subprocess.STARTUPINFO(),
                    env=env
                )
                return
        except Exception:
            pass

    # --- LOGIC ---
    def load_license_file(self):
        file_path = filedialog.askopenfilename(title="Seleziona File Licenza", filetypes=[("Datarium License", "*.datarium")])
        if file_path:
            with open(file_path, "r") as f:
                token = f.read().strip()
            ok, msg = self.license.verify_license(token)
            if ok:
                self.license.save_license(token)
                self.is_licensed = True
                self.license_status = msg
                self.lic_status_lbl.configure(text=f"Licenza Attiva: {msg}", text_color="#10b981")
            else:
                self.lic_status_lbl.configure(text=f"Errore: {msg}", text_color="#ef4444")

    def _fetch_remote_version_info(self):
        """Interroga version.json. Ritorna il dict remoto o solleva un'eccezione."""
        import urllib.request
        import json
        import system_actions
        url = "https://nexflamma.net/version.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5, context=system_actions.https_context()) as response:
            return json.loads(response.read().decode())

    def _pick_platform_update_info(self, data):
        """
        version.json può avere un blocco per piattaforma ("windows"/"mac"/"linux"
        con download_url/sha256 propri) oltre ai campi top-level download_url/sha256
        (retrocompatibilità con la versione precedente del file, un solo installer
        per tutte le piattaforme). Se il blocco specifico manca, si ripiega sul
        top-level.
        """
        import platform
        key = {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")
        block = data.get(key) or {}
        return {
            "download_url": block.get("download_url") or data.get("download_url", ""),
            "sha256": block.get("sha256") or data.get("sha256", ""),
        }

    def _prompt_update_available(self, data):
        from tkinter import messagebox
        remote_version = data.get("version", APP_VERSION)
        changelog = data.get("changelog", "Miglioramenti generali.")
        info = self._pick_platform_update_info(data)
        msg = f"Una nuova versione di Datarium è disponibile: v{remote_version}!\n\nChangelog:\n{changelog}"
        if not info["download_url"]:
            msg += "\n\n(Nessun link di download disponibile per questa piattaforma.)"
            messagebox.showinfo("Nuovo Aggiornamento Disponibile", msg)
            return
        msg += "\n\nVuoi scaricarla e installarla ora?"
        if messagebox.askyesno("Nuovo Aggiornamento Disponibile", msg):
            self.show_page("Settings")
            self.start_self_update(info)
        else:
            # Non ripresentare lo stesso popup ad ogni ricontrollo periodico se
            # l'utente ha già detto no a QUESTA versione; una versione più nuova
            # farà comunque scattare un nuovo avviso.
            self._update_dismissed_version = remote_version

    def start_self_update(self, info):
        """
        Scarica l'installer in background con progresso reale, verifica il SHA-256
        (se fornito da version.json) e poi lo avvia: su Windows in modo silenzioso
        (l'utente non deve più cliccare 'Avanti' più volte), chiudendo Datarium subito
        dopo. Su macOS/Linux non esiste un install silenzioso sicuro da automatizzare
        alla cieca (DMG da montare, AppImage da sostituire): li apriamo/mostriamo
        appena scaricati e verificati, cosa comunque più efficiente di aprire solo
        il browser e lasciare che l'utente trovi da solo il link.
        """
        from tkinter import messagebox
        url = info["download_url"]
        sha256_expected = info.get("sha256", "")

        self.btn_check_upd.configure(state="disabled", text="Aggiornamento in corso...")
        self.upd_progress.set(0)
        self.upd_status_lbl.configure(text="Avvio download...")

        def worker():
            try:
                local_path = self._download_update_file(url)
                if sha256_expected:
                    self.after(0, lambda: self.upd_status_lbl.configure(text="Verifica integrità (SHA-256)..."))
                    actual = self.compute_hash(local_path, "SHA-256")
                    if not actual or actual.lower() != sha256_expected.lower():
                        try:
                            os.remove(local_path)
                        except Exception:
                            pass
                        raise RuntimeError(
                            "Il file scaricato non corrisponde all'hash atteso: download corrotto o "
                            "manomesso. Aggiornamento annullato per sicurezza."
                        )
                self.after(0, lambda: self._finish_self_update(local_path))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror("Aggiornamento fallito", err))
                self.after(0, lambda: self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti"))
                self.after(0, lambda: self.upd_status_lbl.configure(text=""))

        threading.Thread(target=worker, daemon=True).start()

    def _download_update_file(self, url):
        """Scarica url a un file temporaneo con progresso; ritorna il percorso locale.
        Usa urllib (stdlib), lo stesso approccio già in uso altrove nel codebase
        (_fetch_remote_version_info, ai_engine.py) — 'requests' non è tra le
        dipendenze installate, usarlo qui avrebbe fatto fallire il download."""
        import urllib.request
        import tempfile
        import time
        import system_actions
        name = os.path.basename(url.split("?")[0]) or "datarium_update.bin"
        local_path = os.path.join(tempfile.gettempdir(), name)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=30, context=system_actions.https_context()) as resp:
            total = int(resp.headers.get("Content-Length", 0)) or 0
            done = 0
            with open(local_path, "wb") as f:
                while True:
                    chunk = resp.read(512 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    frac = min(done / total, 1.0) if total else 0
                    d_str, t_str = self.format_file_size(done), self.format_file_size(total) if total else "?"
                    elapsed = time.time() - start_time
                    eta_str = ""
                    if total and elapsed > 0.2:
                        speed = done / elapsed
                        pct = int(frac * 100)
                        remaining_s = int(max(0, total - done) / speed) if speed > 0 else 0
                        eta_txt = f"{remaining_s // 60}m {remaining_s % 60}s" if remaining_s >= 60 else f"{remaining_s}s"
                        eta_str = f" · {pct}% · {self.format_file_size(int(speed))}/s · ETA {eta_txt}"
                    self.after(0, lambda v=frac: self.upd_progress.set(v))
                    self.after(0, lambda d=d_str, t=t_str, e=eta_str: self.upd_status_lbl.configure(text=f"Download: {d} / {t}{e}"))
        return local_path

    def _finish_self_update(self, local_path):
        from tkinter import messagebox
        import platform
        import subprocess
        system = platform.system()
        self.upd_progress.set(1)
        self.upd_status_lbl.configure(text="Download completato e verificato.")

        if system == "Windows":
            if messagebox.askyesno(
                "Aggiornamento pronto",
                "Download verificato. Datarium si chiuderà e l'installazione della nuova "
                "versione partirà automaticamente, senza altri click. Continuare?"
            ):
                subprocess.Popen([local_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
                self.after(300, lambda: os._exit(0))
                return
        elif system == "Darwin":
            messagebox.showinfo(
                "Aggiornamento scaricato",
                f"Il nuovo installer è stato verificato e scaricato in:\n{local_path}\n\n"
                "Si aprirà ora: trascina Datarium nella cartella Applicazioni per completare "
                "l'aggiornamento."
            )
            subprocess.Popen(["open", local_path])
        else:
            messagebox.showinfo(
                "Aggiornamento scaricato",
                f"Il nuovo AppImage è stato verificato e scaricato in:\n{local_path}\n\n"
                "Sostituisci il file precedente con questo per completare l'aggiornamento."
            )
            subprocess.Popen(["xdg-open", os.path.dirname(local_path)])

        self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti")

    def check_software_updates(self):
        """Verifica manuale (bottone): mostra sempre un esito, anche 'sei aggiornato' o errore."""
        from tkinter import messagebox
        self.btn_check_upd.configure(state="disabled", text="Verifica in corso...")

        def check_upd_bg():
            try:
                data = self._fetch_remote_version_info()
                remote_version = data.get("version", APP_VERSION)
                self.after(0, lambda: self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti"))
                if _is_newer_version(remote_version, APP_VERSION):
                    self.after(0, lambda: self._prompt_update_available(data))
                else:
                    self.after(0, lambda: messagebox.showinfo("Aggiornamenti", f"Il software è aggiornato alla versione più recente (v{APP_VERSION})!"))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti"))
                self.after(0, lambda: messagebox.showerror("Errore", f"Impossibile verificare gli aggiornamenti: {err}"))

        threading.Thread(target=check_upd_bg, daemon=True).start()

    def check_software_updates_silent(self, reschedule=True):
        """Verifica automatica: parla solo se c'e' davvero un aggiornamento. Nessun
        popup di errore/'sei aggiornato' per non disturbare l'utente (es. offline,
        DNS lento, server irraggiungibile).

        Si riprogrammano ogni ~2 ore per tutta la durata della sessione, non solo
        all'avvio: un utente che lascia Datarium aperto per ore (es. durante un
        Offload lungo) e non lo riavvia mai non vedrebbe altrimenti nessun
        aggiornamento pubblicato nel frattempo, con un solo controllo all'avvio."""
        def check_upd_bg():
            try:
                data = self._fetch_remote_version_info()
                remote_version = data.get("version", APP_VERSION)
                if (_is_newer_version(remote_version, APP_VERSION)
                        and remote_version != getattr(self, "_update_dismissed_version", None)):
                    self.after(0, lambda: self._prompt_update_available(data))
            except Exception:
                pass
            finally:
                if reschedule:
                    # self.after() non e' thread-safe se chiamato da un thread diverso
                    # da quello Tk: passiamo dal thread principale con self.after(0, ...).
                    self.after(0, lambda: self.after(2 * 60 * 60 * 1000, self.check_software_updates_silent))

        threading.Thread(target=check_upd_bg, daemon=True).start()

    def show_page(self, name):
        # Impedisci navigazione se è in corso una scansione
        if getattr(self, 'is_scanning', False):
            return

        # Ogni servizio deve essere sotto licenza, se non c'è licenza reindirizza a Settings
        self.is_licensed, self.license_status = self.license.verify_license()
        if not self.is_licensed and name not in ["Setup", "Settings"]:
            name = "Settings"
            if hasattr(self, 'lic_status_lbl'):
                self.lic_status_lbl.configure(text=f"Stato: {self.license_status} - Licenza necessaria per accedere ai servizi", text_color="#ef4444")

        # Se siamo in Setup, nascondiamo la sidebar per farlo sembrare un installer
        if name == "Setup":
            self.sidebar.grid_forget()
            self.grid_columnconfigure(0, weight=0)
        else:
            self.sidebar.grid(row=0, column=0, sticky="nsew")
            self.grid_columnconfigure(0, weight=0) # Sidebar width fixed
            
        if name == "HashHome":
            self._reset_hash_selection()
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self._update_nav_active(name)

    # Pagine reali -> voce di sidebar corrispondente (i flussi multi-step, es. Organizer
    # o Hash, restano evidenziati sulla loro voce anche nelle sotto-pagine).
    _NAV_PAGE_MAP = {
        "Home": "Home",
        "OrganizerHome": "Organizer", "Options": "Organizer", "Preview": "Organizer",
        "AutoTag": "AutoTag",
        "HashHome": "Hash", "HashOptions": "Hash", "HashResults": "Hash",
        "OffloadHome": "Offload", "OffloadResults": "Offload",
        "Sync": "Sync",
        "Settings": "Settings",
    }

    def _update_nav_active(self, page_name):
        active_key = self._NAV_PAGE_MAP.get(page_name)
        for key, btn in self._nav_buttons.items():
            try:
                btn.configure(**(self.NAV_ACTIVE if key == active_key else self.NAV_INACTIVE))
            except Exception:
                pass

    def change_appearance_mode(self, mode_str):
        mode = "Dark" if mode_str == "Scuro" else "Light"
        ctk.set_appearance_mode(mode)

    def set_sidebar_state(self, state="normal"):
        buttons = [self.btn_home, self.btn_organizer, self.btn_hash, self.btn_autotag, self.btn_offload, self.btn_sync, self.btn_settings]
        for btn in buttons:
            btn.configure(state=state)
        if hasattr(self, 'appearance_mode_segmented'):
            self.appearance_mode_segmented.configure(state=state)

    def open_source_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.source_folder.set(folder)
            # Per specifica utente: Destinazione e ZIP sono la cartella stessa
            self.control_folder.set(folder)
            self.backup_folder.set(folder)
            self.auto_detect_file_types(folder)
            self.show_page("Options")
            
    def open_dest_folder(self):
        folder = filedialog.askdirectory()
        if folder: self.control_folder.set(folder)

    def open_backup_folder(self):
        folder = filedialog.askdirectory()
        if folder: self.backup_folder.set(folder)

    def go_to_preview(self):
        # Re-check license status just before preview to catch revoked licenses
        self.is_licensed, self.license_status = self.license.verify_license()
        if not self.is_licensed:
            self.show_page("Settings")
            self.lic_status_lbl.configure(text=f"Stato: {self.license_status}", text_color="#ef4444")
            return
            
        self.show_page("Preview")
        self.is_scanning = True
        self.set_sidebar_state("disabled")
        self.stop_ai = False
        threading.Thread(target=self.process_files_bg, daemon=True).start()

    def cancel_organization(self):
        self.stop_ai = True
        self.is_scanning = False
        self.set_sidebar_state("normal")
        self.show_page("Options")

    # --- BG AI PROCESS ---
    def update_status(self, text):
        if self.status_lbl.winfo_exists():
            self.after(0, lambda: self.status_lbl.configure(text=text))

    def set_progress(self, val):
        import time
        if self.progress_bar.winfo_exists():
            pct = int(val * 100)
            self.after(0, lambda: self.progress_bar.set(val))
            # Aggiorna testo stato con percentuale e, quando si può stimare, il tempo
            # rimanente (elapsed/val proietta il tempo totale sulla frazione già fatta:
            # non serve tracciare i byte, la frazione stessa arriva già "pesata" dai
            # passi della pipeline AI).
            current = self.status_lbl.cget("text")
            base = current.split(" (")[0]
            suffix = f" ({pct}%)"
            if 0 < val < 1 and getattr(self, "_organize_start_time", None):
                elapsed = time.time() - self._organize_start_time
                remaining_s = int(elapsed * (1 - val) / val)
                eta_str = f"{remaining_s // 60}m {remaining_s % 60}s" if remaining_s >= 60 else f"{remaining_s}s"
                suffix = f" ({pct}% · ETA {eta_str})"
            self.after(0, lambda s=suffix: self.status_lbl.configure(text=f"{base}{s}"))

    def process_files_bg(self):
        import time
        try:
            for w in self.scroll_frame.winfo_children(): w.destroy()
            src = self.source_folder.get()
            if not src: return

            self._organize_start_time = time.time()
            self._review_count = 0
            self.set_progress(0)
            text_items = []
            vision_items = []
            
            for root, _, files in os.walk(src):
                if "Backup_Datarium_" in root: continue
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    skip = False
                    if ext in [
                        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.ico', '.heic', '.heif', '.svg', '.avif', '.jxl',
                        '.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.sr2', '.dng', '.raf', '.rw2', '.raw', '.orf', '.ori', 
                        '.rwl', '.pef', '.ptx', '.cap', '.iiq', '.eip', '.3fr', '.fff', '.dcr', '.kdc', '.dcs', '.drf', '.k25', '.mrw', 
                        '.srw', '.bay', '.x3f', '.erf', '.mef', '.mos', '.pxn', '.gpr', '.rwz', '.obm', '.qtk', '.rdc', '.mdc',
                        '.psd', '.psb', '.ai', '.indd', '.cdr', '.xcf', '.afphoto', '.afdesign', '.afpub', '.sketch', '.fig', '.kra', 
                        '.clip', '.lip', '.pspimage', '.psp', '.qxp', '.dwg', '.dxf', '.eps', '.ps',
                        '.obj', '.fbx', '.stl', '.blend', '.c4d', '.max', '.ma', '.mb', '.3ds', '.gltf', '.glb'
                    ]:
                        if not self.doc_filters.get("Immagini", ctk.BooleanVar(value=True)).get(): skip = True
                        else: vision_items.append({"old": f, "path": os.path.join(root, f), "type": "Image"})
                    elif ext in [
                        '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.f4v', '.wmv', '.m4v', '.mpg', '.mpeg', '.m2v', '.3gp', '.3g2', 
                        '.ts', '.mts', '.m2ts', '.vob', '.ogv', '.divx', '.asf',
                        '.braw', '.r3d', '.ari', '.arx', '.mxf', '.cine', '.crm', '.mcw'
                    ]:
                        if not self.doc_filters.get("Video", ctk.BooleanVar(value=True)).get(): skip = True
                        # Nei video (type="Video") l'AI vision analizza un frame estratto col
                        # proxy ffmpeg: vanno processati nella stessa fase "visione" delle
                        # immagini (dopo che il modello e' caricato), non prima come i testi.
                        else: vision_items.append({"old": f, "path": os.path.join(root, f), "type": "Video"})
                    elif ext in ['.pdf', '.doc', '.docx', '.txt', '.xlsx', '.xls', '.pptx', '.csv']:
                        if not self.doc_filters.get("Documenti", ctk.BooleanVar(value=True)).get(): skip = True
                        else: text_items.append({"old": f, "path": os.path.join(root, f), "type": "Doc"})
                    else: 
                        text_items.append({"old": f, "path": os.path.join(root, f), "type": "Other"})
            
            all_items = text_items + vision_items
            valid_items = []
            
            # Filtro duplicati: pre-filtro per dimensione. Due file identici hanno la stessa
            # dimensione, quindi calcoliamo l'hash (lettura completa) solo dove c'è una possibile
            # collisione, evitando di leggere per intero i file di dimensione unica (spesso video di GB).
            for item in all_items:
                try:
                    item['_size'] = os.path.getsize(item['path'])
                except OSError:
                    item['_size'] = -1
            size_counts = {}
            for item in all_items:
                size_counts[item['_size']] = size_counts.get(item['_size'], 0) + 1

            sh = {}
            for idx, item in enumerate(all_items):
                if self.stop_ai: return
                if self.check_dup.get() and size_counts.get(item['_size'], 0) > 1:
                    h = self.ai.compute_file_hash(item['path'])
                    if h in sh: item['skip'] = True
                    else: sh[h] = True
                if not item.get('skip'): valid_items.append(item)

            if not valid_items:
                self.update_status("❌ Nessun file compatibile trovato nella cartella.")
                self.set_progress(1.0)
                return

            # 1. ANALISI TESTI IN PARALLELO
            self.update_status("⚡ Analisi rapida documenti...")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                # Image e Video vengono analizzati dopo (fase 3), quando il modello vision e'
                # gia' caricato: i video usano un frame estratto via ffmpeg, non solo i metadata.
                future_to_item = {executor.submit(self.ai.extract_context, it['path'], self.scan_sidecars_var.get()): it for it in valid_items if it['type'] not in ("Image", "Video")}
                for future in concurrent.futures.as_completed(future_to_item):
                    if self.stop_ai: break
                    item = future_to_item[future]
                    item['context'] = future.result()
                    self.set_progress(0.1 + 0.2 * (len([x for x in valid_items if x.get('context')]) / max(1, len(valid_items))))

            # 2. CARICAMENTO AI (Testo o Visione)
            if self.check_ai.get():
                vision_needed = [it for it in valid_items if it['type'] in ("Image", "Video")]
                if not self.is_ai_loaded or (vision_needed and not self.ai.is_vision):
                    self.update_status("🧠 Caricamento Modello AI...")
                    success, err = self.ai.download_model_if_needed(vision_mode=bool(vision_needed), progress_callback=self.update_status)
                    if success:
                        self.is_ai_loaded = True

            # 3. ANALISI VISIONE SEQUENZIALE (Per non saturare la RAM)
            vision_needed = [it for it in valid_items if it['type'] in ("Image", "Video")]
            for idx, item in enumerate(vision_needed):
                if self.stop_ai: return
                self.update_status(f"👁️ Visione {idx+1}/{len(vision_needed)}: {item['old']}")
                item['context'] = self.ai.extract_context(item['path'], self.scan_sidecars_var.get())

                # Se la checkbox "Identifica persone nelle foto" è attiva, esegui il riconoscimento facciale con memoria
                # (solo sulle immagini: il rilevamento volti lavora su un file immagine, un video non è leggibile da cv2.imread)
                if self.organizer_identify_people.get() and item['type'] == "Image":
                    self.update_status(f"👤 Analisi volti: {item['old']}")
                    try:
                        faces, cv_img = self.face_mem.detect_faces(item['path'])
                        if faces:
                            identified_names = []
                            for f_idx, rect in enumerate(faces):
                                gray_crop, bgr_crop = self.face_mem.crop_face(cv_img, rect)
                                predicted_name, conf = self.face_mem.predict_face(gray_crop)
                                
                                if predicted_name:
                                    identified_names.append(predicted_name)
                                    print(f"[FaceMemory] Volto {f_idx+1}/{len(faces)} riconosciuto: {predicted_name} (conf: {conf:.1f})")
                                else:
                                    # Non riconosciuto, chiedi all'utente ritagliando il volto
                                    from PIL import Image
                                    bgr_rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
                                    pil_crop = Image.fromarray(bgr_rgb)
                                    
                                    user_input = None
                                    event = threading.Event()
                                    def ask_face(crop=pil_crop, idx=f_idx+1, total=len(faces)):
                                        nonlocal user_input
                                        dialog = FaceIdentificationDialog(self, crop, item['old'], idx, total)
                                        user_input = dialog.user_input
                                        event.set()
                                        
                                    self.after(0, ask_face)
                                    event.wait()
                                    
                                    if user_input and user_input.strip():
                                        new_name = user_input.strip()
                                        identified_names.append(new_name)
                                        self.face_mem.add_face(new_name, gray_crop)
                                        print(f"[FaceMemory] Nuovo volto registrato in memoria: '{new_name}'")
                                        
                            if identified_names:
                                # Rimuovi eventuali duplicati mantenendo l'ordine
                                unique_names = list(dict.fromkeys(identified_names))
                                names_str = ", ".join(unique_names)
                                item['context'] = (item.get('context', '') + f" Persone identificate dall'utente: {names_str}").strip()
                    except Exception as fe:
                        print(f"Errore analisi volti: {fe}")
                
                self.set_progress(0.3 + 0.4 * ((idx+1)/max(1, len(vision_needed))))

            # 4. TAXONOMY & SMART RENAME (Solo se AI attiva)
            if self.check_ai.get():
                self.update_status("🧠 Brainstorming Tassonomia Globale...")
                all_contexts = [it.get('context', '') for it in valid_items]
                taxonomy = self.ai.identify_global_themes(all_contexts)
                self.ai.keep_descriptive_names = self.organizer_keep_names.get()
                # Serie di file (pagine A/B/C, numerazioni): la cartella si decide UNA volta e vale
                # per tutti i membri. Coerenza garantita e una chiamata al modello in meno per file.
                series_folder = {}

                groups = {}
                for idx, item in enumerate(valid_items):
                    if self.stop_ai: return
                    self.update_status(f"🏷️ Organizzazione {idx+1}/{len(valid_items)}...")
                    
                    res = None
                    if self.use_custom_rules_var.get() and self.custom_rules:
                        res = self.ai.apply_custom_rules(item['path'], self.custom_rules)
                        
                    if not res:
                        skey = None
                        if self.ai.keep_descriptive_names and self.ai._is_descriptive_name(item['old']):
                            skey = self.ai.series_key(item['old'])
                            if skey:
                                skey = (item['type'], skey)
                        if skey and skey in series_folder:
                            res = f"{item['type']}/{series_folder[skey]}/{item['old']}"
                        else:
                            res = self.ai.get_smart_name(item['old'], item['type'], item.get('context', ''), taxonomy)
                            item['_ai'] = True
                            if skey:
                                parts_ = res.split('/')
                                if len(parts_) >= 4:
                                    series_folder[skey] = "/".join(parts_[1:-1])
                    item['new'] = res
                    
                    cat = res.split('/')[0]
                    if cat not in groups: groups[cat] = []
                    groups[cat].append(item)
                    self.set_progress(0.7 + 0.3 * ((idx+1)/max(1, len(valid_items))))
                
                # Post-elaborazione: (1) casi incerti -> "Da_Rivedere"; (2) foto/video dello stesso
                # evento (scatti ravvicinati) -> stessa cartella, per votazione.
                for it_ in valid_items:
                    if it_.get('_ai') and self._needs_review(it_):
                        it_['new'] = f"{it_['type']}/Da_Rivedere/{it_['old']}"
                        it_['_review'] = True
                try:
                    self._apply_event_clusters([
                        it_ for it_ in valid_items
                        if it_.get('_ai') and not it_.get('_review') and it_['type'] in ("Image", "Video")
                        and not self.ai._is_descriptive_name(it_['old'])])
                except Exception as ev_err:
                    print(f"[Organizer] Raggruppamento per evento saltato: {ev_err}")
                self._review_count = sum(1 for it_ in valid_items if it_.get('_review'))

                self.last_groups = groups
            else:
                # Fallback senza AI ma con regole custom applicabili!
                groups = {}
                for idx, item in enumerate(valid_items):
                    res = None
                    if self.use_custom_rules_var.get() and self.custom_rules:
                        res = self.ai.apply_custom_rules(item['path'], self.custom_rules)
                    if not res:
                        res = f"Archivio/Organizzato_{item['old']}"
                    item['new'] = res
                    
                    cat = res.split('/')[0]
                    if cat not in groups: groups[cat] = []
                    groups[cat].append(item)
                self.last_groups = groups

            n_rev = getattr(self, "_review_count", 0)
            self.update_status("✨ Analisi completata!" + (f" {n_rev} file in 'Da_Rivedere' (l'AI non era sicura)." if n_rev else ""))
            self.after(0, lambda: self.render_groups(self.last_groups))
            self.send_local_notification("Datarium - Analisi Completata", f"Analizzati con successo {len(valid_items)} file.")
        finally:
            self.is_scanning = False
            self.after(0, lambda: self.set_sidebar_state("normal"))

    def _needs_review(self, item):
        """True se l'esito dell'AI e' poco affidabile: percorso non valido, categoria di ripiego
        (Generale/Varie) o foto senza alcuna descrizione e con nome non descrittivo."""
        parts = str(item.get('new', '')).split('/')
        if len(parts) < 4:
            return True
        if parts[1].lower() == "generale" and parts[2].lower() in ("varie", "generale"):
            return True
        if item.get('type') == "Image" and "IMAGE_DESC" not in (item.get('context') or ""):
            return not self.ai._is_descriptive_name(item.get('old', ''))
        return False

    def _event_timestamp(self, item):
        """Data di scatto (EXIF) o di modifica come timestamp; None se non leggibile."""
        import datetime
        try:
            md = self.ai.extract_metadata(item['path'])
            s = md.get('DateTimeOriginal') or md.get('FileModificationDate')
            if s:
                return datetime.datetime.strptime(str(s)[:19], "%Y:%m:%d %H:%M:%S").timestamp()
        except Exception:
            pass
        try:
            return os.path.getmtime(item['path'])
        except Exception:
            return None

    def _apply_event_clusters(self, items, gap_seconds=1800):
        """Scatti ravvicinati (pausa < 30 min tra uno e l'altro, stesso tipo) = stesso evento.
        La cartella vincente (Categoria/Sottocategoria) e' quella scelta dalla maggioranza dei
        membri (almeno il 50%): gli altri la adottano, cosi' la foto della nonna e quella di
        gruppo della stessa festa non finiscono in posti diversi. Le foto con persone
        identificate restano dove sono."""
        from collections import Counter
        timed = []
        for it in items:
            ts = self._event_timestamp(it)
            if ts is not None:
                timed.append((ts, it))
        timed.sort(key=lambda x: x[0])
        clusters, cur, last = [], [], None
        for ts, it in timed:
            if cur and (ts - last > gap_seconds or it['type'] != cur[-1]['type']):
                clusters.append(cur)
                cur = []
            cur.append(it)
            last = ts
        if cur:
            clusters.append(cur)

        for cl in clusters:
            if len(cl) < 2:
                continue
            folders = []
            for it in cl:
                p = it['new'].split('/')
                folders.append("/".join(p[1:-1]) if len(p) >= 4 else None)
            counts = Counter(f for f in folders if f)
            if not counts:
                continue
            winner, n = counts.most_common(1)[0]
            if n / len(cl) < 0.5:
                continue
            for it, f in zip(cl, folders):
                if f and f != winner and "Persone_Identificate" not in f:
                    it['new'] = f"{it['type']}/{winner}/{it['new'].split('/')[-1]}"

    def render_groups(self, groups):
        for w in self.scroll_frame.winfo_children(): w.destroy()
        
        # Aggiorna Titolo
        src_path = self.source_folder.get()
        folder_name = os.path.basename(src_path)
        self.preview_title.configure(text=f"Cartella {folder_name} ({src_path})")

        # Costruiamo l'albero Tassonomia
        for cat, items in groups.items():
            # FRAME CATEGORIA (ACCORDION)
            cat_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            cat_frame.pack(fill="x", pady=2)
            
            content_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            # Inizia CHIUSO come richiesto dall'utente
            # content_frame.pack(fill="x", padx=20) # Non lo pacchiamo subito
            
            toggle_btn = ctk.CTkButton(cat_frame, text=f"📁 {cat} ^", anchor="w", fg_color=("#e2e8f0", "#1e293b"), text_color=("black", "white"), font=ctk.CTkFont(weight="bold"), 
                                     command=lambda f=content_frame: self.toggle_accordion(f))
            toggle_btn.pack(fill="x", side="left", expand=True)
            
            count_lbl = ctk.CTkLabel(cat_frame, text=f"{len(items)} file", font=ctk.CTkFont(size=11), text_color="gray")
            count_lbl.pack(side="right", padx=10)

            # Sottogruppi (Subcategories)
            subs = {}
            for it in items:
                parts = it['new'].split('/')
                # Formato atteso: Categoria/Sottocategoria/Nome.ext o Categoria/Nome.ext
                sub = parts[1] if len(parts) > 2 else None
                if sub not in subs: subs[sub] = []
                subs[sub].append(it)

            for sub, sub_items in subs.items():
                target_container = content_frame
                if sub:
                    sub_f = ctk.CTkFrame(content_frame, fg_color="transparent")
                    sub_f.pack(fill="x", pady=1, padx=10)
                    ctk.CTkLabel(sub_f, text=f"└─ 📂 {sub}", font=ctk.CTkFont(size=12, slant="italic")).pack(side="left")
                    target_container = ctk.CTkFrame(content_frame, fg_color="transparent")
                    target_container.pack(fill="x", padx=30)

                for it in sub_items:
                    row = ctk.CTkFrame(target_container, fg_color="transparent")
                    row.pack(fill="x", pady=1)
                    
                    # Nome file (senza path categoria)
                    display_name = it['new'].split('/')[-1]
                    ctk.CTkLabel(row, text=f"• {it['old']} ➜ {display_name}", font=ctk.CTkFont(size=12), wraplength=450, justify="left").pack(side="left", padx=5)
                    
                    it['check'] = ctk.BooleanVar(value=True)
                    ctk.CTkCheckBox(row, text="", variable=it['check'], width=20).pack(side="right", padx=5)

    def toggle_accordion(self, frame):
        if frame.winfo_viewable():
            frame.pack_forget()
        else:
            frame.pack(fill="x", padx=20, after=frame.master.winfo_children()[frame.master.winfo_children().index(frame)-1])

    def execute_organization(self):
        self.set_sidebar_state("disabled")
        self.is_scanning = True
        self.stop_ai = False
        
        def run_org_bg():
            try:
                dest = self.control_folder.get()
                src = self.source_folder.get()
                zip_dest_dir = src
                
                if not dest: return

                # 1. ZIP BACKUP PREVENTIVO (Sempre nella sorgente, con protezione ricorsione)
                self.update_status("📦 Creazione backup di sicurezza...")
                import datetime
                import zipfile
                
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                zip_name = f"Backup_Datarium_{timestamp}.zip"
                zip_path_full = os.path.join(zip_dest_dir, zip_name) 
                
                try:
                    # I file già compressi (foto/video/archivi/audio) vengono solo archiviati
                    # (ZIP_STORED): ricomprimerli con DEFLATE non riduce la dimensione ma rallenta
                    # enormemente il backup. I documenti restano compressi normalmente.
                    precompressed_exts = {
                        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.avif', '.jxl',
                        '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.mts', '.m2ts', '.mxf',
                        '.braw', '.r3d', '.wmv', '.flv', '.3gp',
                        '.zip', '.gz', '.7z', '.rar', '.mp3', '.aac', '.m4a', '.ogg', '.flac', '.opus'
                    }
                    with zipfile.ZipFile(zip_path_full, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        all_files = []
                        for root, dirs, files in os.walk(src):
                            for file in files:
                                all_files.append(os.path.join(root, file))

                        total = len(all_files)
                        for i, file_path in enumerate(all_files):
                            if self.stop_ai: break

                            fname = os.path.basename(file_path)
                            if fname.startswith("Backup_Datarium_") or fname == zip_name:
                                continue

                            rel_path = os.path.relpath(file_path, src)
                            ext = os.path.splitext(fname)[1].lower()
                            ctype = zipfile.ZIP_STORED if ext in precompressed_exts else zipfile.ZIP_DEFLATED
                            zipf.write(file_path, rel_path, compress_type=ctype)

                            if i % 10 == 0:
                                self.set_progress(0.01 + 0.09 * (i/max(1, total)))
                    
                    self.set_progress(0.1)
                except Exception as e:
                    from tkinter import messagebox
                    err = str(e)
                    self.after(0, lambda: messagebox.showerror("Errore Backup", f"Impossibile creare lo ZIP: {err}"))
                    return

                self.update_status("🚀 Riorganizzazione in corso...")
                to_proc = []
                for cat in self.last_groups.values():
                    for it in cat:
                        if it.get('check') and it['check'].get(): to_proc.append(it)

                for i, it in enumerate(to_proc):
                    if self.stop_ai: break
                    real_path = it['new']
                    if '/' in real_path:
                        real_path = real_path.split('/', 1)[1]
                    
                    target = os.path.join(dest, real_path)
                    
                    if os.path.abspath(it['path']) == os.path.abspath(target):
                        continue
                        
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    
                    base_target = target
                    counter = 1
                    while os.path.exists(target) and os.path.abspath(it['path']) != os.path.abspath(target):
                        name, ext = os.path.splitext(base_target)
                        target = f"{name}_{counter}{ext}"
                        counter += 1
                    
                    try:
                        shutil.move(it['path'], target)
                        
                        # Generazione video proxy se abilitata
                        if self.proxy_gen_var.get() and it['type'] == "Video":
                            proxy_dir = os.path.join(os.path.dirname(target), "Proxies")
                            self.ai.generate_proxy(
                                target, 
                                proxy_dir, 
                                ffmpeg_path=self.ffmpeg_path, 
                                progress_callback=self.update_status,
                                resolution=self.proxy_resolution_var.get(),
                                format_key=self.proxy_format_var.get()
                            )
                    except Exception as e:
                        print(f"Errore spostamento/proxy {it['old']}: {e}")
                        
                    self.set_progress(0.1 + 0.9 * ((i+1)/max(1, len(to_proc))))

                self.set_progress(1.0)
                self.update_status(f"✨ Completato! Folder riorganizzato e ZIP creato.")
                self.send_local_notification("Datarium - Riorganizzazione Completata", f"Elaborati con successo {len(to_proc)} file.")
            finally:
                self.is_scanning = False
                self.after(0, lambda: self.set_sidebar_state("normal"))

        import threading
        threading.Thread(target=run_org_bg, daemon=True).start()

    def init_hash_pages(self):
        # 1. Page: HashHome (Drawing 2 updated)
        page_home = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["HashHome"] = page_home

        # Centered frame for action buttons
        btn_row = ctk.CTkFrame(page_home, fg_color="transparent")
        btn_row.pack(anchor="center", pady=(0, 20))

        btn_file = ctk.CTkButton(btn_row, text="📂 Seleziona File", font=ctk.CTkFont(size=18, weight="bold"), height=60, width=280, corner_radius=12, command=self.pick_hash_file_home)
        btn_file.pack(side="left", padx=10)

        btn_folder = ctk.CTkButton(btn_row, text="📁 Seleziona Cartella", font=ctk.CTkFont(size=18, weight="bold"), height=60, width=280, corner_radius=12, command=self.pick_hash_folder_home)
        btn_folder.pack(side="left", padx=10)

        # Recent actions header below the buttons
        ctk.CTkLabel(page_home, text="Aperti di recente", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(10, 10))

        rec_f = ctk.CTkFrame(page_home, corner_radius=15, border_width=1, border_color=("gray85", "gray15"))
        rec_f.pack(fill="both", expand=True, padx=5, pady=5)

        # Scrollable recent actions frame
        self.recent_hash_scroll = ctk.CTkScrollableFrame(rec_f, fg_color="transparent")
        self.recent_hash_scroll.pack(fill="both", expand=True, padx=15, pady=15)
        self.update_recent_hash_ui()

        # 2. Page: HashOptions (Drawing 1)
        page_opts = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["HashOptions"] = page_opts

        modal = ctk.CTkFrame(page_opts, width=650, height=650, corner_radius=20, border_width=2, border_color=("gray80", "gray20"))
        modal.place(relx=0.5, rely=0.5, anchor="center")
        modal.pack_propagate(False)

        ctk.CTkLabel(modal, text="Selezione Hash", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(30, 20))

        # File Pick Row
        f_row = ctk.CTkFrame(modal, fg_color="transparent")
        f_row.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(f_row, text="File:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(f_row, textvariable=self.hash_source_file, text_color="gray", font=ctk.CTkFont(size=11), wraplength=320, anchor="w", justify="left").pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(f_row, text="📁", width=40, command=self.pick_hash_file).pack(side="right")
        ctk.CTkButton(f_row, text="✖", width=32, fg_color="transparent", border_width=1, text_color=("gray10", "gray90"), command=lambda: self._clear_hash_field("file")).pack(side="right", padx=(0, 6))

        # Folder Pick Row
        fold_row = ctk.CTkFrame(modal, fg_color="transparent")
        fold_row.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(fold_row, text="Cartella:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(fold_row, textvariable=self.hash_source_folder, text_color="gray", font=ctk.CTkFont(size=11), wraplength=320, anchor="w", justify="left").pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(fold_row, text="📂", width=40, command=self.pick_hash_folder).pack(side="right")
        ctk.CTkButton(fold_row, text="✖", width=32, fg_color="transparent", border_width=1, text_color=("gray10", "gray90"), command=lambda: self._clear_hash_field("folder")).pack(side="right", padx=(0, 6))

        # Folder 2 Pick Row
        fold_row_2 = ctk.CTkFrame(modal, fg_color="transparent")
        fold_row_2.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(fold_row_2, text="Cartella 2 (Confronto):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(fold_row_2, textvariable=self.hash_source_folder_2, text_color="gray", font=ctk.CTkFont(size=11), wraplength=250, anchor="w", justify="left").pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(fold_row_2, text="📂", width=40, command=self.pick_hash_folder_2).pack(side="right")
        ctk.CTkButton(fold_row_2, text="✖", width=32, fg_color="transparent", border_width=1, text_color=("gray10", "gray90"), command=lambda: self._clear_hash_field("folder2")).pack(side="right", padx=(0, 6))

        # Hash Algo
        algo_row = ctk.CTkFrame(modal, fg_color="transparent")
        algo_row.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(algo_row, text="Algoritmo Hash:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.algo_menu = ctk.CTkOptionMenu(algo_row, values=["-Scegli-", "SHA-256", "MD5", "SHA-1", "xxHash64"], variable=self.selected_hash_algo, width=140)
        self.algo_menu.pack(side="right")

        # Checkboxes Row
        check_row = ctk.CTkFrame(modal, fg_color="transparent")
        check_row.pack(fill="x", padx=40, pady=10)
        
        chk_dups = ctk.CTkCheckBox(check_row, text="Evidenzia File con stesso hash", variable=self.highlight_dups, font=ctk.CTkFont(size=13), command=self.toggle_compare_contents_visibility)
        chk_dups.pack(anchor="w", pady=3)
        
        self.chk_compare = ctk.CTkCheckBox(check_row, text="Confronta contenuto (rilegge i file: raddoppia i tempi)", variable=self.compare_contents, font=ctk.CTkFont(size=13))
        if self.highlight_dups.get():
            self.chk_compare.pack(anchor="w", pady=3, padx=(20, 0))

        # Verifica rapida e spegnimento (utile per dischi da centinaia di GB)
        opt_row2 = ctk.CTkFrame(modal, fg_color="transparent")
        opt_row2.pack(fill="x", padx=40, pady=(4, 0))
        ctk.CTkCheckBox(opt_row2, text="Verifica rapida (campiona 3 blocchi per file: molto piu' veloce, meno sicura)", variable=self.hash_quick_mode, font=ctk.CTkFont(size=12)).pack(anchor="w", pady=3)
        ctk.CTkCheckBox(opt_row2, text="Spegni il PC al termine (annullabile, solo se non ci sono differenze)", variable=self.hash_shutdown_after, font=ctk.CTkFont(size=12)).pack(anchor="w", pady=3)

        # Footer Row
        footer_btn_f = ctk.CTkFrame(modal, fg_color="transparent")
        footer_btn_f.pack(side="bottom", fill="x", padx=40, pady=30)
        ctk.CTkButton(footer_btn_f, text="Annulla", fg_color="transparent", border_width=2, width=120, command=lambda: self.show_page("HashHome")).pack(side="left")
        ctk.CTkButton(footer_btn_f, text="Conferma", width=140, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), command=self.run_hash_verification).pack(side="right")

        # 3. Page: HashResults (Drawing 3)
        page_results = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["HashResults"] = page_results

        # Barra di avanzamento e stato (visibili durante il calcolo degli hash)
        self.hash_progress_frame = ctk.CTkFrame(page_results, fg_color="transparent")
        self.hash_progress_frame.pack(fill="x", pady=(0, 5))
        self.hash_status_lbl = ctk.CTkLabel(self.hash_progress_frame, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self.hash_status_lbl.pack(anchor="w", padx=5)
        self.hash_progress_bar = ctk.CTkProgressBar(self.hash_progress_frame, height=10)
        self.hash_progress_bar.pack(fill="x", padx=5, pady=(2, 0))
        ctk.CTkLabel(self.hash_progress_frame, text="Passo 1: calcolo l'hash di ogni file, uno alla volta. Il confronto tra le cartelle avviene alla fine, per percorso.",
                     font=ctk.CTkFont(size=11), text_color="gray", anchor="w", justify="left", wraplength=700).pack(anchor="w", padx=5, pady=(2, 0))
        self.hash_progress_bar.set(0)

        # A single master scrollable frame to hold all tables/sections
        self.hash_results_scroll = ctk.CTkScrollableFrame(page_results, fg_color=("gray95", "gray10"))
        self.hash_results_scroll.pack(fill="both", expand=True, pady=(5, 10))

        # Bottom buttons
        bot_f = ctk.CTkFrame(page_results, fg_color="transparent")
        bot_f.pack(fill="x", side="bottom")
        ctk.CTkButton(bot_f, text="Indietro", fg_color="transparent", border_width=1, width=120, command=lambda: self.show_page("HashOptions")).pack(side="left")
        
        self.btn_export_hash = ctk.CTkButton(bot_f, text="📄 Esporta Report PDF", fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), command=self.export_hash_report)
        self.btn_export_hash.pack(side="right", padx=10)
        
        ctk.CTkButton(bot_f, text="Torna alla Home", width=140, fg_color="transparent", border_width=1, text_color=("gray10", "gray90"), command=lambda: self.show_page("HashHome")).pack(side="right")

    def toggle_compare_contents_visibility(self):
        if self.highlight_dups.get():
            self.chk_compare.pack(anchor="w", pady=3, padx=(20, 0))
        else:
            self.compare_contents.set(False)
            self.chk_compare.pack_forget()

    def _reset_hash_selection(self):
        """Azzera file e cartelle scelti: prima restavano in memoria da un uso precedente e
        finivano nel confronto (es. un video estraneo insieme alle due cartelle scelte)."""
        self.selected_hash_files_list = []
        self.hash_source_folders_list = []
        self.hash_source_file.set("")
        self.hash_source_folder.set("")
        self.hash_source_folder_2.set("")

    def _clear_hash_field(self, which):
        if which == "file":
            self.selected_hash_files_list = []
            self.hash_source_file.set("")
        elif which == "folder":
            self.hash_source_folders_list = []
            self.hash_source_folder.set("")
        else:
            self.hash_source_folder_2.set("")

    def pick_hash_file_home(self):
        file_paths = filedialog.askopenfilenames(title="Seleziona File")
        if file_paths:
            self._reset_hash_selection()
            self.selected_hash_files_list = list(file_paths)
            if len(self.selected_hash_files_list) == 1:
                self.hash_source_file.set(self.selected_hash_files_list[0])
            else:
                self.hash_source_file.set(f"{len(self.selected_hash_files_list)} file selezionati")
            self.show_page("HashOptions")

    def pick_hash_folder_home(self):
        folder_path = filedialog.askdirectory(title="Seleziona Cartella")
        if folder_path:
            self._reset_hash_selection()
            self.hash_source_folders_list = [folder_path]
            self.hash_source_folder.set(folder_path)
            self.show_page("HashOptions")

    def pick_hash_file(self):
        file_paths = filedialog.askopenfilenames(title="Seleziona File")
        if file_paths:
            self.selected_hash_files_list = list(file_paths)
            if len(self.selected_hash_files_list) == 1:
                self.hash_source_file.set(self.selected_hash_files_list[0])
            else:
                self.hash_source_file.set(f"{len(self.selected_hash_files_list)} file selezionati")

    def pick_hash_folder(self):
        folder_path = filedialog.askdirectory(title="Seleziona Cartella")
        if folder_path:
            self.hash_source_folder.set(folder_path)

    def pick_hash_folder_2(self):
        folder_path = filedialog.askdirectory(title="Seleziona Cartella di Confronto")
        if folder_path:
            self.hash_source_folder_2.set(folder_path)

    def update_recent_hash_ui(self):
        for w in self.recent_hash_scroll.winfo_children():
            w.destroy()
        
        if not self.recent_hash_files:
            ctk.CTkLabel(self.recent_hash_scroll, text="Nessun file aperto di recente.", text_color="gray", font=ctk.CTkFont(size=11)).pack(pady=10)
        else:
            for item in self.recent_hash_files:
                row = ctk.CTkFrame(self.recent_hash_scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                
                lbl = ctk.CTkLabel(row, text=os.path.basename(item), font=ctk.CTkFont(size=11), anchor="w", justify="left")
                lbl.pack(side="left", padx=5, fill="x", expand=True)
                
                btn = ctk.CTkButton(row, text="🔍 Scansiona", width=70, height=22, font=ctk.CTkFont(size=10), command=lambda p=item: self.select_recent_file(p))
                btn.pack(side="right", padx=5)

    def select_recent_file(self, path):
        if os.path.exists(path):
            self._reset_hash_selection()
            self.hash_source_file.set(path)
            self.show_page("HashOptions")
        else:
            from tkinter import messagebox
            messagebox.showwarning("File Non Trovato", "Il file selezionato non è più disponibile.")

    @staticmethod
    def _make_hasher(algo):
        import hashlib
        if algo == "MD5":
            return hashlib.md5()
        if algo == "SHA-1":
            return hashlib.sha1()
        if algo == "xxHash64":
            try:
                import xxhash
                return xxhash.xxh64()
            except ImportError:
                return hashlib.sha256()
        return hashlib.sha256()

    def compute_hash(self, file_path, algo="SHA-256", progress_cb=None, sampled=False):
        """Hash di un file con buffer riutilizzato da 8 MB. Con sampled=True legge solo 3 blocchi
        (inizio, meta', fine) piu' la dimensione: molto piu' veloce sui file enormi ma una
        VERIFICA PARZIALE (il risultato e' prefissato 'q-' per non confonderlo con un hash pieno)."""
        try:
            h = self._make_hasher(algo)
            CH = 8 * 1024 * 1024
            buf = bytearray(CH)
            view = memoryview(buf)
            with open(file_path, "rb", buffering=0) as f:
                if sampled:
                    size = os.fstat(f.fileno()).st_size
                    h.update(str(size).encode())
                    if size <= 3 * CH:
                        offsets = [0]
                        limits = [size]
                    else:
                        offsets = [0, max(0, size // 2 - CH // 2), size - CH]
                        limits = [CH, CH, CH]
                    for off, lim in zip(offsets, limits):
                        f.seek(off)
                        left = lim
                        while left > 0:
                            n = f.readinto(memoryview(buf)[:min(CH, left)])
                            if not n:
                                break
                            h.update(view[:n])
                            left -= n
                            if progress_cb:
                                progress_cb(n)
                    return "q-" + h.hexdigest()
                if hasattr(os, "posix_fadvise"):
                    try:
                        os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
                    except Exception:
                        pass
                while True:
                    n = f.readinto(buf)
                    if not n:
                        break
                    h.update(view[:n])
                    if progress_cb:
                        progress_cb(n)
            return h.hexdigest()
        except Exception as e:
            return f"Error: {e}"

    def compute_hashes(self, file_path, algos):
        """Calcola più hash in UNA SOLA lettura del file (evita di rileggerlo per ogni algoritmo).
        Ritorna un dizionario {algoritmo: hash_esadecimale}."""
        import hashlib
        hashers = {}
        for algo in algos:
            if algo == "MD5":
                hashers[algo] = hashlib.md5()
            elif algo == "SHA-1":
                hashers[algo] = hashlib.sha1()
            elif algo == "xxHash64":
                import xxhash
                hashers[algo] = xxhash.xxh64()
            else:
                hashers[algo] = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    for h in hashers.values():
                        h.update(chunk)
            return {a: getattr(h, "hexdigest")() for a, h in hashers.items()}
        except Exception as e:
            return {a: f"Error: {e}" for a in algos}

    def copy_write_and_hash(self, src_path, dest_paths, algos, chunk_size=4 * 1024 * 1024, prefetched_chunks=None, progress_callback=None):
        """
        Legge src_path UNA SOLA VOLTA, scrivendola contemporaneamente su tutte le
        dest_paths e calcolando gli hash richiesti sugli stessi byte letti.

        Se prefetched_chunks è già valorizzato (lista di bytes), il sorgente NON
        viene riletto da disco: si usano i byte già letti in anticipo da
        _prefetch_next_source() durante la verifica del file precedente (dischi
        diversi = lettura sorgente e verifica destinazione avvengono in parallelo
        senza contendersi lo stesso disco). Vedi offload_bg.

        Prima la pipeline di Offload leggeva il sorgente 1 volta per l'hash e poi
        di nuovo 1 volta per OGNI destinazione (shutil.copy2): con 3 dischi di backup
        erano 4 letture identiche dello stesso file. Su hardware lento (es. un hub USB
        con più HDD in parallelo) questo triplica/quadruplica il tempo reale di copia
        anche se il software "fa" la stessa cosa. Con questa funzione il sorgente si
        legge una volta sola, qualunque sia il numero di destinazioni.

        Le scritture sulle destinazioni avvengono ognuna nel proprio thread dedicato,
        con una coda di buffering per disco: se una destinazione è più lenta delle
        altre (disco/hub USB più lento) non blocca più le scritture sulle destinazioni
        veloci, che prima erano costrette ad aspettare il turno nello stesso ciclo
        sequenziale. Il thread di lettura scrive lo stesso chunk (bytes immutabile,
        condivisibile senza copie) in ogni coda; se una coda si riempie (destinazione
        molto più lenta delle altre) la lettura rallenta solo quel poco che serve a
        non far esplodere la memoria, ma non aspetta un turno round-robin come prima.

        La verifica di integrità (rilettura della destinazione) resta un passaggio
        separato: serve a scoprire corruzioni introdotte dalla scrittura stessa
        (dischi/cavi USB ballerini), quindi va tenuta. Per renderla veloce anche su
        file enormi, non rilegge più l'intero file: usa chunk_hashes (calcolati qui,
        un hash per ogni blocco di chunk_size byte, sul primo algoritmo di `algos`)
        per fare una verifica "a campione" con _verify_sampled_destinations() — vedi
        quel metodo per il trade-off esatto (copertura ridotta, non più il 100% dei byte).

        Se `progress_callback` è passato, viene richiamato con i byte letti dal
        sorgente finora (cumulativi su questo file) dopo ogni chunk: serve a far
        avanzare la percentuale/ETA anche DURANTE la copia di un singolo file
        grande, invece di aggiornarli solo a file completato (che su file da
        decine di GB lasciava la barra ferma per minuti).

        Ritorna (hashes: {algo: hexdigest}, write_ok: {dest_path: bool}, chunk_hashes: [str]).
        """
        import hashlib
        import queue
        import threading

        class _NullHasher:
            """Hasher 'nullo' per la modalita' 'Solo Dimensione': non calcola alcun checksum
            (nessun costo CPU), la verifica si affida solo al confronto delle dimensioni gia'
            fatto in _verify_sampled_destinations quando chunk_hashes e' vuoto/omogeneo."""
            def update(self, chunk):
                pass
            def hexdigest(self):
                return "N/A (solo dimensione)"

        def _new_hasher(algo):
            if algo == "MD5":
                return hashlib.md5()
            elif algo == "SHA-1":
                return hashlib.sha1()
            elif algo == "xxHash64":
                import xxhash
                return xxhash.xxh64()
            elif algo == "Solo Dimensione":
                return _NullHasher()
            else:
                return hashlib.sha256()

        hashers = {}
        for algo in algos:
            hashers[algo] = _new_hasher(algo)

        # Hash del PRIMO algoritmo, uno per ogni blocco letto, nello stesso ordine
        # in cui vengono scritti: serve alla verifica a campione più avanti per
        # confrontare un blocco riletto dalla destinazione senza dover ricalcolare
        # l'hash dell'intero file.
        chunk_algo = algos[0]
        chunk_hashes = []

        write_ok = {}
        handles = {}
        for d in dest_paths:
            try:
                handles[d] = open(d, "wb")
                write_ok[d] = True
            except Exception:
                write_ok[d] = False

        # Una coda + un thread scrittore per ogni destinazione scrivibile.
        # maxsize=8 chunk (32MB col default a 4MB/chunk) assorbe le differenze di
        # velocità momentanee tra dischi senza far crescere la memoria senza limite
        # se una destinazione resta stabilmente più lenta delle altre.
        queues = {}
        threads = {}

        def _writer(dest_path, fh, q):
            while True:
                item = q.get()
                if item is None:
                    break
                try:
                    fh.write(item)
                except Exception:
                    write_ok[dest_path] = False

        for d, fh in handles.items():
            if write_ok[d]:
                # Hint "lettura/scrittura sequenziale" al kernel su Mac/Linux (no-op
                # sicuro su Windows, dove posix_fadvise non esiste): permette al
                # sistema di fare readahead/writeback più aggressivo sapendo che il
                # file viene percorso dall'inizio alla fine, senza salti casuali.
                if hasattr(os, "posix_fadvise"):
                    try:
                        os.posix_fadvise(fh.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
                    except Exception:
                        pass
                q = queue.Queue(maxsize=8)
                queues[d] = q
                t = threading.Thread(target=_writer, args=(d, fh, q), daemon=True)
                t.start()
                threads[d] = t

        def _hash_chunk(chunk):
            h = _new_hasher(chunk_algo)
            h.update(chunk)
            return h.hexdigest()

        bytes_read = 0
        try:
            if prefetched_chunks is not None:
                for chunk in prefetched_chunks:
                    for h in hashers.values():
                        h.update(chunk)
                    chunk_hashes.append(_hash_chunk(chunk))
                    for d, q in queues.items():
                        if write_ok.get(d):
                            q.put(chunk)
                    bytes_read += len(chunk)
                    if progress_callback is not None:
                        progress_callback(bytes_read)
            else:
                with open(src_path, "rb") as fsrc:
                    if hasattr(os, "posix_fadvise"):
                        try:
                            os.posix_fadvise(fsrc.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
                        except Exception:
                            pass
                    while chunk := fsrc.read(chunk_size):
                        for h in hashers.values():
                            h.update(chunk)
                        chunk_hashes.append(_hash_chunk(chunk))
                        for d, q in queues.items():
                            if write_ok.get(d):
                                q.put(chunk)
                        bytes_read += len(chunk)
                        if progress_callback is not None:
                            progress_callback(bytes_read)
        finally:
            for d, q in queues.items():
                q.put(None)
            for t in threads.values():
                t.join()
            for fh in handles.values():
                try:
                    fh.close()
                except Exception:
                    pass

        for d in dest_paths:
            if write_ok.get(d):
                try:
                    shutil.copystat(src_path, d)
                except Exception:
                    pass

        hashes = {a: getattr(h, "hexdigest")() for a, h in hashers.items()}
        return hashes, write_ok, chunk_hashes

    def _verify_sampled_destinations(self, target_paths, chunk_hashes, chunk_size, algo, expected_size, max_samples=10):
        """
        Verifica "a campione": invece di rileggere l'INTERO file da ogni destinazione
        (come prima), rilegge solo una manciata di blocchi (max_samples, sempre incluso
        il primo e l'ultimo) e li confronta con l'hash calcolato per quel blocco durante
        la scrittura (chunk_hashes, da copy_write_and_hash). Più un controllo economico
        della dimensione totale del file, che da solo intercetta scritture troncate
        (disco pieno, cavo staccato a metà).

        TRADE-OFF ESPLICITO accettato per la velocità: questo NON è più equivalente a
        rileggere il 100% dei byte come prima. Su un file con centinaia di blocchi,
        campionandone una decina la probabilità di NON accorgersi di una corruzione
        isolata in un punto non campionato è concreta (non più ~0% come con la rilettura
        completa). Intercetta comunque con alta affidabilità i fallimenti "grossi"
        (scrittura troncata, blocco iniziale/finale corrotto, disco disconnesso).

        Ritorna {target_path: bool}.
        """
        import hashlib
        import concurrent.futures

        def _hasher(a):
            if a == "MD5":
                return hashlib.md5()
            elif a == "SHA-1":
                return hashlib.sha1()
            elif a == "xxHash64":
                import xxhash
                return xxhash.xxh64()
            else:
                return hashlib.sha256()

        n_chunks = len(chunk_hashes)
        if n_chunks == 0:
            sample_indices = []
        elif n_chunks <= max_samples:
            sample_indices = list(range(n_chunks))
        else:
            # sempre il primo e l'ultimo, il resto distribuito uniformemente nel file
            step = (n_chunks - 1) / (max_samples - 1)
            sample_indices = sorted(set(round(i * step) for i in range(max_samples)))

        def _check_one(target_path):
            try:
                if os.path.getsize(target_path) != expected_size:
                    return False
                with open(target_path, "rb") as f:
                    for idx in sample_indices:
                        f.seek(idx * chunk_size)
                        block = f.read(chunk_size)
                        h = _hasher(algo)
                        h.update(block)
                        if h.hexdigest() != chunk_hashes[idx]:
                            return False
                return True
            except Exception:
                return False

        if not target_paths:
            return {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(target_paths)) as pool:
            return dict(zip(target_paths, pool.map(_check_one, target_paths)))

    # Soglia oltre la quale NON si pre-legge il file successivo in memoria: file
    # RAW/ProRes molto grandi (decine di GB) rischierebbero di saturare la RAM.
    # Sotto la soglia il guadagno è reale (nessuna doppia lettura del sorgente),
    # sopra si torna al comportamento normale (nessuna regressione, solo nessun bonus).
    PREFETCH_MAX_BYTES = 1024 * 1024 * 1024  # 1 GB

    def _prefetch_next_source(self, path, chunk_size=4 * 1024 * 1024):
        """
        Legge path per intero in memoria (lista di chunk), pensato per essere
        chiamato in un thread separato MENTRE il file precedente è in fase di
        verifica (rilettura delle destinazioni): sorgente e destinazioni sono
        quasi sempre dischi fisicamente diversi (es. scheda SD della camera ->
        HDD di backup), quindi questa lettura non contende banda con la verifica
        in corso. Se il file supera PREFETCH_MAX_BYTES o si verifica un errore,
        ritorna None: il chiamante farà una normale lettura da disco più avanti,
        senza alcuna regressione.
        """
        try:
            size = os.path.getsize(path)
            if size > self.PREFETCH_MAX_BYTES:
                return None
            chunks = []
            with open(path, "rb") as f:
                if hasattr(os, "posix_fadvise"):
                    try:
                        os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
                    except Exception:
                        pass
                while chunk := f.read(chunk_size):
                    chunks.append(chunk)
            return chunks
        except Exception:
            return None

    def check_content_equal(self, f1, f2):
        try:
            if os.path.getsize(f1) != os.path.getsize(f2):
                return False
            size = 4 * 1024 * 1024
            with open(f1, "rb", buffering=0) as a, open(f2, "rb", buffering=0) as b:
                while True:
                    ch1 = a.read(size)
                    ch2 = b.read(size)
                    if ch1 != ch2:
                        return False
                    if not ch1:
                        return True
        except Exception:
            return False

    def create_section_header(self, parent, text):
        f = ctk.CTkFrame(parent, fg_color=("#cbd5e1", "#334155"), height=35, corner_radius=5)
        f.pack(fill="x", pady=(15, 5))
        f.pack_propagate(False)
        ctk.CTkLabel(f, text=text, font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=15)
        return f

    def create_table_header(self, parent):
        tbl_hdr = ctk.CTkFrame(parent, height=30, fg_color="transparent")
        tbl_hdr.pack(fill="x", pady=2)
        tbl_hdr.columnconfigure(0, weight=3)
        tbl_hdr.columnconfigure(1, weight=1)
        tbl_hdr.columnconfigure(2, weight=5)
        tbl_hdr.columnconfigure(3, weight=1)
        
        ctk.CTkLabel(tbl_hdr, text="Nome File", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").grid(row=0, column=0, padx=10, sticky="ew")
        ctk.CTkLabel(tbl_hdr, text="Tipo", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").grid(row=0, column=1, padx=10, sticky="ew")
        ctk.CTkLabel(tbl_hdr, text="Hash", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").grid(row=0, column=2, padx=10, sticky="ew")
        ctk.CTkLabel(tbl_hdr, text="Dimensione", font=ctk.CTkFont(size=11, weight="bold"), anchor="e").grid(row=0, column=3, padx=10, sticky="ew")

    def populate_section(self, parent, items, bg_color="transparent", text_color=None, limit=500):
        if not items:
            ctk.CTkLabel(parent, text="Nessun file trovato in questa sezione.", text_color="gray", font=ctk.CTkFont(size=12, slant="italic")).pack(pady=15)
            return

        if len(items) > limit:
            ctk.CTkLabel(parent, text=f"Mostrati i primi {limit} di {len(items)} file (l'elenco completo e' nel report PDF).",
                         text_color="gray", font=ctk.CTkFont(size=11, slant="italic")).pack(pady=(4, 2))
        for it in items[:limit]:
            row_frame = ctk.CTkFrame(parent, fg_color=bg_color, corner_radius=5)
            row_frame.pack(fill="x", pady=2)
            row_frame.columnconfigure(0, weight=3)
            row_frame.columnconfigure(1, weight=1)
            row_frame.columnconfigure(2, weight=5)
            row_frame.columnconfigure(3, weight=1)

            ctk.CTkLabel(row_frame, text=it['name'], text_color=text_color, font=ctk.CTkFont(size=12, weight="bold" if it.get('is_source') else "normal"), anchor="w", justify="left").grid(row=0, column=0, padx=10, pady=4, sticky="ew")
            ctk.CTkLabel(row_frame, text=it['type'], text_color=text_color, font=ctk.CTkFont(size=12), anchor="w", justify="left").grid(row=0, column=1, padx=10, pady=4, sticky="ew")
            
            lbl_hash = ctk.CTkLabel(row_frame, text=it['hash'], text_color=text_color, font=ctk.CTkFont(size=11), anchor="w", justify="left", wraplength=350)
            lbl_hash.grid(row=0, column=2, padx=10, pady=4, sticky="ew")
            lbl_hash.bind("<Button-1>", lambda e, hv=it['hash']: self.copy_to_clipboard(hv))

            ctk.CTkLabel(row_frame, text=it['size'], text_color=text_color, font=ctk.CTkFont(size=11), anchor="e", justify="right").grid(row=0, column=3, padx=10, pady=4, sticky="ew")

    def run_hash_verification(self):
        for w in self.hash_results_scroll.winfo_children():
            w.destroy()

        sd = self.hash_source_folder.get()
        sd_list = []
        if sd:
            sd_list.append(sd)
            
        sd2 = self.hash_source_folder_2.get()
        if sd2 and sd2 not in sd_list:
            sd_list.append(sd2)
            
        algo = self.selected_hash_algo.get()
        if algo == "-Scegli-":
            # xxHash64 e' molto piu' veloce di SHA-256 e basta per verificare copie/backup
            try:
                import xxhash  # noqa: F401
                algo = "xxHash64"
            except ImportError:
                algo = "SHA-256"

        files_to_hash = []
        if self.selected_hash_files_list:
            files_to_hash = list(self.selected_hash_files_list)
        elif self.hash_source_file.get():
            files_to_hash = [self.hash_source_file.get()]

        if len(sd_list) == 2 and files_to_hash:
            # Confronto tra due cartelle: un file "extra" falsa il risultato, lo si esclude
            files_to_hash = []

        if not files_to_hash and not sd_list:
            from tkinter import messagebox
            messagebox.showwarning("Selezione Mancante", "Seleziona almeno un file o una cartella da controllare.")
            return

        self.show_page("HashResults")
        self.is_scanning = True
        self.set_sidebar_state("disabled")
        self.hash_progress_bar.set(0)
        self.hash_status_lbl.configure(text="Preparazione calcolo hash...")

        self._hash_quick = self.hash_quick_mode.get()
        self._hash_shutdown = self.hash_shutdown_after.get()
        threading.Thread(target=self._run_hash_verification_bg, args=(files_to_hash, sd_list, algo), daemon=True).start()

    def _update_hash_progress(self, idx, total, name, bytes_done=None, total_bytes=None, elapsed=None):
        """Aggiorna barra e stato del calcolo hash (thread UI). Barra e percentuale usano la
        STESSA scala (byte, prima la barra contava i file e la percentuale i byte: due numeri
        diversi). I dati importanti vengono per primi e il nome del file, accorciato, per ultimo:
        prima una riga lunga usciva dalla finestra e l'ETA non si vedeva."""
        have_bytes = bytes_done is not None and total_bytes
        if hasattr(self, 'hash_progress_bar') and self.hash_progress_bar.winfo_exists():
            frac = (bytes_done / total_bytes) if have_bytes else ((idx + 1) / max(1, total))
            self.hash_progress_bar.set(min(1.0, max(0.0, frac)))
        if hasattr(self, 'hash_status_lbl') and self.hash_status_lbl.winfo_exists():
            short = name if len(name) <= 34 else name[:31] + "..."
            parts = []
            if have_bytes and elapsed is not None and elapsed > 0.05:
                speed = bytes_done / elapsed
                pct = min(100, int(bytes_done / total_bytes * 100))
                parts.append(f"{pct}%")
                parts.append(f"{self.format_file_size(int(speed))}/s")
                if elapsed >= 3 and speed > 0:
                    remaining_s = int(max(0, total_bytes - bytes_done) / speed)
                    if remaining_s >= 3600:
                        eta_str = f"{remaining_s // 3600}h {(remaining_s % 3600) // 60}m"
                    elif remaining_s >= 60:
                        eta_str = f"{remaining_s // 60}m {remaining_s % 60}s"
                    else:
                        eta_str = f"{remaining_s}s"
                    parts.append(f"ETA {eta_str}")
                else:
                    parts.append("ETA calcolo...")
            parts.append(f"file {idx + 1}/{total}")
            parts.append(short)
            self.hash_status_lbl.configure(text=" · ".join(parts), wraplength=700, justify="left")

    def _run_hash_verification_bg(self, files_to_hash, sd_list, algo):
        import system_actions
        # PC sveglio per tutta la durata (calcoli da decine di minuti o di ore: altrimenti la
        # sospensione notturna li interrompe), come gia' in Offload.
        sleep_guard = system_actions.SleepInhibitor()
        sleep_guard.__enter__()
        quick = bool(getattr(self, "_hash_quick", False))
        shutdown_after = bool(getattr(self, "_hash_shutdown", False))
        try:
            import time
            import threading as _th
            from concurrent.futures import ThreadPoolExecutor

            results = []
            source_paths = set()

            # 1. Lista completa dei file: (path, is_source, root, rel)
            tasks = []
            for sf in files_to_hash:
                if os.path.exists(sf):
                    ap = os.path.abspath(sf)
                    if ap not in source_paths:
                        source_paths.add(ap)
                        tasks.append((sf, True, None, os.path.basename(sf)))

            for sd in sd_list:
                if os.path.isdir(sd):
                    for root, _, files in os.walk(sd):
                        for f in files:
                            p = os.path.join(root, f)
                            if os.path.abspath(p) in source_paths:
                                continue
                            tasks.append((p, False, sd, os.path.relpath(p, sd)))

            total = len(tasks)
            if total == 0:
                self.after(0, self._render_hash_results, results)
                return

            sizes = []
            for t_ in tasks:
                try:
                    sizes.append(os.path.getsize(t_[0]))
                except Exception:
                    sizes.append(0)
            # Byte realmente da leggere (in modalita' rapida sono solo i blocchi campionati)
            work = [min(s, 3 * 8 * 1024 * 1024) if quick else s for s in sizes]
            total_bytes = sum(work)

            # 2. Raggruppa per disco fisico: gruppi su dischi diversi girano IN PARALLELO
            #    (il tempo totale e' quello del disco piu' lento, non la somma); file sullo
            #    stesso disco restano sequenziali per non far "sbattere" le testine di un HDD.
            def _dev(path):
                try:
                    return os.stat(path).st_dev
                except Exception:
                    return None
            groups = {}
            for idx, t_ in enumerate(tasks):
                groups.setdefault(_dev(t_[0]), []).append(idx)
            # Stesso percorso relativo = file uno accanto all'altro: nel confronto di due cartelle
            # si vede lo stesso nome due volte di fila (A e B) invece di nomi che "saltano".
            for g_ in groups.values():
                g_.sort(key=lambda i_: (tasks[i_][3].lower(), str(tasks[i_][2])))

            out = [None] * total
            lock = _th.Lock()
            state = {"bytes": 0, "done": 0, "last_ui": 0.0, "cur": {}}
            start_time = time.time()

            def _push_ui(name, force=False):
                now = time.time()
                with lock:
                    if not force and now - state["last_ui"] < 0.25:
                        return
                    state["last_ui"] = now
                    bd, dn = state["bytes"], state["done"]
                    state["cur"][_th.get_ident()] = name
                    shown = list(dict.fromkeys(state["cur"].values()))
                disp = shown[0] if len(shown) == 1 else " | ".join(shown)
                el = now - start_time
                self.after(0, lambda: self._update_hash_progress(min(dn, total - 1), total, disp, bd, total_bytes, el))

            def _worker(indices):
                for idx in indices:
                    p, is_source, root, rel = tasks[idx]
                    name = os.path.basename(p)

                    def _cb(n, name=name):
                        with lock:
                            state["bytes"] += n
                        _push_ui(name)

                    hash_val = self.compute_hash(p, algo, progress_cb=_cb, sampled=quick)
                    ext = os.path.splitext(p)[1].upper().replace('.', '')
                    out[idx] = {
                        "name": name, "path": p, "type": ext if ext else "FILE",
                        "hash": hash_val, "size": self.format_file_size(sizes[idx]),
                        "is_source": is_source, "root": root, "rel": rel,
                    }
                    with lock:
                        state["done"] += 1
                    _push_ui(name, force=True)

            with ThreadPoolExecutor(max_workers=max(1, min(len(groups), 4))) as ex:
                list(ex.map(_worker, groups.values()))

            results = [r for r in out if r]
            for r in results:
                if r["is_source"] and r["path"] not in self.recent_hash_files:
                    self.recent_hash_files.insert(0, r["path"])
                    self.recent_hash_files = self.recent_hash_files[:10]
            self.after(0, self.update_recent_hash_ui)

            self.hash_last_algo = algo + (" (verifica rapida)" if quick else "")
            self.after(0, self._render_hash_results, results)

            # Spegnimento a fine lavoro: solo se le due cartelle non presentano differenze
            # (altrimenti l'utente deve poter vedere il risultato prima).
            if shutdown_after:
                comp = self.build_hash_comparison(results)
                clean = (comp is None and not any(str(r.get("hash", "")).startswith("Error") for r in results)) or (
                    comp is not None and not (comp["different"] or comp["only_a"] or comp["only_b"] or comp["moved"]))
                if clean:
                    ok_sd, msg_sd, sd_handle = system_actions.shutdown_computer(60)
                    if ok_sd:
                        self._pending_shutdown_handle = sd_handle
                        self.after(0, lambda: self._show_shutdown_countdown("Verifica hash completata."))
                else:
                    from tkinter import messagebox
                    self.after(0, lambda: messagebox.showwarning(
                        "Spegnimento annullato",
                        "Il confronto ha rilevato differenze o errori: lo spegnimento automatico e' stato annullato per farti controllare il risultato."))
        finally:
            sleep_guard.__exit__(None, None, None)
            self.is_scanning = False
            self.after(0, lambda: self.set_sidebar_state("normal"))

    @staticmethod
    def build_hash_comparison(results):
        """Confronta i file di DUE cartelle per percorso relativo. Ritorna None se le
        cartelle non sono due, altrimenti un dict con: identical, different, only_a,
        only_b, moved (stesso hash ma percorso diverso)."""
        roots = []
        for r in results:
            if r.get("root") and r["root"] not in roots:
                roots.append(r["root"])
        if len(roots) != 2:
            return None
        a_root, b_root = roots
        a = {r["rel"]: r for r in results if r.get("root") == a_root}
        b = {r["rel"]: r for r in results if r.get("root") == b_root}
        same, diff, only_a, only_b = [], [], [], []
        for rel, ra in a.items():
            rb = b.get(rel)
            if rb is None:
                only_a.append(ra)
            elif ra["hash"] == rb["hash"] and not ra["hash"].startswith("Error"):
                same.append((ra, rb))
            else:
                diff.append((ra, rb))
        for rel, rb in b.items():
            if rel not in a:
                only_b.append(rb)
        moved = []
        b_by_hash = {}
        for rb in only_b:
            b_by_hash.setdefault(rb["hash"], []).append(rb)
        for ra in list(only_a):
            cands = b_by_hash.get(ra["hash"])
            if cands and not ra["hash"].startswith("Error"):
                moved.append((ra, cands.pop(0)))
                only_a.remove(ra)
        moved_b = {id(m[1]) for m in moved}
        only_b = [rb for rb in only_b if id(rb) not in moved_b]
        return {"a_root": a_root, "b_root": b_root, "identical": same, "different": diff,
                "only_a": only_a, "only_b": only_b, "moved": moved}

    def _render_hash_results(self, results):
        self.last_hash_results = results
        if hasattr(self, 'hash_progress_bar') and self.hash_progress_bar.winfo_exists():
            self.hash_progress_bar.set(1.0)
        if hasattr(self, 'hash_status_lbl') and self.hash_status_lbl.winfo_exists():
            self.hash_status_lbl.configure(text=f"✓ Completato: {len(results)} file elaborati")

        hash_counts = {}
        for r in results:
            hash_counts[r['hash']] = hash_counts.get(r['hash'], 0) + 1

        hash_groups = {}
        for r in results:
            hash_groups.setdefault(r['hash'], []).append(r)

        dup_hash_files = [r for r in results if hash_counts.get(r['hash'], 0) > 1]

        comp = self.build_hash_comparison(results)
        self.last_hash_comparison = comp
        if comp:
            self._render_hash_comparison(comp)

        self.create_section_header(self.hash_results_scroll, "📋 Tutti i file e gli hash")
        self.create_table_header(self.hash_results_scroll)
        self.populate_section(self.hash_results_scroll, results)

        self.create_section_header(self.hash_results_scroll, "🔄 File con hash uguale")
        self.create_table_header(self.hash_results_scroll)
        self.populate_section(self.hash_results_scroll, dup_hash_files, bg_color=("#ffedd5", "#7c2d12"), text_color=("#ea580c", "#fb923c"))

        if self.compare_contents.get() and self.highlight_dups.get():
            to_check = [items for items in hash_groups.values() if len(items) > 1]
            if to_check:
                # Rilegge i file: in background, con avanzamento. Prima girava QUI, sul thread
                # dell'interfaccia, e su cartelle da centinaia di GB la finestra restava
                # congelata (rotella su Mac) per tutta la durata.
                self.is_scanning = True
                self.set_sidebar_state("disabled")
                self.hash_progress_bar.set(0)
                self.hash_status_lbl.configure(text="Confronto byte per byte dei file con hash uguale...")
                threading.Thread(target=self._content_compare_bg, args=(to_check,), daemon=True).start()

    def _content_compare_bg(self, groups):
        import time
        try:
            n_pairs = sum(len(g) - 1 for g in groups)
            done = 0
            start = time.time()
            dup_content_files = []
            for items in groups:
                ref_item = items[0]
                valid_items = [ref_item]
                for other in items[1:]:
                    el = time.time() - start
                    eta = f" · ETA {int(el * (n_pairs - done) / done) // 60}m" if done and el > 5 else ""
                    self.after(0, lambda d=done, nm=other['name'], e=eta: (
                        self.hash_progress_bar.set(d / max(1, n_pairs)),
                        self.hash_status_lbl.configure(text=f"Confronto contenuto {d + 1}/{n_pairs}{e} · {nm[:34]}")))
                    if self.check_content_equal(ref_item['path'], other['path']):
                        valid_items.append(other)
                    done += 1
                if len(valid_items) > 1:
                    dup_content_files.extend(valid_items)
            self.after(0, self._render_content_compare, dup_content_files)
        except Exception as e:
            self.after(0, lambda err=str(e): self.hash_status_lbl.configure(text=f"Confronto contenuto interrotto: {err}"))
        finally:
            self.is_scanning = False
            self.after(0, lambda: self.set_sidebar_state("normal"))

    def _render_content_compare(self, dup_content_files):
        self.hash_progress_bar.set(1.0)
        self.hash_status_lbl.configure(text=f"✓ Completato: {len(self.last_hash_results)} file elaborati, contenuto verificato")
        self.create_section_header(self.hash_results_scroll, "📦 File con hash uguale e contenuto uguale")
        self.create_table_header(self.hash_results_scroll)
        self.populate_section(self.hash_results_scroll, dup_content_files, bg_color=("#ffedd5", "#7c2d12"), text_color=("#ea580c", "#fb923c"))

    def _render_hash_comparison(self, comp):
        """Verdetto file-per-file tra Cartella 1 e Cartella 2 (abbinati per percorso relativo)."""
        n_ok, n_diff = len(comp["identical"]), len(comp["different"])
        n_a, n_b, n_mv = len(comp["only_a"]), len(comp["only_b"]), len(comp["moved"])
        all_ok = not (n_diff or n_a or n_b or n_mv)
        self.create_section_header(self.hash_results_scroll, "⚖️ Confronto Cartella 1 ↔ Cartella 2")
        verdict = "✅ Le due cartelle sono IDENTICHE" if all_ok else "⚠️ Le due cartelle NON coincidono"
        ctk.CTkLabel(self.hash_results_scroll, text=verdict, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#10b981" if all_ok else "#ef4444").pack(anchor="w", padx=10, pady=(2, 2))
        ctk.CTkLabel(self.hash_results_scroll,
                     text=f"{n_ok} identici · {n_diff} diversi · {n_a} solo in Cartella 1 · {n_b} solo in Cartella 2 · {n_mv} stesso contenuto/percorso diverso",
                     font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w", padx=10, pady=(0, 6))

        def _rows(title, items, color, note=None):
            if not items:
                return
            self.create_section_header(self.hash_results_scroll, title)
            for item in items:
                row = ctk.CTkFrame(self.hash_results_scroll, fg_color=color, corner_radius=5)
                row.pack(fill="x", pady=2)
                if isinstance(item, tuple):
                    txt = item[0]['rel'] if item[0]['rel'] == item[1]['rel'] else f"{item[0]['rel']}  ↔  {item[1]['rel']}"
                    sub = f"1: {item[0]['hash'][:16]}…   2: {item[1]['hash'][:16]}…   ({item[0]['size']})"
                else:
                    txt, sub = item['rel'], f"{note}  ({item['size']})"
                ctk.CTkLabel(row, text=txt, font=ctk.CTkFont(size=12, weight="bold"), anchor="w", justify="left", wraplength=700).pack(anchor="w", padx=10, pady=(4, 0))
                ctk.CTkLabel(row, text=sub, font=ctk.CTkFont(size=11), anchor="w", text_color="gray").pack(anchor="w", padx=10, pady=(0, 4))

        red = ("#fee2e2", "#7f1d1d")
        amber = ("#ffedd5", "#7c2d12")
        _rows(f"❌ Contenuto DIVERSO ({n_diff})", comp["different"], red)
        _rows(f"⚠️ Solo in Cartella 1 ({n_a})", comp["only_a"], amber, "manca in Cartella 2")
        _rows(f"⚠️ Solo in Cartella 2 ({n_b})", comp["only_b"], amber, "manca in Cartella 1")
        _rows(f"↔️ Stesso contenuto, percorso diverso ({n_mv})", comp["moved"], amber)

    def copy_to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        from tkinter import messagebox
        messagebox.showinfo("Copiato", "Valore Hash copiato negli appunti!")

    def export_hash_report(self):
        if not hasattr(self, 'last_hash_results') or not self.last_hash_results:
            from tkinter import messagebox
            messagebox.showwarning("Nessun Dato", "Nessun risultato disponibile per l'esportazione.")
            return
        
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = f"HASH_{timestamp}"
        
        # Cartella di output: usa quella del primo file o la home
        output_dir = os.path.dirname(self.last_hash_results[0]['path']) if self.last_hash_results else os.path.expanduser("~")
        report_dir = os.path.join(output_dir, "Hash_Reports")
        
        from report_generator import ReportGenerator
        try:
            report_path = ReportGenerator.save_hash_report(report_dir, report_id, self.last_hash_results, getattr(self, 'hash_last_algo', None) or self.selected_hash_algo.get(), comparison=getattr(self, 'last_hash_comparison', None))
            import webbrowser
            webbrowser.open(pathlib.Path(report_path).absolute().as_uri())
            from tkinter import messagebox
            messagebox.showinfo("Report Generato", f"Report esportato con successo ed aperto nel browser:\n{report_path}")
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Errore Esportazione", f"Impossibile salvare il report: {e}")

    def format_file_size(self, size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def init_autotag_page(self):
        self.autotag_master_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["AutoTag"] = self.autotag_master_frame

        self.autotag_views = {}

        # 1. AUTOTAG HOME (Drawing 1)
        v_home = ctk.CTkFrame(self.autotag_master_frame, fg_color="transparent")
        self.autotag_views["Home"] = v_home

        ctk.CTkLabel(v_home, text="Auto Tagging intelligente", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))
        
        recent_box = ctk.CTkFrame(v_home, corner_radius=15, border_width=1, border_color=("gray85", "gray15"))
        recent_box.pack(fill="both", expand=True, padx=5, pady=5)
        
        ctk.CTkLabel(recent_box, text="Progetti recenti", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=30, pady=(30, 5))
        ctk.CTkLabel(recent_box, text="I tuoi album digitali e progetti organizzati appariranno qui.", text_color="gray", font=ctk.CTkFont(slant="italic")).pack(anchor="w", padx=30)

        # Center Crea Album button
        btn_crea = ctk.CTkButton(recent_box, text="➕ Crea Album", font=ctk.CTkFont(size=16, weight="bold"), width=220, height=55, corner_radius=10, fg_color="#10b981", hover_color="#059669", command=lambda: self.show_autotag_subpage("Config"))
        btn_crea.place(relx=0.5, rely=0.55, anchor="center")

        # 2. AUTOTAG CONFIG (Drawing 3)
        v_config = ctk.CTkFrame(self.autotag_master_frame, fg_color="transparent")
        self.autotag_views["Config"] = v_config

        ctk.CTkLabel(v_config, text="Configura Nuovo Album", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))

        cfg_box = ctk.CTkFrame(v_config, width=700, height=520, corner_radius=15, border_width=1, border_color=("gray85", "gray15"))
        cfg_box.pack(pady=5)
        cfg_box.pack_propagate(False)

        # Inputs grid
        g = ctk.CTkFrame(cfg_box, fg_color="transparent")
        g.pack(fill="x", padx=40, pady=(40, 10))
        g.columnconfigure(1, weight=1)

        # Row 1: Cartella Foto
        ctk.CTkLabel(g, text="Cartella Foto:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=0, column=0, sticky="w", pady=15)
        self.ent_at_src = ctk.CTkEntry(g, textvariable=self.autotag_source_folder, font=ctk.CTkFont(size=12), height=35)
        self.ent_at_src.grid(row=0, column=1, padx=(15, 10), sticky="ew")
        ctk.CTkButton(g, text="📂", width=45, height=35, command=self.pick_autotag_source).grid(row=0, column=2)

        # Row 2: Cartella Destinazione
        ctk.CTkLabel(g, text="Cartella Destinazione:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=1, column=0, sticky="w", pady=15)
        self.ent_at_dst = ctk.CTkEntry(g, textvariable=self.autotag_dest_folder, font=ctk.CTkFont(size=12), height=35)
        self.ent_at_dst.grid(row=1, column=1, padx=(15, 10), sticky="ew")
        ctk.CTkButton(g, text="📂", width=45, height=35, command=self.pick_autotag_dest).grid(row=1, column=2)

        # Checkboxes
        chk_frame = ctk.CTkFrame(cfg_box, fg_color="transparent")
        chk_frame.pack(fill="x", padx=40, pady=10)

        self.chk_ai_scan = ctk.CTkCheckBox(chk_frame, text="Accetta che l'AI scansioni le foto e i video", variable=self.autotag_accept_ai, font=ctk.CTkFont(size=13))
        self.chk_ai_scan.pack(anchor="w", pady=8)

        self.chk_at_rename = ctk.CTkCheckBox(chk_frame, text="Rinomina e organizza in Album", variable=self.autotag_rename, font=ctk.CTkFont(size=13))
        self.chk_at_rename.pack(anchor="w", pady=8)

        # Actions
        act_frame = ctk.CTkFrame(cfg_box, fg_color="transparent")
        act_frame.pack(fill="x", side="bottom", padx=40, pady=35)
        ctk.CTkButton(act_frame, text="Annulla", fg_color="transparent", border_width=1, width=120, height=40, command=lambda: self.show_autotag_subpage("Home")).pack(side="left")
        self.btn_confirm_at = ctk.CTkButton(act_frame, text="Conferma", fg_color="#10b981", hover_color="#059669", width=140, height=40, font=ctk.CTkFont(weight="bold"), command=self.run_autotag_analysis)
        self.btn_confirm_at.pack(side="right")

        # 3. AUTOTAG RESULTS / ALBUM (Drawing 2)
        v_results = ctk.CTkFrame(self.autotag_master_frame, fg_color="transparent")
        self.autotag_views["Album"] = v_results

        ctk.CTkLabel(v_results, text="I tuoi Album Intelligenti", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))
        
        self.autotag_album_scroll = ctk.CTkScrollableFrame(v_results, fg_color=("gray95", "gray10"))
        self.autotag_album_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        res_foot = ctk.CTkFrame(v_results, fg_color="transparent")
        res_foot.pack(fill="x", side="bottom", pady=(10, 0))
        ctk.CTkButton(res_foot, text="Indietro", fg_color="transparent", border_width=1, width=120, command=lambda: self.show_autotag_subpage("Config")).pack(side="left")
        ctk.CTkButton(res_foot, text="Salva e Organizza", fg_color="#10b981", hover_color="#059669", width=160, font=ctk.CTkFont(weight="bold"), command=self.rename_and_create_albums).pack(side="right")

        # Start on Home view
        self.show_autotag_subpage("Home")

    def show_autotag_subpage(self, name):
        for v in self.autotag_views.values():
            v.pack_forget()
        self.autotag_views[name].pack(fill="both", expand=True)

    def pick_autotag_source(self):
        folder = filedialog.askdirectory(title="Seleziona Cartella Foto")
        if folder:
            self.autotag_source_folder.set(folder)

    def pick_autotag_dest(self):
        folder = filedialog.askdirectory(title="Seleziona Cartella Destinazione")
        if folder:
            self.autotag_dest_folder.set(folder)

    # Estensioni che Auto Tag sa leggere: foto (anche RAW), video (anche BRAW/R3D/MXF...) e documenti.
    AUTOTAG_EXTS = frozenset([
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.heif', '.avif',
        '.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.sr2', '.dng', '.raf', '.rw2', '.orf', '.pef', '.srw',
        '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg', '.m2v', '.3gp',
        '.ts', '.mts', '.m2ts', '.vob', '.braw', '.r3d', '.ari', '.arx', '.mxf', '.cine', '.crm',
        '.pdf', '.docx', '.doc', '.txt',
    ])

    def run_autotag_analysis(self):
        src = self.autotag_source_folder.get()
        dst = self.autotag_dest_folder.get()
        if not src or not dst:
            from tkinter import messagebox
            messagebox.showwarning("Selezione Mancante", "Seleziona entrambe le cartelle per procedere.")
            return

        self.btn_confirm_at.configure(state="disabled", text="⚡ Scansione...")
        self.is_scanning = True
        self.set_sidebar_state("disabled")

        for w in self.autotag_album_scroll.winfo_children():
            w.destroy()

        def scan_bg():
            try:
                import time
                
                # Pre-caricamento del modello AI se necessario
                if self.autotag_accept_ai.get() and not self.is_ai_loaded:
                    self.after(0, lambda: self.btn_confirm_at.configure(text="🧠 Caricamento AI..."))
                    success, err = self.ai.download_model_if_needed(vision_mode=True, progress_callback=None)
                    if success:
                        self.is_ai_loaded = True
                
                self.after(0, lambda: self.btn_confirm_at.configure(text="⚡ Scansione..."))
                valid_files = []
                for root, _, files in os.walk(src):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in self.AUTOTAG_EXTS and not f.startswith('._'):
                            valid_files.append(os.path.join(root, f))

                if not valid_files:
                    self.after(0, lambda: self.btn_confirm_at.configure(state="normal", text="Conferma"))
                    self.after(0, lambda: self.show_autotag_subpage("Config"))
                    from tkinter import messagebox
                    self.after(0, lambda: messagebox.showinfo("Nessun file", "Nessun file leggibile (foto, video o documenti) trovato nella cartella selezionata."))
                    return

                # Group files into albums based on AI/metadata
                # 1) documenti (pdf/docx/txt) letti in PARALLELO; foto/video in sequenza (un solo
                #    modello vision in memoria). 2) nome album per file, riusando quello gia'
                #    dato a un contesto identico (frame/descrizioni uguali = stessa risposta).
                # Avanzamento con percentuale ed ETA reali sul pulsante.
                import concurrent.futures
                total_steps = max(1, 2 * len(valid_files))
                state = {"done": 0, "t0": time.time(), "last": 0.0}

                def _tick(label):
                    state["done"] += 1
                    now = time.time()
                    if now - state["last"] < 0.4 and state["done"] < total_steps:
                        return
                    state["last"] = now
                    frac = state["done"] / total_steps
                    el = max(now - state["t0"], 0.001)
                    eta = int(el * (1 - frac) / frac) if frac > 0.02 else None
                    eta_txt = (f" · ETA {eta // 60}m {eta % 60}s" if eta and eta >= 60 else (f" · ETA {eta}s" if eta is not None else ""))
                    txt = f"{label} {int(frac * 100)}%{eta_txt}"
                    self.after(0, lambda tx=txt: self.btn_confirm_at.configure(text=tx))

                doc_exts = ('.pdf', '.docx', '.doc', '.txt')
                contexts = {}
                doc_files = [p for p in valid_files if os.path.splitext(p)[1].lower() in doc_exts]
                media_files = [p for p in valid_files if os.path.splitext(p)[1].lower() not in doc_exts]

                if doc_files:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                        futs = {ex.submit(self.ai.extract_context, p): p for p in doc_files}
                        for fut in concurrent.futures.as_completed(futs):
                            try:
                                contexts[futs[fut]] = fut.result()
                            except Exception:
                                contexts[futs[fut]] = ""
                            _tick("👁️ Analisi")
                for p in media_files:
                    try:
                        # Il modello vision e' gia' caricato sopra: extract_context descrive anche i
                        # video (frame estratto via ffmpeg); senza frame usa nome/cartelle/ffprobe.
                        contexts[p] = self.ai.extract_context(p)
                    except Exception:
                        contexts[p] = ""
                    _tick("👁️ Analisi")

                albums = {}
                album_cache = {}
                for path in valid_files:
                    try:
                        context = contexts.get(path) or ""
                        if not context:
                            album_name = "Varie"
                        elif context in album_cache:
                            album_name = album_cache[context]
                        else:
                            album_name = self.ai.get_album_name(context)
                            album_cache[context] = album_name
                        # Clean filename characters
                        for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
                            album_name = album_name.replace(ch, "")
                        album_name = album_name.capitalize()
                        albums.setdefault(album_name, []).append(path)
                    except Exception:
                        albums.setdefault("Ricordi", []).append(path)
                    _tick("🏷️ Tag")

                self.current_albums = albums

                def update_album_ui():
                    # Raggruppa gli album con 1 solo file in "Altri Elementi" per evitare "una cartella per immagine"
                    visual_albums = {}
                    for album, files in self.current_albums.items():
                        if len(files) == 1:
                            visual_albums.setdefault("Altri Elementi", []).extend(files)
                        else:
                            visual_albums.setdefault(album, []).extend(files)
                    self.current_albums = visual_albums

                    self._render_album_grid()

                    self.btn_confirm_at.configure(state="normal", text="Conferma")
                    self.show_autotag_subpage("Album")

                self.after(0, update_album_ui)
            finally:
                self.is_scanning = False
                self.after(0, lambda: self.set_sidebar_state("normal"))

        threading.Thread(target=scan_bg, daemon=True).start()

    def _render_album_grid(self):
        """Ridisegna la griglia delle card degli album basandosi su self.current_albums."""
        for w in self.autotag_album_scroll.winfo_children():
            w.destroy()

        grid_f = ctk.CTkFrame(self.autotag_album_scroll, fg_color="transparent")
        grid_f.pack(fill="both", expand=True)
        grid_f.columnconfigure((0, 1, 2), weight=1, minsize=220)

        for idx, (album, files) in enumerate(self.current_albums.items()):
            card = ctk.CTkFrame(grid_f, corner_radius=12, border_width=1, border_color=("gray85", "gray20"))
            card.grid(row=idx // 3, column=idx % 3, padx=12, pady=12, sticky="nsew")

            # Carica anteprima copertina dell'album
            preview_img = None
            for f_path in files:
                ext = os.path.splitext(f_path)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.heic', '.heif']:
                    try:
                        from PIL import Image
                        pil_img = Image.open(f_path)
                        pil_img.thumbnail((160, 100))
                        preview_img = ctk.CTkImage(light_image=pil_img, size=pil_img.size)
                        break
                    except Exception:
                        pass

            if preview_img:
                lbl_icon = ctk.CTkLabel(card, text="", image=preview_img)
            else:
                lbl_icon = ctk.CTkLabel(card, text="📁", font=ctk.CTkFont(size=52))
            lbl_icon.pack(pady=(20, 5))

            lbl_name = ctk.CTkLabel(card, text=f"Album {album}", font=ctk.CTkFont(size=14, weight="bold"))
            lbl_name.pack(padx=10)

            ctk.CTkLabel(card, text=f"{len(files)} elementi", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(2, 10))

            btn_edit = ctk.CTkButton(card, text="Personalizza Nome", height=30, fg_color="transparent", border_width=1, font=ctk.CTkFont(size=11), command=lambda a=album: self.edit_album_name(a))
            btn_edit.pack(pady=(0, 20), padx=15, fill="x")

    def edit_album_name(self, old_name):
        from tkinter import simpledialog
        new_name = simpledialog.askstring("Modifica Nome Album", f"Inserisci un nuovo nome per l'album '{old_name}':")
        if new_name and new_name.strip() and new_name != old_name:
            self.current_albums[new_name.strip()] = self.current_albums.pop(old_name)
            self._render_album_grid()

    def rename_and_create_albums(self):
        import shutil
        dst = self.autotag_dest_folder.get()
        if not dst:
            return

        # Raggruppa gli album con 1 solo file in "Altri_Elementi" per evitare "una cartella per immagine"
        final_albums = {}
        for album, files in getattr(self, 'current_albums', {}).items():
            clean_album_name = album.replace(" ", "_")
            if len(files) == 1:
                final_albums.setdefault("Altri_Elementi", []).extend(files)
            else:
                final_albums.setdefault(clean_album_name, []).extend(files)

        for album, files in final_albums.items():
            album_dir = os.path.join(dst, album)
            os.makedirs(album_dir, exist_ok=True)
            for idx, f in enumerate(files):
                try:
                    ext = os.path.splitext(f)[1].lower()
                    orig_base = os.path.splitext(os.path.basename(f))[0]
                    new_filename = f"{album}_{orig_base}{ext}" if self.autotag_rename.get() else os.path.basename(f)
                    dest_path = os.path.join(album_dir, new_filename)
                    
                    base_dest = dest_path
                    counter = 1
                    while os.path.exists(dest_path) and os.path.abspath(f) != os.path.abspath(dest_path):
                        name, e = os.path.splitext(base_dest)
                        dest_path = f"{name}_{counter}{e}"
                        counter += 1

                    try:
                        shutil.copy2(f, dest_path)
                    except OSError:
                        shutil.copy(f, dest_path)
                except Exception:
                    pass

        from tkinter import messagebox
        messagebox.showinfo("Successo", "Tutti gli elementi sono stati organizzati e gli album intelligenti sono stati creati con successo!")
        self.show_autotag_subpage("Home")

    def init_offload_pages(self):
        self.offload_master_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["OffloadHome"] = self.offload_master_frame
        self.pages["OffloadResults"] = self.offload_master_frame

        self.offload_views = {}

        # 1. OFFLOAD CONFIG PAGE
        v_home = ctk.CTkFrame(self.offload_master_frame, fg_color="transparent")
        self.offload_views["OffloadHome"] = v_home

        ctk.CTkLabel(v_home, text="Offload & Backup Sicuro SSD", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))

        cfg_box = ctk.CTkScrollableFrame(v_home, corner_radius=15, border_width=1, border_color=("gray85", "gray15"))
        cfg_box.pack(fill="both", expand=True, padx=5, pady=5)

        ctk.CTkLabel(cfg_box, text="Configura Backup e Verifica MHL", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=30, pady=(20, 5))
        ctk.CTkLabel(cfg_box, text="Copia i file multimediali dalle tue SSD/Card verso più volumi simultaneamente, verificando l'integrità byte-a-byte.", text_color="gray", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=30, pady=(0, 20))

        # Inputs grid
        g = ctk.CTkFrame(cfg_box, fg_color="transparent")
        g.pack(fill="x", padx=30, pady=10)
        g.columnconfigure(1, weight=1)

        # Row 1: Sorgente
        ctk.CTkLabel(g, text="Cartella Sorgente (SSD/Card):", font=ctk.CTkFont(weight="bold", size=13)).grid(row=0, column=0, sticky="w", pady=12)
        self.ent_off_src = ctk.CTkEntry(g, textvariable=self.offload_source_folder, font=ctk.CTkFont(size=12), height=35)
        self.ent_off_src.grid(row=0, column=1, padx=(15, 10), sticky="ew")
        ctk.CTkButton(g, text="📂", width=45, height=35, command=self.pick_offload_source).grid(row=0, column=2)

        # Row 2: dynamic list of destinations
        ctk.CTkLabel(g, text="Cartelle di Destinazione:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=1, column=0, sticky="nw", pady=12)
        
        self.dest_list_frame = ctk.CTkFrame(g, fg_color="transparent")
        self.dest_list_frame.grid(row=1, column=1, columnspan=2, padx=(15, 0), sticky="ew", pady=12)
        
        self.offload_destinations = []
        self.render_offload_destinations_ui()

        # Settings
        ctk.CTkLabel(g, text="Algoritmo Verifica:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=3, column=0, sticky="w", pady=12)
        self.opt_off_algo = ctk.CTkOptionMenu(g, variable=self.offload_algo, values=["xxHash64", "SHA-256", "MD5", "Solo Dimensione"], height=35)
        self.opt_off_algo.grid(row=3, column=1, columnspan=2, padx=(15, 0), sticky="w")

        ctk.CTkLabel(g, text="ID Report:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=4, column=0, sticky="w", pady=12)
        self.ent_off_id = ctk.CTkEntry(g, textvariable=self.offload_report_id, font=ctk.CTkFont(size=12), height=35)
        self.ent_off_id.grid(row=4, column=1, columnspan=2, padx=(15, 0), sticky="w", ipadx=100)

        # Naming destinazione configurabile: schema per generare una sottocartella nella
        # destinazione invece di mirror-are sempre e solo il path relativo della sorgente
        # (gap rispetto a ShotPut Pro individuato confrontando le due app).
        ctk.CTkLabel(g, text="Sottocartella Destinazione:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=5, column=0, sticky="w", pady=12)
        naming_row = ctk.CTkFrame(g, fg_color="transparent")
        naming_row.grid(row=5, column=1, columnspan=2, padx=(15, 0), sticky="ew")
        self.opt_off_naming = ctk.CTkOptionMenu(
            naming_row, variable=self.offload_naming_scheme,
            values=["Nessuna (mirror sorgente)", "Data odierna", "Nome sorgente", "Numerazione automatica", "Personalizzato"],
            height=35, width=210, command=lambda _v: self._update_naming_prefix_visibility()
        )
        self.opt_off_naming.pack(side="left")
        self.ent_off_naming_prefix = ctk.CTkEntry(naming_row, textvariable=self.offload_naming_prefix, placeholder_text="Prefisso (es. Offload)", height=35, width=180)
        self.ent_off_naming_prefix.pack(side="left", padx=(10, 0))
        self._update_naming_prefix_visibility()

        # Preset: salva/richiama al volo destinazioni + algoritmo + naming scelti.
        ctk.CTkLabel(g, text="Preset:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=6, column=0, sticky="w", pady=12)
        preset_row = ctk.CTkFrame(g, fg_color="transparent")
        preset_row.grid(row=6, column=1, columnspan=2, padx=(15, 0), sticky="ew")
        self.opt_off_preset = ctk.CTkOptionMenu(preset_row, variable=self.offload_selected_preset, values=["-"], height=35, width=210, command=self._apply_offload_preset)
        self.opt_off_preset.pack(side="left")
        ctk.CTkButton(preset_row, text="💾 Salva come preset", width=170, height=35, command=self._save_offload_preset).pack(side="left", padx=(10, 0))
        self._refresh_offload_presets_ui()

        # --- Sezione Metadati Produzione (stile Silverstack) ---
        meta_header = ctk.CTkFrame(cfg_box, fg_color="transparent")
        meta_header.pack(fill="x", padx=30, pady=(20, 0))
        ctk.CTkLabel(meta_header, text="🎬 Metadati Produzione", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkLabel(meta_header, text="(opzionali - inclusi nel report MHL)", font=ctk.CTkFont(size=11, slant="italic"), text_color="gray").pack(side="left", padx=10)

        meta_grid = ctk.CTkFrame(cfg_box, fg_color="transparent")
        meta_grid.pack(fill="x", padx=30, pady=(5, 0))
        for _c in range(3):
            meta_grid.columnconfigure(_c * 2 + 1, weight=1)

        for idx, (key, label) in enumerate(self.offload_meta_fields):
            r = idx // 3
            c = (idx % 3) * 2
            ctk.CTkLabel(meta_grid, text=f"{label}:", font=ctk.CTkFont(size=11)).grid(row=r, column=c, sticky="w", padx=(0, 6), pady=5)
            ctk.CTkEntry(meta_grid, textvariable=self.offload_meta_vars[key], height=30).grid(row=r, column=c + 1, sticky="ew", padx=(0, 15), pady=5)

        notes_row = ctk.CTkFrame(cfg_box, fg_color="transparent")
        notes_row.pack(fill="x", padx=30, pady=(8, 0))
        ctk.CTkLabel(notes_row, text="Note:", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.offload_notes_text = ctk.CTkTextbox(notes_row, height=60)
        self.offload_notes_text.pack(fill="x", pady=(2, 0))

        # Opzione proxy video (ffmpeg)
        ctk.CTkCheckBox(cfg_box, text="Genera proxy video (ffmpeg) durante l'offload", variable=self.offload_make_proxy).pack(anchor="w", padx=30, pady=(14, 0))

        # Opzioni di fine lavoro: espulsione sorgente e spegnimento PC. Il sistema resta
        # comunque sveglio per TUTTA la copia (vedi SleepInhibitor in offload_bg) a
        # prescindere da queste due, altrimenti bloccare lo schermo (es. Touch ID su Mac)
        # durante una copia lunga la interrompe a metà.
        ctk.CTkCheckBox(cfg_box, text="Espelli la sorgente al termine (es. SD card della camera)", variable=self.offload_eject_source).pack(anchor="w", padx=30, pady=(10, 0))
        ctk.CTkCheckBox(cfg_box, text="Spegni il PC al termine (annullabile, 60s di margine)", variable=self.offload_shutdown_after).pack(anchor="w", padx=30, pady=(6, 0))

        # Action Button
        ctk.CTkButton(cfg_box, text="⚡ Avvia Offload & Genera Report", fg_color="#10b981", hover_color="#059669", height=50, width=320, font=ctk.CTkFont(weight="bold", size=15), corner_radius=10, command=self.run_offload_process).pack(pady=30)

        # 2. OFFLOAD RESULTS PAGE
        v_results = ctk.CTkFrame(self.offload_master_frame, fg_color="transparent")
        self.offload_views["OffloadResults"] = v_results

        ctk.CTkLabel(v_results, text="Stato Offload SSD", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))

        self.offload_status_lbl = ctk.CTkLabel(v_results, text="Inizializzazione...", font=ctk.CTkFont(size=16, weight="bold"))
        self.offload_status_lbl.pack(pady=10)

        self.offload_progress_bar = ctk.CTkProgressBar(v_results, height=15)
        self.offload_progress_bar.pack(fill="x", padx=10, pady=10)
        self.offload_progress_bar.set(0)

        # Log live: una riga per ogni file all'avvio/fine copia, in modo che l'utente
        # veda sempre "sta succedendo qualcosa" (soprattutto con pochi file enormi,
        # dove la sola label di stato può restare ferma a lungo tra un file e l'altro).
        self.offload_log_text = ctk.CTkTextbox(v_results, height=140, font=ctk.CTkFont(family="Consolas", size=11))
        self.offload_log_text.pack(fill="x", padx=5, pady=(0, 5))
        self.offload_log_text.configure(state="disabled")

        self.offload_results_scroll = ctk.CTkScrollableFrame(v_results, fg_color=("gray95", "gray10"))
        self.offload_results_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        res_foot = ctk.CTkFrame(v_results, fg_color="transparent")
        res_foot.pack(fill="x", side="bottom", pady=(15, 0))
        
        ctk.CTkButton(res_foot, text="Nuovo Offload", fg_color="transparent", text_color=("gray10", "gray90"), border_width=1, width=120, command=lambda: self.show_offload_subpage("OffloadHome")).pack(side="left")
        
        self.btn_open_report = ctk.CTkButton(res_foot, text="📄 Apri Report PDF", fg_color="#10b981", hover_color="#059669", width=220, font=ctk.CTkFont(weight="bold"), state="disabled", command=self.open_generated_report)
        self.btn_open_report.pack(side="right")

        # Start on Home
        self.show_offload_subpage("OffloadHome")

    def _offload_log(self, line):
        """Aggiunge una riga al log live della pagina Offload (thread-safe: va
        chiamato da self.after). Autoscroll in fondo."""
        if not self.offload_log_text.winfo_exists():
            return
        self.offload_log_text.configure(state="normal")
        self.offload_log_text.insert("end", line + "\n")
        self.offload_log_text.see("end")
        self.offload_log_text.configure(state="disabled")

    def show_offload_subpage(self, name):
        if name == "OffloadHome":
            import datetime
            self.offload_report_id.set(f"A{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
        for v in self.offload_views.values():
            v.pack_forget()
        self.offload_views[name].pack(fill="both", expand=True)

    def render_offload_destinations_ui(self):
        for w in self.dest_list_frame.winfo_children():
            w.destroy()
            
        if not self.offload_destinations:
            lbl_empty = ctk.CTkLabel(self.dest_list_frame, text="Nessuna destinazione aggiunta. Clicca Aggiungi per inserire una cartella.", text_color="gray", font=ctk.CTkFont(size=12, slant="italic"))
            lbl_empty.pack(anchor="w", pady=5)
        else:
            for idx, path in enumerate(self.offload_destinations):
                row = ctk.CTkFrame(self.dest_list_frame, fg_color=("gray90", "gray15"), corner_radius=6)
                row.pack(fill="x", pady=2)
                
                lbl = ctk.CTkLabel(row, text=path, font=ctk.CTkFont(size=11), anchor="w", justify="left")
                lbl.pack(side="left", padx=10, fill="x", expand=True, pady=5)
                
                btn_del = ctk.CTkButton(row, text="❌", width=30, height=25, fg_color="transparent", text_color="#ef4444", hover_color=("gray80", "gray25"), font=ctk.CTkFont(size=10, weight="bold"), command=lambda i=idx: self.remove_offload_destination(i))
                btn_del.pack(side="right", padx=5)
                
        btn_add = ctk.CTkButton(self.dest_list_frame, text="➕ Aggiungi Destinazione", height=30, width=180, font=ctk.CTkFont(size=11, weight="bold"), command=self.add_offload_destination)
        btn_add.pack(anchor="w", pady=(10, 5))

    def add_offload_destination(self):
        folder = filedialog.askdirectory(title="Seleziona Cartella di Destinazione")
        if folder:
            if folder not in self.offload_destinations:
                self.offload_destinations.append(folder)
                self.render_offload_destinations_ui()
                
    def remove_offload_destination(self, index):
        if 0 <= index < len(self.offload_destinations):
            self.offload_destinations.pop(index)
            self.render_offload_destinations_ui()

    def pick_offload_source(self):
        folder = filedialog.askdirectory(title="Seleziona Cartella Sorgente (SSD/Card)")
        if folder:
            self.offload_source_folder.set(folder)

    def open_generated_report(self):
        if hasattr(self, 'generated_report_path') and os.path.exists(self.generated_report_path):
            import webbrowser
            webbrowser.open(pathlib.Path(self.generated_report_path).absolute().as_uri())

    def _update_naming_prefix_visibility(self):
        """Il campo prefisso serve solo per lo schema 'Personalizzato': disabilitato (non
        rimosso, per non alterare la griglia) negli altri casi cosi' l'utente capisce subito
        che non ha effetto con lo schema attualmente selezionato."""
        if not hasattr(self, "ent_off_naming_prefix"):
            return
        scheme = self.offload_naming_scheme.get()
        self.ent_off_naming_prefix.configure(state="normal" if scheme == "Personalizzato" else "disabled")

    def _compute_offload_subfolder(self, src, dests, scheme, prefix):
        """Calcola la sottocartella di destinazione secondo lo schema scelto (gap rispetto a
        ShotPut Pro: naming destinazione configurabile invece del solo mirror del path sorgente).
        Ritorna "" per 'Nessuna' (comportamento identico a prima, nessuna regressione)."""
        import re
        import datetime
        today = datetime.datetime.now().strftime("%Y-%m-%d")

        if scheme == "Data odierna":
            return today
        elif scheme == "Nome sorgente":
            name = os.path.basename(os.path.normpath(src)) or "Sorgente"
            return re.sub(r'[<>:"/\\|?*]', "_", name)
        elif scheme == "Numerazione automatica":
            # Cerca in TUTTE le destinazioni il numero piu' alto gia' usato (Offload_001, ...)
            # cosi' due destinazioni non finiscono mai con numeri diversi per lo stesso job.
            max_n = 0
            for d in dests:
                try:
                    for entry in os.listdir(d):
                        m = re.match(r"^Offload_(\d+)$", entry)
                        if m:
                            max_n = max(max_n, int(m.group(1)))
                except Exception:
                    pass
            return f"Offload_{max_n + 1:03d}"
        elif scheme == "Personalizzato":
            base = prefix.strip() or "Offload"
            base = re.sub(r'[<>:"/\\|?*]', "_", base)
            return f"{base}_{today}"
        else:  # "Nessuna (mirror sorgente)" o valore sconosciuto
            return ""

    def _refresh_offload_presets_ui(self):
        if not hasattr(self, "opt_off_preset"):
            return
        names = list(self.offload_presets.keys())
        self.opt_off_preset.configure(values=names if names else ["-"])
        if self.offload_selected_preset.get() not in names:
            self.offload_selected_preset.set(names[0] if names else "-")

    def _save_offload_preset(self):
        """Salva destinazioni + algoritmo + naming correnti come preset riutilizzabile,
        persistito in config.json (stesso file delle altre impostazioni dell'app)."""
        from tkinter import simpledialog, messagebox
        name = simpledialog.askstring("Salva Preset", "Nome del preset:")
        if not name or not name.strip():
            return
        name = name.strip()
        self.offload_presets[name] = {
            "destinations": [d for d in self.offload_destinations if d.strip()],
            "algo": self.offload_algo.get(),
            "naming_scheme": self.offload_naming_scheme.get(),
            "naming_prefix": self.offload_naming_prefix.get(),
            "make_proxy": self.offload_make_proxy.get(),
        }
        self.save_settings()
        self._refresh_offload_presets_ui()
        self.offload_selected_preset.set(name)
        messagebox.showinfo("Preset salvato", f"Preset \"{name}\" salvato con successo.")

    def _apply_offload_preset(self, name):
        """Richiama un preset salvato: sostituisce destinazioni/algoritmo/naming correnti."""
        preset = self.offload_presets.get(name)
        if not preset:
            return
        self.offload_destinations = list(preset.get("destinations", []))
        self.render_offload_destinations_ui()
        self.offload_algo.set(preset.get("algo", "xxHash64"))
        self.offload_naming_scheme.set(preset.get("naming_scheme", "Nessuna (mirror sorgente)"))
        self.offload_naming_prefix.set(preset.get("naming_prefix", ""))
        self.offload_make_proxy.set(preset.get("make_proxy", False))
        self._update_naming_prefix_visibility()

    PROXY_VIDEO_EXTS = ('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mxf', '.mpg', '.mpeg', '.mts', '.m2ts', '.wmv')

    def run_offload_process(self):
        src = self.offload_source_folder.get()
        dests = [d for d in self.offload_destinations if d.strip()]
        algo = self.offload_algo.get()
        report_id = self.offload_report_id.get()
        make_proxy = self.offload_make_proxy.get()
        naming_scheme = self.offload_naming_scheme.get()
        naming_prefix = self.offload_naming_prefix.get()
        dest_subfolder = self._compute_offload_subfolder(src, dests, naming_scheme, naming_prefix) if dests else ""

        # Raccogli i metadati di produzione (solo i campi compilati) per il report MHL
        production_meta = {}
        for key, label in self.offload_meta_fields:
            val = self.offload_meta_vars[key].get().strip()
            if val:
                production_meta[label] = val
        if self.offload_notes_text is not None:
            notes = self.offload_notes_text.get("1.0", "end").strip()
            if notes:
                production_meta["Note"] = notes

        if not src or not dests:
            from tkinter import messagebox
            messagebox.showwarning("Selezione Mancante", "Seleziona la cartella sorgente (SSD) ed almeno una cartella di destinazione.")
            return

        self.show_offload_subpage("OffloadResults")
        self.btn_open_report.configure(state="disabled")
        self.is_scanning = True
        self.set_sidebar_state("disabled")

        for w in self.offload_results_scroll.winfo_children():
            w.destroy()

        self.offload_status_lbl.configure(text="Avvio copia ed elaborazione...", text_color=("gray10", "white"))
        self.offload_progress_bar.set(0)
        self.offload_log_text.configure(state="normal")
        self.offload_log_text.delete("1.0", "end")
        self.offload_log_text.configure(state="disabled")

        eject_source = self.offload_eject_source.get()
        shutdown_after = self.offload_shutdown_after.get()

        def offload_bg():
            import system_actions
            # Impedisce al sistema di sospendersi/bloccare lo schermo per tutta la
            # durata della copia: su Mac, bloccare lo schermo (es. con Touch ID)
            # durante Offload interrompeva il job a metà. Ripristinato nel `finally`
            # qui sotto, qualunque cosa succeda.
            sleep_guard = system_actions.SleepInhibitor()
            sleep_guard.__enter__()
            try:
                import time
                import os
                import shutil
                import datetime
                import concurrent.futures
                import threading
                from report_generator import ReportGenerator

                files_to_copy = []
                for root, _, files in os.walk(src):
                    for f in files:
                        p = os.path.join(root, f)
                        rel = os.path.relpath(p, src)
                        files_to_copy.append({"name": f, "path": p, "rel": rel})

                if not files_to_copy:
                    self.after(0, lambda: self.offload_status_lbl.configure(text="❌ Nessun file trovato nella sorgente.", text_color="#ef4444"))
                    return

                total_files = len(files_to_copy)
                total_bytes = 0
                for _x in files_to_copy:
                    try:
                        total_bytes += os.path.getsize(_x["path"])
                    except Exception:
                        pass

                # Controllo spazio libero: servono total_bytes su OGNI destinazione
                low_space = []
                for d in dests:
                    try:
                        free = shutil.disk_usage(d).free
                        if free < total_bytes:
                            low_space.append((d, free))
                    except Exception:
                        pass
                if low_space:
                    msg = "Spazio insufficiente su: " + ", ".join(
                        f"{os.path.basename(x[0]) or x[0]} ({self.format_file_size(x[1])} liberi / {self.format_file_size(total_bytes)} necessari)"
                        for x in low_space)
                    self.after(0, lambda m=msg: self.offload_status_lbl.configure(text="❌ " + m, text_color="#ef4444"))
                    return

                processed_files = 0
                copied_bytes = 0
                start_time = time.time()
                job_start_dt = datetime.datetime.now()
                results = []

                # Pre-lettura del file successivo in memoria MENTRE il file corrente è
                # in fase di verifica (vedi _prefetch_next_source): sorgente e destinazioni
                # sono quasi sempre dischi fisici diversi, quindi le due operazioni non si
                # contendono banda. Se fallisce o il file è troppo grande, nessun problema:
                # copy_write_and_hash farà semplicemente una normale lettura da disco.
                prefetch_state = {"path": None, "thread": None, "chunks": None}

                def _kick_prefetch(path):
                    def _do():
                        prefetch_state["chunks"] = self._prefetch_next_source(path)
                    prefetch_state["path"] = path
                    prefetch_state["chunks"] = None
                    t = threading.Thread(target=_do, daemon=True)
                    t.start()
                    prefetch_state["thread"] = t

                if files_to_copy:
                    _kick_prefetch(files_to_copy[0]["path"])

                # Barra/percentuale/velocita'/ETA: UN solo calcolo, basato sempre sui BYTE
                # (prima la barra saltava tra frazione di byte durante la copia e frazione
                # di file a file completato). Velocita' mostrata = media mobile sulla sola
                # fase di copia; ETA = byte rimanenti / velocita' media complessiva (include
                # verifica e proxy, quindi e' il tempo reale al completamento). Nei primi
                # secondi l'ETA e' instabile: si mostra "calcolo..." finche' non ci sono
                # almeno 3 s e l'1% di dati.
                ui_state = {"t": 0.0, "last_t": None, "last_done": 0, "ewma": None}

                def _ui_progress(done, force=False):
                    now = time.time()
                    if not force and now - ui_state["t"] < 0.25:
                        return
                    ui_state["t"] = now
                    if total_bytes:
                        done = min(done, total_bytes)
                        frac = done / total_bytes
                    else:
                        frac = processed_files / max(1, total_files)
                    elapsed = max(0.001, now - start_time)
                    overall = done / elapsed
                    if ui_state["last_t"] is None:
                        ui_state["last_t"], ui_state["last_done"] = now, done
                    elif now - ui_state["last_t"] >= 0.5:
                        inst = (done - ui_state["last_done"]) / (now - ui_state["last_t"])
                        ui_state["ewma"] = inst if ui_state["ewma"] is None else 0.3 * inst + 0.7 * ui_state["ewma"]
                        ui_state["last_t"], ui_state["last_done"] = now, done
                    speed = ui_state["ewma"] if ui_state["ewma"] else overall
                    if elapsed >= 3 and frac >= 0.01 and overall > 0:
                        eta_s = int(max(0, total_bytes - done) / overall) if total_bytes else 0
                        eta_str = f"{eta_s // 3600}h {(eta_s % 3600) // 60}m" if eta_s >= 3600 else (f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 60 else f"{eta_s}s")
                    else:
                        eta_str = "calcolo..."
                    n_file = min(processed_files + 1, total_files) if frac < 1 else total_files
                    text = f"{int(frac * 100)}% · {self.format_file_size(int(speed))}/s · ETA {eta_str} · file {n_file}/{total_files}"
                    self.after(0, lambda v=frac, tx=text: (
                        self.offload_progress_bar.set(v),
                        self.offload_status_lbl.configure(text=tx, text_color=("gray10", "white"))
                    ))

                for _idx, it in enumerate(files_to_copy):
                    try:
                        sz = os.path.getsize(it["path"])
                        sz_str = self.format_file_size(sz)

                        # Copia + checksum sorgente in UN'UNICA lettura del file, scritta
                        # simultaneamente su tutte le destinazioni (vedi copy_write_and_hash):
                        # prima erano 1 lettura per l'hash + 1 rilettura per ogni destinazione,
                        # il vero collo di bottiglia con più dischi lenti in parallelo.
                        alt_algo = None if algo == "Solo Dimensione" else ("SHA-256" if algo == "xxHash64" else "MD5")
                        algos_list = [algo] if alt_algo is None else [algo, alt_algo]
                        self.after(0, lambda name=it["name"]: self.offload_status_lbl.configure(text=f"Copia e checksum: {name}..."))
                        self.after(0, lambda name=it["name"], s=sz_str, n=_idx + 1, t=total_files: self._offload_log(f"▶ [{n}/{t}] {name} ({s})"))

                        target_paths = []
                        for d in dests:
                            base_dir = os.path.join(d, dest_subfolder) if dest_subfolder else d
                            target_path = os.path.join(base_dir, it["rel"])
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            target_paths.append(target_path)

                        prefetched = None
                        if prefetch_state["path"] == it["path"] and prefetch_state["thread"] is not None:
                            prefetch_state["thread"].join()
                            prefetched = prefetch_state["chunks"]

                        # Percentuale/velocità/ETA aggiornate DURANTE la copia del singolo file
                        # (non solo a file completato): su pochi file enormi (tipico di un
                        # Offload da camera/SD card) la barra restava ferma per minuti tra un
                        # aggiornamento e l'altro. Throttle a ~4 volte/secondo per non intasare
                        # la coda eventi della UI su file da decine di GB.
                        bytes_before_file = copied_bytes
                        ui_state["last_t"] = None  # la fase di verifica/proxy non conta nella velocita' di copia

                        def _on_file_progress(n, _bf=bytes_before_file, _sz=sz):
                            _ui_progress(_bf + n, force=(n >= _sz))

                        src_hashes, write_ok, chunk_hashes = self.copy_write_and_hash(it["path"], target_paths, algos_list, prefetched_chunks=prefetched, progress_callback=_on_file_progress)
                        src_hash = src_hashes[algo]
                        src_hash_alt = src_hashes[alt_algo] if alt_algo else "N/A"

                        # Avvia subito la pre-lettura del PROSSIMO file: da qui in poi (retry
                        # + verifica) il disco sorgente è libero, tanto vale iniziare a leggerlo.
                        if _idx + 1 < len(files_to_copy):
                            _kick_prefetch(files_to_copy[_idx + 1]["path"])

                        mtime = os.path.getmtime(it["path"])
                        ctime = os.path.getctime(it["path"])
                        created_str = datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
                        modified_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

                        # Retry mirato SOLO sulle destinazioni che hanno fallito la scrittura
                        # (drive USB lenti/ballerini): non serve rileggere il sorgente per
                        # quelle già scritte correttamente al primo giro.
                        for target_path in target_paths:
                            if write_ok.get(target_path):
                                continue
                            for _attempt in range(1, 4):
                                try:
                                    shutil.copy2(it["path"], target_path)
                                    write_ok[target_path] = True
                                    break
                                except Exception as ce:
                                    if _attempt < 3:
                                        time.sleep(1.5 * _attempt)
                                    else:
                                        print(f"Errore copia fallita per {it['name']}: {ce}")

                        # Verifica integrità: rilegge ogni destinazione per scoprire eventuali
                        # corruzioni introdotte dalla scrittura stessa. Il checksum "prima" e'
                        # src_hash (calcolato leggendo il sorgente durante la copia), il checksum
                        # "dopo" e' dest_hash (rileggendo la destinazione a scrittura conclusa):
                        # un'incongruenza tra i due va segnalata in modo esplicito, non solo
                        # marcata "Failed" in una riga di tabella che l'utente puo' non notare.
                        copy_success = True
                        fail_reason = None  # "scrittura" | "checksum"
                        # Stato per-destinazione (non solo un esito unico per il file): ShotPut Pro
                        # mostra nel report "Destination N: Status Verified" per ogni copia, non solo
                        # un singolo Verified/Failed complessivo. dest_status mappa dest_path -> label.
                        dest_status = {tp: "Verified" for tp in target_paths}
                        verify_targets = [tp for tp in target_paths if write_ok.get(tp)]
                        if any(not write_ok.get(tp) for tp in target_paths):
                            copy_success = False
                            fail_reason = "scrittura"
                            for tp in target_paths:
                                if not write_ok.get(tp):
                                    dest_status[tp] = "Failed (scrittura)"

                        if verify_targets:
                            self.after(0, lambda name=it["name"]: self.offload_status_lbl.configure(text=f"Verifica integrità: {name}..."))
                            # Verifica A CAMPIONE in parallelo su ogni destinazione (vedi
                            # _verify_sampled_destinations): rilegge solo una manciata di
                            # blocchi invece dell'intero file, molto più veloce della
                            # rilettura completa di prima, con una copertura ridotta ma
                            # comunque efficace sui fallimenti più comuni (scrittura
                            # troncata, blocco corrotto). Trade-off scelto esplicitamente
                            # per la velocità.
                            verify_ok = self._verify_sampled_destinations(
                                verify_targets, chunk_hashes, 4 * 1024 * 1024, algo, sz)

                            for target_path, ok in verify_ok.items():
                                if not src_hash or src_hash.startswith("Error") or not ok:
                                    copy_success = False
                                    fail_reason = "checksum"  # priorita' massima: e' l'esito piu' grave
                                    dest_status[target_path] = "Failed (checksum)"

                        # Proxy video (ffmpeg) sulla prima destinazione (best-effort)
                        if make_proxy:
                            try:
                                if os.path.splitext(it["path"])[1].lower() in self.PROXY_VIDEO_EXTS:
                                    self.ai.generate_proxy(
                                        it["path"], os.path.join(dests[0], "Proxies"),
                                        ffmpeg_path=self.ffmpeg_path,
                                        resolution=self.proxy_resolution_var.get(),
                                        format_key=self.proxy_format_var.get())
                            except Exception:
                                pass

                        _log_icon = "✓" if copy_success else "✗"
                        _log_reason = f" ({fail_reason})" if fail_reason else ""
                        self.after(0, lambda ic=_log_icon, r=_log_reason: self._offload_log(f"  {ic} completato{r}"))

                        status = "Verified" if copy_success else "Failed"

                        # Estrazione metadati REALI del media (risoluzione, durata, codec,
                        # bitrate, timecode...): ffprobe se configurato, cv2 come ripiego.
                        media_info = ReportGenerator.extract_media_info(it["path"], self.ffmpeg_path)

                        results.append({
                            "name": it["name"],
                            "path": it["path"],
                            "rel": os.path.join(dest_subfolder, it["rel"]) if dest_subfolder else it["rel"],
                            "size_bytes": sz,
                            "size_str": sz_str,
                            "created": created_str,
                            "modified": modified_str,
                            "hash": src_hash,
                            "hash_alt": src_hash_alt,
                            "dest_status": {d: dest_status.get(tp, "Unknown") for d, tp in zip(dests, target_paths)},
                            "status": status,
                            "fail_reason": fail_reason,
                            "media_format": media_info["media_format"],
                            "codec": media_info["codec"],
                            "duration": media_info["duration"],
                            "resolution": media_info["resolution"],
                            "camera": media_info["camera"],
                            "shot": media_info["shot"],
                            "frames": media_info["frames"],
                            "bitrate": media_info["bitrate"],
                            "audio": media_info["audio"],
                            "timecode": media_info.get("timecode", "N/A")
                        })

                    except Exception as e:
                        results.append({
                            "name": it["name"],
                            "path": it["path"],
                            "rel": os.path.join(dest_subfolder, it["rel"]) if dest_subfolder else it["rel"],
                            "size_bytes": 0,
                            "size_str": "0 B",
                            "hash": "ERROR",
                            "status": "Failed",
                            "fail_reason": "errore"
                        })
                        self.after(0, lambda err=str(e): self._offload_log(f"  ✗ errore: {err}"))

                    processed_files += 1
                    try:
                        copied_bytes += os.path.getsize(it["path"])
                    except Exception:
                        pass
                    _ui_progress(copied_bytes, force=True)

                # Generate and save report
                self.after(0, lambda: self.offload_status_lbl.configure(text="Generazione Report..."))
                job_finish_dt = datetime.datetime.now()
                elapsed_s = int(time.time() - start_time)
                elapsed_str = f"{elapsed_s // 60}m {elapsed_s % 60}s" if elapsed_s >= 60 else f"{elapsed_s}s"
                timing = {"start": job_start_dt, "finish": job_finish_dt, "elapsed_str": elapsed_str}
                first_dst = dests[0]
                report_dir = os.path.join(first_dst, "MHL_Reports")
                report_path = ReportGenerator.save_report(report_dir, report_id, src, results, algo, dests, production_meta, timing)
                self.generated_report_path = report_path

                # Export TXT/CSV accanto al PDF: stesso contenuto in formato testuale/tabellare,
                # per chi deve importarli in un foglio di calcolo o in uno script invece di
                # aprire un PDF (prima Datarium generava solo PDF, ShotPut Pro offre anche questi).
                try:
                    ReportGenerator.save_txt_report(report_dir, report_id, results, algo, dests, timing)
                    ReportGenerator.save_csv_report(report_dir, report_id, results, algo)
                except Exception as e:
                    print(f"Errore export TXT/CSV: {e}")

                # File .mhl VERI (uno per destinazione, standard ASC MediaHashList), non solo
                # un PDF che si chiama "MHL": permette a un altro tool DIT (Silverstack, YoYotta,
                # Pomfort) di leggere e validare i checksum senza passare da Datarium.
                try:
                    ReportGenerator.save_mhl_files(dests, report_id, results, algo)
                except Exception as e:
                    print(f"Errore generazione .mhl: {e}")

                # Copiamo il report in tutte le altre destinazioni per sicurezza
                for other_dst in dests[1:]:
                    try:
                        other_report_dir = os.path.join(other_dst, "MHL_Reports")
                        os.makedirs(other_report_dir, exist_ok=True)
                        shutil.copy2(report_path, os.path.join(other_report_dir, os.path.basename(report_path)))
                    except Exception:
                        pass

                checksum_mismatches = [r for r in results if r.get("fail_reason") == "checksum"]
                write_failures = [r for r in results if r.get("fail_reason") in ("scrittura", "errore")]

                if checksum_mismatches or write_failures:
                    self.send_local_notification(
                        "Datarium - Offload con errori",
                        f"{len(checksum_mismatches) + len(write_failures)} file su {len(results)} non verificati. Controlla il report."
                    )
                else:
                    self.send_local_notification(
                        "Datarium - Offload Completato",
                        f"{len(results)} file copiati e verificati con successo su {len(dests)} destinazione/i."
                    )

                # Cronologia job persistente su disco (indipendente dalla sessione, con
                # retention configurabile): gap rispetto a ShotPut Pro, che tiene uno storico
                # dei job anche dopo la chiusura dell'app.
                try:
                    n_ok_results = sum(1 for r in results if r.get("status") == "Verified")
                    ReportGenerator.record_job_history(self.get_job_history_path(), {
                        "job_type": "offload",
                        "report_id": report_id,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "status": "Failed" if (checksum_mismatches or write_failures) else "Verified",
                        "n_files": len(results),
                        "n_ok": n_ok_results,
                        "destinations": dests,
                        "report_path": report_path,
                    }, max_entries=self.job_history_max)
                except Exception as e:
                    print(f"Errore registrazione cronologia job: {e}")

                def render_results_ui():
                    if checksum_mismatches:
                        self.offload_status_lbl.configure(
                            text=f"⚠ Incongruenza di checksum su {len(checksum_mismatches)} file: il contenuto copiato "
                                 f"NON corrisponde al sorgente. Controlla il report prima di considerare il backup valido.",
                            text_color="#ef4444"
                        )
                    elif write_failures:
                        self.offload_status_lbl.configure(
                            text=f"⚠ Offload completato con {len(write_failures)} errori di scrittura. Controlla il report.",
                            text_color="#f59e0b"
                        )
                    else:
                        self.offload_status_lbl.configure(text="✓ Offload completato con successo, checksum verificato su ogni file.", text_color="#10b981")
                    self.btn_open_report.configure(state="normal")

                    for res in results:
                        row = ctk.CTkFrame(self.offload_results_scroll, fg_color="transparent")
                        row.pack(fill="x", pady=2)

                        icon = "✓" if res["status"] == "Verified" else ("⚠" if res.get("fail_reason") == "checksum" else "❌")
                        icon_color = "#10b981" if res["status"] == "Verified" else "#ef4444"
                        lbl_icon = ctk.CTkLabel(row, text=icon, text_color=icon_color, font=ctk.CTkFont(size=14, weight="bold"))
                        lbl_icon.pack(side="left", padx=10)

                        lbl_name = ctk.CTkLabel(row, text=res["name"], font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
                        lbl_name.pack(side="left", fill="x", expand=True, padx=5)

                        if res.get("fail_reason"):
                            reason_txt = {"checksum": "checksum non corrispondente", "scrittura": "errore di scrittura", "errore": "errore"}.get(res["fail_reason"], "")
                            ctk.CTkLabel(row, text=reason_txt, font=ctk.CTkFont(size=11), text_color="#ef4444").pack(side="right", padx=15)

                        lbl_sz = ctk.CTkLabel(row, text=res["size_str"], font=ctk.CTkFont(size=11), text_color="gray")
                        lbl_sz.pack(side="right", padx=15)

                    # Un'incongruenza di checksum in un tool di backup e' un problema di integrita'
                    # dei dati, non un errore qualunque: merita un popup esplicito, non solo una
                    # riga colorata in una lista scrollabile che si puo' non notare.
                    if checksum_mismatches:
                        from tkinter import messagebox
                        names = "\n".join(f"• {r['name']}" for r in checksum_mismatches[:15])
                        more = f"\n... e altri {len(checksum_mismatches) - 15}" if len(checksum_mismatches) > 15 else ""
                        messagebox.showwarning(
                            "Incongruenza di checksum rilevata",
                            f"{len(checksum_mismatches)} file copiati non corrispondono al checksum del sorgente:\n\n"
                            f"{names}{more}\n\n"
                            "Il backup di questi file NON è affidabile: ricopiali o verifica il disco di destinazione."
                        )

                self.after(0, render_results_ui)

                # Espulsione sorgente e spegnimento PC: solo a fine job, e lo spegnimento
                # solo se non ci sono incongruenze di checksum (l'utente potrebbe voler
                # vedere/gestire il problema prima che il PC si spenga).
                if eject_source:
                    ok_ej, msg_ej = system_actions.eject_volume(src)
                    self.after(0, lambda ok=ok_ej, m=msg_ej: self.offload_status_lbl.configure(
                        text=(self.offload_status_lbl.cget("text") + ("\nSorgente espulsa." if ok else f"\nEspulsione sorgente fallita: {m}"))
                    ))

                if shutdown_after and not checksum_mismatches:
                    ok_sd, msg_sd, sd_handle = system_actions.shutdown_computer(60)
                    if ok_sd:
                        self._pending_shutdown_handle = sd_handle
                        self.after(0, self._show_shutdown_countdown)
                elif shutdown_after and checksum_mismatches:
                    from tkinter import messagebox
                    self.after(0, lambda: messagebox.showwarning(
                        "Spegnimento annullato",
                        "Sono state rilevate incongruenze di checksum: lo spegnimento automatico è stato "
                        "annullato per darti modo di controllare il report prima di spegnere il PC."
                    ))
            finally:
                sleep_guard.__exit__(None, None, None)
                self.is_scanning = False
                self.after(0, lambda: self.set_sidebar_state("normal"))

        threading.Thread(target=offload_bg, daemon=True).start()

    def _show_shutdown_countdown(self, headline="Offload completato."):
        """Popup non bloccante con pulsante per annullare lo spegnimento automatico
        programmato a fine Offload (margine di 60s prima che avvenga davvero)."""
        from tkinter import messagebox
        win = ctk.CTkToplevel(self)
        win.title("Spegnimento programmato")
        win.geometry("380x150")
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text=f"{headline}\nIl PC si spegnerà tra 60 secondi.",
                     font=ctk.CTkFont(weight="bold")).pack(pady=(20, 10))

        def do_cancel():
            import system_actions
            system_actions.cancel_shutdown(getattr(self, "_pending_shutdown_handle", None))
            win.destroy()

        ctk.CTkButton(win, text="Annulla spegnimento", fg_color="#ef4444", hover_color="#b91c1c",
                      command=do_cancel).pack(pady=10)
        # Se l'utente non annulla, la finestra si chiude da sola quando lo spegnimento
        # e' ormai imminente/avvenuto: niente resta appeso in giro.
        win.after(60000, lambda: win.destroy() if win.winfo_exists() else None)

    # ==================== SINCRONIZZA DISCHI (stile FreeFileSync) ====================
    SYNC_COLORS = {
        "only_a": ("#dbeafe", "#1e3a5f"),
        "only_b": ("#dcfce7", "#14532d"),
        "different": ("#fef3c7", "#78350f"),
        "identical": ("gray92", "gray17"),
    }
    SYNC_ACTION_LOOK = {
        "a2b": ("▶", "#2563eb"),
        "b2a": ("◀", "#16a34a"),
        "skip": ("⏸", "#6b7280"),
        "del_a": ("🗑 A", "#dc2626"),
        "del_b": ("🗑 B", "#dc2626"),
    }
    SYNC_MAX_ROWS = 400

    def init_sync_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Sync"] = page

        ctk.CTkLabel(page, text="Sincronizza Dischi", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(page, text="Confronta due dischi o cartelle, controlla l'anteprima e sincronizza. Niente viene cancellato davvero: i file eliminati o sostituiti vanno nella cartella _Datarium_Sync_Cestino del disco e si possono recuperare.",
                     text_color="gray", font=ctk.CTkFont(size=12), wraplength=820, justify="left").pack(anchor="w", pady=(0, 8))

        top = ctk.CTkFrame(page, corner_radius=10)
        top.pack(fill="x", pady=(0, 6))
        for col, (label, var) in enumerate((("Disco A", self.sync_path_a), ("Disco B", self.sync_path_b))):
            cell = ctk.CTkFrame(top, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="ew", padx=12, pady=(10, 4))
            top.columnconfigure(col, weight=1)
            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            row = ctk.CTkFrame(cell, fg_color="transparent")
            row.pack(fill="x")
            ctk.CTkEntry(row, textvariable=var, placeholder_text="Scegli cartella o disco...").pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkButton(row, text="📂", width=40, command=lambda v=var: self._sync_pick(v)).pack(side="left")

        mrow = ctk.CTkFrame(top, fg_color="transparent")
        mrow.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(2, 10))
        ctk.CTkLabel(mrow, text="Modalità:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        import disk_sync
        ctk.CTkOptionMenu(mrow, values=list(disk_sync.MODES.keys()), variable=self.sync_mode_var, width=330,
                          command=lambda _v: self._sync_apply_mode()).pack(side="left", padx=(8, 18))
        ctk.CTkLabel(mrow, text="Escludi:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkEntry(mrow, textvariable=self.sync_exclude, width=230, placeholder_text="es. *.tmp, Proxies, Cache").pack(side="left", padx=8)

        opts = ctk.CTkFrame(page, fg_color="transparent")
        opts.pack(fill="x", pady=(0, 4))
        self.btn_sync_scan = ctk.CTkButton(opts, text="🔍 Confronta", width=130, height=34, font=ctk.CTkFont(weight="bold"), command=self.sync_scan)
        self.btn_sync_scan.pack(side="left")
        ctk.CTkCheckBox(opts, text="Approfondito (hash di tutto)", variable=self.sync_deep).pack(side="left", padx=(14, 0))
        ctk.CTkCheckBox(opts, text="Verifica dopo la copia", variable=self.sync_verify).pack(side="left", padx=(14, 0))

        flt = ctk.CTkFrame(page, fg_color="transparent")
        flt.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(flt, text="Mostra:", font=ctk.CTkFont(size=12)).pack(side="left")
        for key, text in (("only_a", "Solo in A"), ("only_b", "Solo in B"), ("different", "Diversi"), ("identical", "Identici")):
            ctk.CTkCheckBox(flt, text=text, variable=self.sync_show[key], width=20, command=self._sync_render).pack(side="left", padx=(10, 0))

        self.sync_status_lbl = ctk.CTkLabel(page, text="Scegli i due dischi e premi Confronta.", font=ctk.CTkFont(size=13, weight="bold"), anchor="w")
        self.sync_status_lbl.pack(fill="x", pady=(2, 0))
        self.sync_progress = ctk.CTkProgressBar(page, height=10)
        self.sync_progress.pack(fill="x", pady=(2, 6))
        self.sync_progress.set(0)

        hdr = ctk.CTkFrame(page, fg_color=("gray85", "gray20"), corner_radius=6)
        hdr.pack(fill="x")
        hdr.columnconfigure(0, weight=1, uniform="s")
        hdr.columnconfigure(2, weight=1, uniform="s")
        ctk.CTkLabel(hdr, text="DISCO A", font=ctk.CTkFont(weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        ctk.CTkLabel(hdr, text="Azione", width=70, font=ctk.CTkFont(size=11)).grid(row=0, column=1)
        ctk.CTkLabel(hdr, text="DISCO B", font=ctk.CTkFont(weight="bold"), anchor="w").grid(row=0, column=2, sticky="ew", padx=6, pady=4)

        self.sync_scroll = ctk.CTkScrollableFrame(page, fg_color=("gray95", "gray10"))
        self.sync_scroll.pack(fill="both", expand=True, pady=(2, 6))

        bot = ctk.CTkFrame(page, fg_color="transparent")
        bot.pack(fill="x")
        self.btn_sync_go = ctk.CTkButton(bot, text="⚡ Sincronizza", height=42, width=190, fg_color="#10b981", hover_color="#059669",
                                         font=ctk.CTkFont(weight="bold", size=14), state="disabled", command=self.sync_apply)
        self.btn_sync_go.pack(side="left")
        self.sync_summary_lbl = ctk.CTkLabel(bot, text="", font=ctk.CTkFont(size=12), anchor="w", justify="left", wraplength=560)
        self.sync_summary_lbl.pack(side="left", padx=14)

    def _sync_pick(self, var):
        folder = filedialog.askdirectory(title="Seleziona disco o cartella")
        if folder:
            var.set(folder)

    def _sync_set_busy(self, busy):
        self.sync_busy = busy
        self.is_scanning = busy
        self.set_sidebar_state("disabled" if busy else "normal")
        self.btn_sync_scan.configure(state="disabled" if busy else "normal")
        if busy:
            self.btn_sync_go.configure(state="disabled")

    def _sync_status(self, text, progress=None):
        def _u():
            self.sync_status_lbl.configure(text=text, text_color=("gray10", "gray90"))
            if progress is not None:
                self.sync_progress.set(progress)
        self.after(0, _u)

    def _sync_mode(self):
        import disk_sync
        return disk_sync.MODES.get(self.sync_mode_var.get(), "update")

    def _sync_apply_mode(self):
        """Riassegna le azioni di default di ogni riga secondo la modalita' scelta."""
        import disk_sync
        mode = self._sync_mode()
        for r in self.sync_rows:
            r["action"] = disk_sync.default_action(r, mode)
        self._sync_render()

    def sync_scan(self):
        from tkinter import messagebox
        import disk_sync
        a, b = self.sync_path_a.get().strip(), self.sync_path_b.get().strip()
        if not (os.path.isdir(a) and os.path.isdir(b)):
            messagebox.showwarning("Selezione mancante", "Scegli due cartelle/dischi validi (A e B).")
            return
        if os.path.abspath(a) == os.path.abspath(b):
            messagebox.showwarning("Stessa cartella", "Disco A e Disco B sono lo stesso percorso.")
            return
        deep = self.sync_deep.get()
        exclude = disk_sync.parse_exclude(self.sync_exclude.get())
        self._sync_set_busy(True)
        self.sync_progress.configure(mode="indeterminate")
        self.sync_progress.start()

        def bg():
            try:
                rows = disk_sync.compare(a, b, deep=deep, exclude=exclude, status_cb=lambda s: self._sync_status(s))
                mode = self._sync_mode()
                for r in rows:
                    r["action"] = disk_sync.default_action(r, mode)
                self.sync_rows = rows
            except Exception as e:
                self.sync_rows = []
                self._sync_status(f"Errore durante il confronto: {e}")
            finally:
                self.after(0, self._sync_scan_done)
        threading.Thread(target=bg, daemon=True).start()

    def _sync_scan_done(self):
        self.sync_progress.stop()
        self.sync_progress.configure(mode="determinate")
        self.sync_progress.set(0)
        self._sync_set_busy(False)
        self._sync_render()

    def _sync_counts(self):
        c = {"only_a": 0, "only_b": 0, "different": 0, "identical": 0}
        for r in self.sync_rows:
            c[r["status"]] += 1
        return c

    def _sync_refresh_summary(self):
        import disk_sync
        s = disk_sync.summarize(self.sync_rows)
        n = s["a2b"] + s["b2a"] + s["del"]
        parts = []
        if s["a2b"]:
            parts.append(f"▶ {s['a2b']} A→B")
        if s["b2a"]:
            parts.append(f"◀ {s['b2a']} B→A")
        if s["del"]:
            parts.append(f"🗑 {s['del']} nel cestino")
        txt = " · ".join(parts) if parts else "Nessuna azione prevista"
        if n:
            txt += f"  ({disk_sync.fmt_size(s['bytes'])} da copiare"
            txt += f", {s['overwrite']} sostituzioni)" if s["overwrite"] else ")"
        self.sync_summary_lbl.configure(text=txt)
        self.btn_sync_go.configure(state="normal" if (n and not self.sync_busy) else "disabled")

    def _sync_render(self):
        import disk_sync
        for w in self.sync_scroll.winfo_children():
            w.destroy()
        c = self._sync_counts()
        if not self.sync_rows:
            self._sync_refresh_summary()
            return
        if not (c["only_a"] or c["only_b"] or c["different"]):
            self.sync_status_lbl.configure(text=f"✅ I due dischi sono identici ({c['identical']} file).", text_color="#10b981")
        else:
            self.sync_status_lbl.configure(
                text=f"{c['only_a']} solo in A · {c['only_b']} solo in B · {c['different']} diversi · {c['identical']} identici",
                text_color=("gray10", "gray90"))

        shown = [r for r in self.sync_rows if self.sync_show[r["status"]].get()]
        mode = self._sync_mode()
        for r in shown[:self.SYNC_MAX_ROWS]:
            row = ctk.CTkFrame(self.sync_scroll, fg_color=self.SYNC_COLORS[r["status"]], corner_radius=4)
            row.pack(fill="x", pady=1)
            row.columnconfigure(0, weight=1, uniform="s")
            row.columnconfigure(2, weight=1, uniform="s")

            def _side(info, col):
                if info:
                    txt, sub = r["rel"], f"{disk_sync.fmt_size(info[0])} · {disk_sync.fmt_date(info[1])}"
                else:
                    txt, sub = "— manca —", ""
                ctk.CTkLabel(row, text=txt, font=ctk.CTkFont(size=12, weight="bold" if info else "normal"),
                             text_color=None if info else "gray", anchor="w", justify="left", wraplength=300).grid(row=0, column=col, sticky="ew", padx=6, pady=(3, 0))
                ctk.CTkLabel(row, text=sub or r["note"], font=ctk.CTkFont(size=10), text_color="gray", anchor="w").grid(row=1, column=col, sticky="ew", padx=6, pady=(0, 3))
            _side(r["a"], 0)
            _side(r["b"], 2)

            if r["status"] != "identical":
                sym, col = self.SYNC_ACTION_LOOK[r["action"]]
                btn = ctk.CTkButton(row, text=sym, width=58, height=28, fg_color=col, hover_color=col, font=ctk.CTkFont(size=13, weight="bold"))
                btn.configure(command=lambda rr=r, b=btn: self._sync_cycle_action(rr, b))
                btn.grid(row=0, column=1, rowspan=2, padx=6)
            else:
                ctk.CTkLabel(row, text="=", width=58, font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=1, rowspan=2, padx=6)

        if len(shown) > self.SYNC_MAX_ROWS:
            ctk.CTkLabel(self.sync_scroll, text=f"... e altri {len(shown) - self.SYNC_MAX_ROWS} file non mostrati (la sincronizzazione li include comunque).",
                         text_color="gray", font=ctk.CTkFont(size=11, slant="italic")).pack(pady=8)
        self._sync_refresh_summary()

    def _sync_cycle_action(self, row, btn):
        """Click sul pulsante di una riga: passa alla prossima azione consentita."""
        import disk_sync
        acts = disk_sync.allowed_actions(row, self._sync_mode())
        cur = row.get("action")
        nxt = acts[(acts.index(cur) + 1) % len(acts)] if cur in acts else acts[0]
        row["action"] = nxt
        sym, col = self.SYNC_ACTION_LOOK[nxt]
        btn.configure(text=sym, fg_color=col, hover_color=col)
        self._sync_refresh_summary()

    def sync_apply(self):
        from tkinter import messagebox
        import disk_sync
        import time
        a, b = self.sync_path_a.get().strip(), self.sync_path_b.get().strip()
        s = disk_sync.summarize(self.sync_rows)
        if not (s["a2b"] or s["b2a"] or s["del"]):
            return
        msg = f"Eseguire la sincronizzazione?\n\n▶ {s['a2b']} file A → B\n◀ {s['b2a']} file B → A\n🗑 {s['del']} file spostati nel cestino\nDati da copiare: {disk_sync.fmt_size(s['bytes'])}"
        if s["overwrite"]:
            msg += f"\n\n{s['overwrite']} file esistono gia' con contenuto diverso: la versione attuale finira' nel cestino _Datarium_Sync_Cestino."
        if not messagebox.askyesno("Conferma sincronizzazione", msg):
            return

        verify = self.sync_verify.get()
        total_bytes = max(s["bytes"], 1)
        self._sync_set_busy(True)
        state = {"bytes": 0, "start": time.time()}

        def _cb(i, n_jobs, rel, n):
            state["bytes"] += n
            el = max(time.time() - state["start"], 0.05)
            speed = state["bytes"] / el
            eta = int(max(0, total_bytes - state["bytes"]) / speed) if speed > 0 else 0
            eta_txt = f"{eta // 60}m {eta % 60}s" if eta >= 60 else f"{eta}s"
            self._sync_status(f"{i + 1}/{n_jobs}: {rel} · {min(100, int(state['bytes'] / total_bytes * 100))}% · {disk_sync.fmt_size(int(speed))}/s · ETA {eta_txt}",
                              min(1.0, state["bytes"] / total_bytes))

        def bg():
            try:
                failed = disk_sync.execute(self.sync_rows, a, b, verify=verify, progress_cb=_cb)
                self.after(0, lambda: self._sync_apply_done(failed))
            except Exception as e:
                self._sync_status(f"Errore durante la sincronizzazione: {e}")
                self.after(0, lambda: self._sync_set_busy(False))
        threading.Thread(target=bg, daemon=True).start()

    def _sync_apply_done(self, failed):
        from tkinter import messagebox
        self._sync_set_busy(False)
        if failed:
            details = "\n".join(f"- {rel}: {err}" for rel, err in failed[:10])
            messagebox.showwarning("Sincronizzazione con errori", f"{len(failed)} operazioni fallite:\n{details}")
        else:
            messagebox.showinfo("Sincronizzazione completata", "Fatto." + (" Copie verificate con hash." if self.sync_verify.get() else ""))
        self.sync_scan()  # riconfronta: mostra lo stato reale dopo la sincronizzazione

if __name__ == "__main__":
    try:
        app = DatariumApp()
        app.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(f"CRITICAL ERROR AT STARTUP: {e}\n")
            f.write(traceback.format_exc())
        print(f"L'applicazione ha riscontrato un errore fatale. Controlla crash_log.txt")

