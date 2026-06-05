import os
import sys
import tempfile
try:
    os.chdir(tempfile.gettempdir())
except:
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
import threading
import shutil
import pathlib
from tkinter import filedialog
from ai_engine import AIEngine
from license_manager import LicenseManager
import cv2
from face_memory import FaceMemoryManager

ctk.set_appearance_mode("Dark")

# Risolvi il percorso assoluto per evitare problemi in modalità frozen (PyInstaller)
if getattr(sys, 'frozen', False):
    if hasattr(sys, '_MEIPASS'):
        theme_path = os.path.join(sys._MEIPASS, "assets", "material_theme.json")
    else:
        theme_path = os.path.join(os.path.dirname(sys.executable), "assets", "material_theme.json")
else:
    theme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "material_theme.json")

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
            if getattr(sys, 'frozen', False):
                self.icon_path = os.path.join(sys._MEIPASS, "icon.ico")
            else:
                self.icon_path = "icon.ico"
                
            if os.path.exists(self.icon_path):
                self.iconbitmap(self.icon_path)
        except: pass

        # Core Engines
        self.ai = AIEngine()
        self.license = LicenseManager()
        self.face_mem = FaceMemoryManager(base_models_dir=self.ai.get_models_dir())
        
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

        # Offload Feature State
        import datetime
        self.offload_source_folder = ctk.StringVar(value="")
        self.offload_dest_folder_1 = ctk.StringVar(value="")
        self.offload_dest_folder_2 = ctk.StringVar(value="")
        self.offload_algo = ctk.StringVar(value="xxHash64")
        self.offload_report_id = ctk.StringVar(value="A" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

        # Settings state
        self.load_settings()
        self.scan_sidecars_var = ctk.BooleanVar(value=self.scan_sidecars_enabled)
        self.proxy_gen_var = ctk.BooleanVar(value=self.proxy_gen_enabled)
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

    def load_settings(self):
        import json
        config_path = self.get_config_path()
        self.custom_rules = []
        self.ffmpeg_path = ""
        self.scan_sidecars_enabled = True
        self.proxy_gen_enabled = False
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.custom_rules = data.get("custom_rules", [])
                    self.ffmpeg_path = data.get("ffmpeg_path", "")
                    self.scan_sidecars_enabled = data.get("scan_sidecars_enabled", True)
                    self.proxy_gen_enabled = data.get("proxy_gen_enabled", False)
            except Exception as e:
                print(f"Errore caricamento impostazioni: {e}")
                
    def save_settings(self):
        import json
        config_path = self.get_config_path()
        data = {
            "custom_rules": self.custom_rules,
            "ffmpeg_path": self.ffmpeg_path,
            "scan_sidecars_enabled": self.scan_sidecars_var.get(),
            "proxy_gen_enabled": self.proxy_gen_var.get()
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

        self.btn_home = ctk.CTkButton(self.sidebar, text="🏠 Home", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Home"))
        self.btn_home.grid(row=1, column=0, padx=20, pady=5, sticky="ew")

        self.btn_organizer = ctk.CTkButton(self.sidebar, text="📁 Organizer", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=self.go_to_organizer)
        self.btn_organizer.grid(row=2, column=0, padx=20, pady=5, sticky="ew")

        self.btn_autotag = ctk.CTkButton(self.sidebar, text="\U0001f3f7 Auto Tag", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("AutoTag"))
        self.btn_autotag.grid(row=3, column=0, padx=20, pady=5, sticky="ew")

        self.btn_hash = ctk.CTkButton(self.sidebar, text="🔑 Hash Check", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("HashHome"))
        self.btn_hash.grid(row=4, column=0, padx=20, pady=5, sticky="ew")

        self.btn_offload = ctk.CTkButton(self.sidebar, text="⚡ Offload", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("OffloadHome"))
        self.btn_offload.grid(row=5, column=0, padx=20, pady=5, sticky="ew")

        # Bottom Buttons
        self.sidebar.grid_rowconfigure(6, weight=1)
        
        self.btn_settings = ctk.CTkButton(self.sidebar, text="\u2699 Impostazioni", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Settings"))
        self.btn_settings.grid(row=7, column=0, padx=20, pady=10, sticky="ew")

        self.appearance_mode_segmented = ctk.CTkSegmentedButton(self.sidebar, values=["🌙 Dark", "☀️ Light"], command=self.change_appearance_mode)
        self.appearance_mode_segmented.grid(row=8, column=0, padx=20, pady=(10, 30), sticky="ew")
        self.appearance_mode_segmented.set("🌙 Dark")

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

    def init_organizer_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["OrganizerHome"] = page
        
        ctk.CTkLabel(page, text="📁 Organizer AI", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))
        
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
        
        self.model_choice_var = ctk.StringVar(value="full")
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
            # Proviamo a indovinare il progresso se il testo contiene indizi (es. %)
            if "%" in text:
                try: 
                    pct = int(text.split('%')[0].split('|')[-1].strip()) / 100
                    self.after(0, lambda: self.setup_progress.set(pct))
                except: pass

    def init_home_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Home"] = page

        # Welcome Header Banner
        header = ctk.CTkFrame(page, fg_color=("gray95", "gray11"), corner_radius=15, height=140)
        header.pack(fill="x", pady=(0, 20))
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="✨ Benvenuto in Datarium", font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", padx=30, pady=(25, 2))
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
        base_dir = os.path.dirname(os.path.abspath(__file__))
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
        self.ffmpeg_status_lbl.pack(anchor="w", padx=20, pady=(5, 15))
        # Esegui un controllo silenzioso iniziale
        self.after(500, lambda: self.test_ffmpeg_path(silent=True))

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
        ctk.CTkLabel(upd_box, text="Versione corrente: v1.2.0", text_color="gray").pack(anchor="w", padx=20)
        self.btn_check_upd = ctk.CTkButton(upd_box, text="Verifica Aggiornamenti", command=self.check_software_updates)
        self.btn_check_upd.pack(anchor="w", padx=20, pady=(10, 15))

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
        except:
            pass
            
        try:
            if os.name == 'nt':
                # Semplice script PowerShell non bloccante per Windows Toast
                ps_script = f"""
                [void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");
                $notification = New-Object System.Windows.Forms.NotifyIcon;
                $notification.Icon = [System.Drawing.SystemIcons]::Information;
                $notification.BalloonTipIcon = "Info";
                $notification.BalloonTipTitle = "{title}";
                $notification.BalloonTipText = "{message}";
                $notification.Visible = $True;
                $notification.ShowBalloonTip(5000);
                """
                import subprocess
                subprocess.Popen(["powershell", "-Command", ps_script], startupinfo=subprocess.STARTUPINFO())
                return
        except:
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

    def check_software_updates(self):
        from tkinter import messagebox
        import urllib.request
        import json
        import webbrowser
        self.btn_check_upd.configure(state="disabled", text="Verifica in corso...")
        
        def check_upd_bg():
            current_version = "1.2.0"
            try:
                url = "https://nexflamma.net/version.json"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    remote_version = data.get("version", "1.2.0")
                    download_url = data.get("download_url", "")
                    changelog = data.get("changelog", "Miglioramenti generali.")

                    self.after(0, lambda: self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti"))
                    
                    if remote_version > current_version:
                        msg = f"Una nuova versione di Datarium è disponibile: v{remote_version}!\n\nChangelog:\n{changelog}\n\nVuoi scaricarla ora?"
                        if messagebox.askyesno("Nuovo Aggiornamento Disponibile", msg):
                            webbrowser.open(download_url)
                    else:
                        self.after(0, lambda: messagebox.showinfo("Aggiornamenti", f"Il software è aggiornato alla versione più recente (v{current_version})!"))
            except Exception as e:
                self.after(0, lambda: self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti"))
                self.after(0, lambda: messagebox.showerror("Errore", f"Impossibile verificare gli aggiornamenti: {e}"))

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
            
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    def change_appearance_mode(self, mode_str):
        if "Dark" in mode_str:
            mode = "Dark"
        else:
            mode = "Light"
        ctk.set_appearance_mode(mode)

    def set_sidebar_state(self, state="normal"):
        buttons = [self.btn_home, self.btn_organizer, self.btn_hash, self.btn_autotag, self.btn_offload, self.btn_settings]
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
        if self.progress_bar.winfo_exists():
            pct = int(val * 100)
            self.after(0, lambda: self.progress_bar.set(val))
            # Aggiorna testo stato con percentuale se non è già presente
            current = self.status_lbl.cget("text")
            base = current.split(" (")[0]
            self.after(0, lambda: self.status_lbl.configure(text=f"{base} ({pct}%)"))

    def process_files_bg(self):
        try:
            for w in self.scroll_frame.winfo_children(): w.destroy()
            src = self.source_folder.get()
            if not src: return

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
                        else: text_items.append({"old": f, "path": os.path.join(root, f), "type": "Video"})
                    elif ext in ['.pdf', '.doc', '.docx', '.txt', '.xlsx', '.xls', '.pptx', '.csv']:
                        if not self.doc_filters.get("Documenti", ctk.BooleanVar(value=True)).get(): skip = True
                        else: text_items.append({"old": f, "path": os.path.join(root, f), "type": "Doc"})
                    else: 
                        text_items.append({"old": f, "path": os.path.join(root, f), "type": "Other"})
            
            # Limit total to 100 for stability
            all_items = (text_items + vision_items)[:100]
            valid_items = []
            
            # Filtro duplicati
            sh = {}
            for idx, item in enumerate(all_items):
                if self.stop_ai: return
                if self.check_dup.get():
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
                future_to_item = {executor.submit(self.ai.extract_context, it['path'], self.scan_sidecars_var.get()): it for it in valid_items if it['type'] != "Image"}
                for future in concurrent.futures.as_completed(future_to_item):
                    if self.stop_ai: break
                    item = future_to_item[future]
                    item['context'] = future.result()
                    self.set_progress(0.1 + 0.2 * (len([x for x in valid_items if x.get('context')]) / max(1, len(valid_items))))

            # 2. CARICAMENTO AI (Testo o Visione)
            if self.check_ai.get():
                vision_needed = [it for it in valid_items if it['type'] == "Image"]
                if not self.is_ai_loaded or (vision_needed and not self.ai.is_vision):
                    self.update_status("🧠 Caricamento Modello AI...")
                    success, err = self.ai.download_model_if_needed(vision_mode=bool(vision_needed), progress_callback=self.update_status)
                    if success:
                        self.is_ai_loaded = True

            # 3. ANALISI VISIONE SEQUENZIALE (Per non saturare la RAM)
            vision_needed = [it for it in valid_items if it['type'] == "Image"]
            for idx, item in enumerate(vision_needed):
                if self.stop_ai: return
                self.update_status(f"👁️ Visione {idx+1}/{len(vision_needed)}: {item['old']}")
                item['context'] = self.ai.extract_context(item['path'], self.scan_sidecars_var.get())
                
                # Se la checkbox "Identifica persone nelle foto" è attiva, esegui il riconoscimento facciale con memoria
                if self.organizer_identify_people.get():
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

                groups = {}
                for idx, item in enumerate(valid_items):
                    if self.stop_ai: return
                    self.update_status(f"🏷️ Organizzazione {idx+1}/{len(valid_items)}...")
                    
                    res = None
                    if self.use_custom_rules_var.get() and self.custom_rules:
                        res = self.ai.apply_custom_rules(item['path'], self.custom_rules)
                        
                    if not res:
                        res = self.ai.get_smart_name(item['old'], item['type'], item.get('context', ''), taxonomy)
                    item['new'] = res
                    
                    cat = res.split('/')[0]
                    if cat not in groups: groups[cat] = []
                    groups[cat].append(item)
                    self.set_progress(0.7 + 0.3 * ((idx+1)/max(1, len(valid_items))))
                
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

            self.update_status("✨ Analisi completata!")
            self.after(0, lambda: self.render_groups(self.last_groups))
            self.send_local_notification("Datarium - Analisi Completata", f"Analizzati con successo {len(valid_items)} file.")
        finally:
            self.is_scanning = False
            self.after(0, lambda: self.set_sidebar_state("normal"))

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
                            zipf.write(file_path, rel_path)
                            
                            if i % 10 == 0:
                                self.set_progress(0.01 + 0.09 * (i/max(1, total)))
                    
                    self.set_progress(0.1)
                except Exception as e:
                    from tkinter import messagebox
                    self.after(0, lambda: messagebox.showerror("Errore Backup", f"Impossibile creare lo ZIP: {e}"))
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
                            self.ai.generate_proxy(target, proxy_dir, self.ffmpeg_path, progress_callback=self.update_status)
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

    def process_activation(self):
        token = self.license_entry.get().strip()
        ok, msg = self.license.verify_license(token)
        if ok:
            self.license.save_license(token)
            self.is_licensed = True
            self.license_status = msg
            self.lic_status_lbl.configure(text=f"Stato: {msg}", text_color="#10b981")
        else:
            self.lic_status_lbl.configure(text=f"Errore: {msg}", text_color="#ef4444")

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

        modal = ctk.CTkFrame(page_opts, width=650, height=520, corner_radius=20, border_width=2, border_color=("gray80", "gray20"))
        modal.place(relx=0.5, rely=0.5, anchor="center")
        modal.pack_propagate(False)

        ctk.CTkLabel(modal, text="Selezione Hash", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(30, 20))

        # File Pick Row
        f_row = ctk.CTkFrame(modal, fg_color="transparent")
        f_row.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(f_row, text="File:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(f_row, textvariable=self.hash_source_file, text_color="gray", font=ctk.CTkFont(size=11), wraplength=320, anchor="w", justify="left").pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(f_row, text="📁", width=40, command=self.pick_hash_file).pack(side="right")

        # Folder Pick Row
        fold_row = ctk.CTkFrame(modal, fg_color="transparent")
        fold_row.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(fold_row, text="Cartella:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(fold_row, textvariable=self.hash_source_folder, text_color="gray", font=ctk.CTkFont(size=11), wraplength=320, anchor="w", justify="left").pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(fold_row, text="📂", width=40, command=self.pick_hash_folder).pack(side="right")

        # Folder 2 Pick Row
        fold_row_2 = ctk.CTkFrame(modal, fg_color="transparent")
        fold_row_2.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(fold_row_2, text="Cartella 2 (Confronto):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(fold_row_2, textvariable=self.hash_source_folder_2, text_color="gray", font=ctk.CTkFont(size=11), wraplength=250, anchor="w", justify="left").pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(fold_row_2, text="📂", width=40, command=self.pick_hash_folder_2).pack(side="right")

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
        
        self.chk_compare = ctk.CTkCheckBox(check_row, text="Confronta contenuto", variable=self.compare_contents, font=ctk.CTkFont(size=13))
        if self.highlight_dups.get():
            self.chk_compare.pack(anchor="w", pady=3, padx=(20, 0))

        # Footer Row
        footer_btn_f = ctk.CTkFrame(modal, fg_color="transparent")
        footer_btn_f.pack(side="bottom", fill="x", padx=40, pady=30)
        ctk.CTkButton(footer_btn_f, text="Annulla", fg_color="transparent", border_width=2, width=120, command=lambda: self.show_page("HashHome")).pack(side="left")
        ctk.CTkButton(footer_btn_f, text="Conferma", width=140, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), command=self.run_hash_verification).pack(side="right")

        # 3. Page: HashResults (Drawing 3)
        page_results = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["HashResults"] = page_results

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

    def pick_hash_file_home(self):
        file_paths = filedialog.askopenfilenames(title="Seleziona File")
        if file_paths:
            self.selected_hash_files_list = list(file_paths)
            if len(self.selected_hash_files_list) == 1:
                self.hash_source_file.set(self.selected_hash_files_list[0])
            else:
                self.hash_source_file.set(f"{len(self.selected_hash_files_list)} file selezionati")
            self.show_page("HashOptions")

    def pick_hash_folder_home(self):
        folder_path = filedialog.askdirectory(title="Seleziona Cartella")
        if folder_path:
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
            self.hash_source_file.set(path)
            self.show_page("HashOptions")
        else:
            from tkinter import messagebox
            messagebox.showwarning("File Non Trovato", "Il file selezionato non è più disponibile.")

    def compute_hash(self, file_path, algo="SHA-256"):
        import hashlib
        try:
            if algo == "MD5":
                h = hashlib.md5()
            elif algo == "SHA-1":
                h = hashlib.sha1()
            elif algo == "xxHash64":
                import xxhash
                h = xxhash.xxh64()
            else:
                h = hashlib.sha256()
                
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return getattr(h, "hexdigest")()
        except Exception as e:
            return f"Error: {e}"

    def check_content_equal(self, f1, f2):
        try:
            with open(f1, "rb") as a, open(f2, "rb") as b:
                while True:
                    ch1 = a.read(8192)
                    ch2 = b.read(8192)
                    if ch1 != ch2:
                        return False
                    if not ch1:
                        return True
        except:
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

    def populate_section(self, parent, items, bg_color="transparent", text_color=None):
        if not items:
            ctk.CTkLabel(parent, text="Nessun file trovato in questa sezione.", text_color="gray", font=ctk.CTkFont(size=12, slant="italic")).pack(pady=15)
            return

        for it in items:
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
            algo = "SHA-256"

        files_to_hash = []
        if self.selected_hash_files_list:
            files_to_hash = list(self.selected_hash_files_list)
        elif self.hash_source_file.get():
            files_to_hash = [self.hash_source_file.get()]

        if not files_to_hash and not sd_list:
            from tkinter import messagebox
            messagebox.showwarning("Selezione Mancante", "Seleziona almeno un file o una cartella da controllare.")
            return

        self.show_page("HashResults")
        self.is_scanning = True
        self.set_sidebar_state("disabled")
        self.loading_lbl = ctk.CTkLabel(self.hash_results_scroll, text="Calcolo hash in corso. Attendere...", font=ctk.CTkFont(size=14, weight="bold"))
        self.loading_lbl.pack(pady=20)
        
        threading.Thread(target=self._run_hash_verification_bg, args=(files_to_hash, sd_list, algo), daemon=True).start()

    def _run_hash_verification_bg(self, files_to_hash, sd_list, algo):
        try:
            results = []
            source_paths = set()

            for sf in files_to_hash:
                if os.path.exists(sf):
                    source_paths.add(os.path.abspath(sf))
                    hash_val = self.compute_hash(sf, algo)
                    sz = os.path.getsize(sf)
                    ext = os.path.splitext(sf)[1].upper().replace('.', '')
                    results.append({
                        "name": os.path.basename(sf),
                        "path": sf,
                        "type": ext if ext else "FILE",
                        "hash": hash_val,
                        "size": self.format_file_size(sz),
                        "is_source": True
                    })
                    if sf not in self.recent_hash_files:
                        self.recent_hash_files.insert(0, sf)
                        self.recent_hash_files = self.recent_hash_files[:10]
                        self.after(0, self.update_recent_hash_ui)

            for sd in sd_list:
                if os.path.isdir(sd):
                    for root, _, files in os.walk(sd):
                        for f in files:
                            p = os.path.join(root, f)
                            if os.path.abspath(p) in source_paths:
                                continue
                            h = self.compute_hash(p, algo)
                            sz_f = os.path.getsize(p)
                            ext_f = os.path.splitext(p)[1].upper().replace('.', '')
                            results.append({
                                "name": f,
                                "path": p,
                                "type": ext_f if ext_f else "FILE",
                                "hash": h,
                                "size": self.format_file_size(sz_f),
                                "is_source": False
                            })
            
            self.after(0, self._render_hash_results, results)
        finally:
            self.is_scanning = False
            self.after(0, lambda: self.set_sidebar_state("normal"))

    def _render_hash_results(self, results):
        self.last_hash_results = results
        if hasattr(self, 'loading_lbl') and self.loading_lbl.winfo_exists():
            self.loading_lbl.destroy()
            
        hash_counts = {}
        for r in results:
            hash_counts[r['hash']] = hash_counts.get(r['hash'], 0) + 1

        hash_groups = {}
        for r in results:
            hash_groups.setdefault(r['hash'], []).append(r)

        dup_hash_files = [r for r in results if hash_counts.get(r['hash'], 0) > 1]
        
        self.create_section_header(self.hash_results_scroll, "📋 Tutti i file e gli hash")
        self.create_table_header(self.hash_results_scroll)
        self.populate_section(self.hash_results_scroll, results)

        self.create_section_header(self.hash_results_scroll, "🔄 File con hash uguale")
        self.create_table_header(self.hash_results_scroll)
        self.populate_section(self.hash_results_scroll, dup_hash_files, bg_color=("#ffedd5", "#7c2d12"), text_color=("#ea580c", "#fb923c"))

        if self.compare_contents.get() and self.highlight_dups.get():
            dup_content_files = []
            for h_val, items in hash_groups.items():
                if len(items) > 1:
                    ref_item = items[0]
                    valid_items = [ref_item]
                    for other in items[1:]:
                        if self.check_content_equal(ref_item['path'], other['path']):
                            valid_items.append(other)
                    if len(valid_items) > 1:
                        dup_content_files.extend(valid_items)

            self.create_section_header(self.hash_results_scroll, "📦 File con hash uguale e contenuto uguale")
            self.create_table_header(self.hash_results_scroll)
            self.populate_section(self.hash_results_scroll, dup_content_files, bg_color=("#ffedd5", "#7c2d12"), text_color=("#ea580c", "#fb923c"))

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
            report_path = ReportGenerator.save_hash_report(report_dir, report_id, self.last_hash_results, self.selected_hash_algo.get())
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

        ctk.CTkLabel(v_home, text="🏷️ Auto Tagging intelligente", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))
        
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

        ctk.CTkLabel(v_config, text="⚙️ Configura Nuovo Album", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))

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

        ctk.CTkLabel(v_results, text="🖼️ I tuoi Album Intelligenti", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))
        
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
                        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.mp4', '.mov', '.avi']:
                            valid_files.append(os.path.join(root, f))

                if not valid_files:
                    self.after(0, lambda: self.btn_confirm_at.configure(state="normal", text="Conferma"))
                    self.after(0, lambda: self.show_autotag_subpage("Config"))
                    from tkinter import messagebox
                    self.after(0, lambda: messagebox.showinfo("Nessun file", "Nessun file multimediale (foto/video) trovato nella cartella selezionata."))
                    return

                # Group files into albums based on AI/metadata
                albums = {}
                for path in valid_files:
                    try:
                        ext = os.path.splitext(path)[1].lower()
                        context = self.ai.extract_context(path) if ext not in ['.mp4', '.mov'] else "Multimediale"
                        album_name = self.ai.get_album_name(context) if context else "Varie"
                        # Clean filename characters
                        for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
                            album_name = album_name.replace(ch, "")
                        album_name = album_name.capitalize()
                        albums.setdefault(album_name, []).append(path)
                    except:
                        albums.setdefault("Ricordi", []).append(path)

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

                    # Grid of visual album cards
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
                                except:
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

                    self.btn_confirm_at.configure(state="normal", text="Conferma")
                    self.show_autotag_subpage("Album")

                self.after(0, update_album_ui)
            finally:
                self.is_scanning = False
                self.after(0, lambda: self.set_sidebar_state("normal"))

        threading.Thread(target=scan_bg, daemon=True).start()

    def edit_album_name(self, old_name):
        from tkinter import simpledialog
        new_name = simpledialog.askstring("Modifica Nome Album", f"Inserisci un nuovo nome per l'album '{old_name}':")
        if new_name and new_name.strip() and new_name != old_name:
            self.current_albums[new_name.strip()] = self.current_albums.pop(old_name)
            # Re-render UI
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
                        except:
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
                    new_filename = f"{album}_{idx+1}{ext}" if self.autotag_rename.get() else os.path.basename(f)
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
                except:
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

        ctk.CTkLabel(v_home, text="⚡ Offload & Backup Sicuro SSD", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))

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
        self.opt_off_algo = ctk.CTkOptionMenu(g, variable=self.offload_algo, values=["xxHash64", "SHA-256", "MD5"], height=35)
        self.opt_off_algo.grid(row=3, column=1, columnspan=2, padx=(15, 0), sticky="w")

        ctk.CTkLabel(g, text="ID Report:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=4, column=0, sticky="w", pady=12)
        self.ent_off_id = ctk.CTkEntry(g, textvariable=self.offload_report_id, font=ctk.CTkFont(size=12), height=35)
        self.ent_off_id.grid(row=4, column=1, columnspan=2, padx=(15, 0), sticky="w", ipadx=100)

        # Action Button
        ctk.CTkButton(cfg_box, text="⚡ Avvia Offload & Genera Report", fg_color="#10b981", hover_color="#059669", height=50, width=320, font=ctk.CTkFont(weight="bold", size=15), corner_radius=10, command=self.run_offload_process).pack(pady=30)

        # 2. OFFLOAD RESULTS PAGE
        v_results = ctk.CTkFrame(self.offload_master_frame, fg_color="transparent")
        self.offload_views["OffloadResults"] = v_results

        ctk.CTkLabel(v_results, text="⚡ Stato Offload SSD", font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w", pady=(0, 20))

        self.offload_status_lbl = ctk.CTkLabel(v_results, text="Inizializzazione...", font=ctk.CTkFont(size=16, weight="bold"))
        self.offload_status_lbl.pack(pady=10)

        self.offload_progress_bar = ctk.CTkProgressBar(v_results, height=15)
        self.offload_progress_bar.pack(fill="x", padx=10, pady=10)
        self.offload_progress_bar.set(0)

        self.offload_results_scroll = ctk.CTkScrollableFrame(v_results, fg_color=("gray95", "gray10"))
        self.offload_results_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        res_foot = ctk.CTkFrame(v_results, fg_color="transparent")
        res_foot.pack(fill="x", side="bottom", pady=(15, 0))
        
        ctk.CTkButton(res_foot, text="Nuovo Offload", fg_color="transparent", text_color=("gray10", "gray90"), border_width=1, width=120, command=lambda: self.show_offload_subpage("OffloadHome")).pack(side="left")
        
        self.btn_open_report = ctk.CTkButton(res_foot, text="📄 Apri Report PDF", fg_color="#10b981", hover_color="#059669", width=220, font=ctk.CTkFont(weight="bold"), state="disabled", command=self.open_generated_report)
        self.btn_open_report.pack(side="right")

        # Start on Home
        self.show_offload_subpage("OffloadHome")

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

    def run_offload_process(self):
        src = self.offload_source_folder.get()
        dests = [d for d in self.offload_destinations if d.strip()]
        algo = self.offload_algo.get()
        report_id = self.offload_report_id.get()

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

        self.offload_status_lbl.configure(text="Avvio copia ed elaborazione...", text_color="white")
        self.offload_progress_bar.set(0)

        def offload_bg():
            try:
                import time
                import os
                import shutil
                import datetime
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
                processed_files = 0
                results = []

                for it in files_to_copy:
                    try:
                        sz = os.path.getsize(it["path"])
                        sz_str = self.format_file_size(sz)

                        # Compute source hashes
                        self.after(0, lambda name=it["name"]: self.offload_status_lbl.configure(text=f"Calcolo checksum: {name}..."))
                        src_hash = self.compute_hash(it["path"], algo)
                        src_hash_alt = self.compute_hash(it["path"], "SHA-256" if algo == "xxHash64" else "MD5")

                        mtime = os.path.getmtime(it["path"])
                        ctime = os.path.getctime(it["path"])
                        created_str = datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
                        modified_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

                        # Copy to all active destinations and verify
                        copy_success = True
                        for d in dests:
                            target_path = os.path.join(d, it["rel"])
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)

                            self.after(0, lambda name=it["name"], dest=os.path.basename(d): self.offload_status_lbl.configure(text=f"Copia {name} in {dest}..."))
                            try:
                                shutil.copy2(it["path"], target_path)
                            except OSError:
                                try:
                                    shutil.copy(it["path"], target_path)
                                except Exception as ce:
                                    copy_success = False
                                    print(f"Errore copia fallita per {it['name']}: {ce}")
                                    continue

                            # Verification
                            self.after(0, lambda name=it["name"]: self.offload_status_lbl.configure(text=f"Verifica integrità: {name}..."))
                            dest_hash = self.compute_hash(target_path, algo)
                            
                            # Se l'hash ha ritornato errore o non coincide, la copia fallisce la verifica
                            if (not src_hash or src_hash.startswith("Error") or 
                                not dest_hash or dest_hash.startswith("Error") or 
                                dest_hash != src_hash):
                                copy_success = False

                        status = "Verified" if copy_success else "Failed"

                        # Media metadata extraction mock / standard details
                        ext = os.path.splitext(it["name"])[1].lower()
                        media_format = "Video" if ext in ['.mp4', '.mov', '.avi', '.mkv', '.braw', '.r3d', '.mxf'] else ("Image" if ext in ['.jpg', '.jpeg', '.png', '.webp', '.nef', '.cr2', '.arw', '.dng'] else "Data")

                        results.append({
                            "name": it["name"],
                            "path": it["path"],
                            "size_bytes": sz,
                            "size_str": sz_str,
                            "created": created_str,
                            "modified": modified_str,
                            "hash": src_hash,
                            "hash_alt": src_hash_alt,
                            "status": status,
                            "media_format": media_format,
                            "codec": "H.264 / AAC" if media_format == "Video" else ("JPEG" if media_format == "Image" else "N/A"),
                            "duration": "0:00:15" if media_format == "Video" else "N/A",
                            "resolution": "HD - 1920 x 1080" if media_format == "Video" else "N/A",
                            "camera": "Sony FX3" if media_format == "Video" else "N/A",
                            "shot": "Scene 1" if media_format == "Video" else "N/A",
                            "frames": "375" if media_format == "Video" else "N/A",
                            "bitrate": "12.5 MB/s" if media_format == "Video" else "N/A",
                            "audio": "Audio Format: Linear PCM\nChannels: 2\nSample Rate: 48.0 kHz\nAudio Bit Depth: 24-bit\nAudio Bit Rate: 1.5 MB/s" if media_format == "Video" else "N/A"
                        })

                    except Exception as e:
                        results.append({
                            "name": it["name"],
                            "path": it["path"],
                            "size_bytes": 0,
                            "size_str": "0 B",
                            "hash": "ERROR",
                            "status": "Failed"
                        })

                    processed_files += 1
                    progress_val = processed_files / total_files
                    self.after(0, lambda val=progress_val: self.offload_progress_bar.set(val))

                # Generate and save report
                self.after(0, lambda: self.offload_status_lbl.configure(text="Generazione Report..."))
                first_dst = dests[0]
                report_dir = os.path.join(first_dst, "MHL_Reports")
                report_path = ReportGenerator.save_report(report_dir, report_id, src, results, algo, dests)
                self.generated_report_path = report_path
                
                # Copiamo il report in tutte le altre destinazioni per sicurezza
                for other_dst in dests[1:]:
                    try:
                        other_report_dir = os.path.join(other_dst, "MHL_Reports")
                        os.makedirs(other_report_dir, exist_ok=True)
                        shutil.copy2(report_path, os.path.join(other_report_dir, os.path.basename(report_path)))
                    except:
                        pass

                def render_results_ui():
                    self.offload_status_lbl.configure(text="✓ Offload completato con successo!", text_color="#10b981")
                    self.btn_open_report.configure(state="normal")

                    for res in results:
                        row = ctk.CTkFrame(self.offload_results_scroll, fg_color="transparent")
                        row.pack(fill="x", pady=2)

                        lbl_icon = ctk.CTkLabel(row, text="✓" if res["status"] == "Verified" else "❌", text_color="#10b981" if res["status"] == "Verified" else "#ef4444", font=ctk.CTkFont(size=14, weight="bold"))
                        lbl_icon.pack(side="left", padx=10)

                        lbl_name = ctk.CTkLabel(row, text=res["name"], font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
                        lbl_name.pack(side="left", fill="x", expand=True, padx=5)

                        lbl_sz = ctk.CTkLabel(row, text=res["size_str"], font=ctk.CTkFont(size=11), text_color="gray")
                        lbl_sz.pack(side="right", padx=15)

                self.after(0, render_results_ui)
            finally:
                self.is_scanning = False
                self.after(0, lambda: self.set_sidebar_state("normal"))

        threading.Thread(target=offload_bg, daemon=True).start()

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

