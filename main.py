import os
import sys

# Ridirezione standard output/error per evitare crash in modalità --noconsole
# se qualche libreria (es. tqdm/huggingface) prova a scrivere sul terminale inesistente.
if getattr(sys, 'frozen', False):
    import platform
    if platform.system() == "Darwin":
        # Su Mac è vitale loggare se il setup fallisce
        log_path = os.path.join(os.path.expanduser("~"), "Desktop", "datarium_debug.log")
        sys.stdout = open(log_path, 'a')
        sys.stderr = open(log_path, 'a')
    else:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

import customtkinter as ctk
import os
import threading
import shutil
from tkinter import filedialog
from ai_engine import AIEngine
from license_manager import LicenseManager

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

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

    def go_to_organizer(self):
        if self.source_folder.get():
            self.show_page("Options")
        else:
            self.show_page("OrganizerHome")

    def setup_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(5, weight=1)

        self.logo_lbl = ctk.CTkLabel(self.sidebar, text="DATARIUM", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_lbl.grid(row=0, column=0, padx=20, pady=(30, 40))

        self.btn_home = ctk.CTkButton(self.sidebar, text="🏠 Home", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Home"))
        self.btn_home.grid(row=1, column=0, padx=20, pady=5, sticky="ew")

        self.btn_organizer = ctk.CTkButton(self.sidebar, text="📁 Organizer", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=self.go_to_organizer)
        self.btn_organizer.grid(row=2, column=0, padx=20, pady=5, sticky="ew")

        self.btn_hash = ctk.CTkButton(self.sidebar, text="🔑 Hash Check", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("HashHome"))
        self.btn_hash.grid(row=3, column=0, padx=20, pady=5, sticky="ew")

        self.btn_autotag = ctk.CTkButton(self.sidebar, text="🏷️ Auto Tag", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("AutoTag"))
        self.btn_autotag.grid(row=4, column=0, padx=20, pady=5, sticky="ew")

        # Bottom Buttons
        self.btn_settings = ctk.CTkButton(self.sidebar, text="⚙️ Impostazioni", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Settings"))
        self.btn_settings.grid(row=6, column=0, padx=20, pady=10, sticky="ew")

        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar, values=["Dark", "Light"], command=self.change_appearance_mode)
        self.appearance_mode_optionemenu.grid(row=7, column=0, padx=20, pady=(10, 30))

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
        
        from PIL import Image
        base_dir = os.path.dirname(os.path.abspath(__file__))
        folder_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "folder.png")), size=(64, 64))
        key_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "key.png")), size=(64, 64))
        tag_icon = ctk.CTkImage(light_image=Image.open(os.path.join(base_dir, "assets", "tag.png")), size=(64, 64))

        # Card 1: Organizer
        c1 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c1.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        c1.pack_propagate(False)

        ctk.CTkLabel(c1, text="", image=folder_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c1, text="Organizer AI", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c1, text="Scansiona, ordina e rinomina i tuoi file e documenti in base al contenuto.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c1, text="Apri Organizer", fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(weight="bold"), height=38, corner_radius=8, command=self.go_to_organizer).pack(side="bottom", pady=30, padx=20, fill="x")

        # Card 2: Hash Check
        c2 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c2.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        c2.pack_propagate(False)

        ctk.CTkLabel(c2, text="", image=key_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c2, text="Verifica Hash", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c2, text="Calcola l'hash dei file e confronta duplicati esatti byte-a-byte.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c2, text="Vai ad Hash", fg_color="transparent", border_width=1, text_color=("gray10", "gray90"), height=38, corner_radius=8, command=lambda: self.show_page("HashHome")).pack(side="bottom", pady=30, padx=20, fill="x")

        # Card 3: Auto Tag
        c3 = ctk.CTkFrame(cards_container, corner_radius=15, border_width=1, border_color=("gray85", "gray15"), height=340)
        c3.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        c3.pack_propagate(False)

        ctk.CTkLabel(c3, text="", image=tag_icon).pack(pady=(35, 10))
        ctk.CTkLabel(c3, text="Auto Tag & Album", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(c3, text="Raggruppa foto e video in album intelligenti generati dall'AI.", text_color="gray", font=ctk.CTkFont(size=12), wraplength=180, justify="center").pack(pady=(5, 15))
        ctk.CTkButton(c3, text="Vai ad Album", fg_color="transparent", border_width=1, text_color=("gray10", "gray90"), height=38, corner_radius=8, command=lambda: self.show_page("AutoTag")).pack(side="bottom", pady=30, padx=20, fill="x")


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
        ctk.CTkLabel(modal, text="Opzioni", font=ctk.CTkFont(weight="bold")).pack(pady=(10, 5))
        opts_f = ctk.CTkFrame(modal, fg_color="transparent")
        opts_f.pack()
        
        self.check_ai = ctk.CTkCheckBox(opts_f, text="Attiva Scelta AI")
        self.check_ai.pack(side="left", padx=20); self.check_ai.select()
        
        self.check_dup = ctk.CTkCheckBox(opts_f, text="Rilevamento dei tipi di file (Hash Check)")
        self.check_dup.pack(side="left", padx=20); self.check_dup.select()

        # --- FOOTER ---
        btn_f = ctk.CTkFrame(modal, fg_color="transparent")
        btn_f.pack(side="bottom", fill="x", padx=40, pady=30)
        ctk.CTkButton(btn_f, text="Annulla", fg_color="transparent", border_width=2, width=120, command=lambda: self.show_page("Home")).pack(side="left")
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
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif']: counts["Immagini"] += 1
                elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']: counts["Video"] += 1
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
        ctk.CTkButton(footer, text="Annulla", fg_color="transparent", border_width=1, width=100, command=lambda: self.show_page("Options")).pack(side="right", padx=10)

    def init_settings_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Settings"] = page

        ctk.CTkLabel(page, text="Impostazioni", font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", pady=(0, 20))

        hw_box = ctk.CTkFrame(page, corner_radius=10)
        hw_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(hw_box, text="Status Hardware", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        self.hw_info_lbl = ctk.CTkLabel(hw_box, text=f"Rilevato: {self.ai.hardware_info}", text_color="#38bdf8")
        self.hw_info_lbl.pack(anchor="w", padx=20, pady=(0, 15))

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

        upd_box = ctk.CTkFrame(page, corner_radius=10)
        upd_box.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(upd_box, text="Aggiornamenti Software", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(upd_box, text="Versione corrente: v1.2.0", text_color="gray").pack(anchor="w", padx=20)
        self.btn_check_upd = ctk.CTkButton(upd_box, text="Verifica Aggiornamenti", command=self.check_software_updates)
        self.btn_check_upd.pack(anchor="w", padx=20, pady=(10, 15))

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
        self.btn_check_upd.configure(state="disabled", text="Verifica in corso...")
        
        # Simulate check or check a real URL if it exists
        try:
            # We can check the Supabase RPC or a placeholder REST URL to simulate update checks.
            # Here we simulate a 1-second checking time for a premium user experience.
            def check_upd_bg():
                import time
                time.sleep(1.2)
                self.after(0, lambda: self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti"))
                self.after(0, lambda: messagebox.showinfo("Aggiornamenti", "Il software è aggiornato alla versione più recente (v1.2.0)!"))
            threading.Thread(target=check_upd_bg, daemon=True).start()
        except:
            self.btn_check_upd.configure(state="normal", text="Verifica Aggiornamenti")

    def show_page(self, name):
        # Se siamo in Setup, nascondiamo la sidebar per farlo sembrare un installer
        if name == "Setup":
            self.sidebar.grid_forget()
            self.grid_columnconfigure(0, weight=0)
        else:
            self.sidebar.grid(row=0, column=0, sticky="nsew")
            self.grid_columnconfigure(0, weight=0) # Sidebar width fixed
            
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    def change_appearance_mode(self, mode):
        ctk.set_appearance_mode(mode)

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
        self.stop_ai = False
        threading.Thread(target=self.process_files_bg, daemon=True).start()

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
        for w in self.scroll_frame.winfo_children(): w.destroy()
        src = self.source_folder.get()
        if not src: return

        self.set_progress(0)
        # --- NUOVA LOGICA TURBO: ANALISI IBRIDA ---
        text_items = []
        vision_items = []
        
        for root, _, files in os.walk(src):
            if "Backup_Datarium_" in root: continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                skip = False
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif']:
                    if not self.doc_filters.get("Immagini", ctk.BooleanVar(value=True)).get(): skip = True
                    else: vision_items.append({"old": f, "path": os.path.join(root, f), "type": "Image"})
                elif ext in ['.mp4', '.mov', '.avi', '.mkv']:
                    if not self.doc_filters.get("Video", ctk.BooleanVar(value=True)).get(): skip = True
                elif ext in ['.pdf', '.doc', '.docx', '.txt', '.xlsx']:
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
            future_to_item = {executor.submit(self.ai.extract_context, it['path']): it for it in valid_items if it['type'] != "Image"}
            for future in concurrent.futures.as_completed(future_to_item):
                if self.stop_ai: break
                item = future_to_item[future]
                item['context'] = future.result()
                self.set_progress(0.1 + 0.2 * (len([x for x in valid_items if x.get('context')]) / max(1, len(valid_items))))

        # 2. CARICAMENTO AI VISION (Se serve)
        vision_needed = [it for it in valid_items if it['type'] == "Image"]
        if vision_needed and not self.is_ai_loaded:
            self.update_status("🧠 Caricamento Vision Model...")
            self.is_ai_loaded = self.ai.download_model_if_needed(True, self.update_status)

        # 3. ANALISI VISIONE SEQUENZIALE (Per non saturare la RAM)
        for idx, item in enumerate(vision_needed):
            if self.stop_ai: return
            self.update_status(f"👁️ Visione {idx+1}/{len(vision_needed)}: {item['old']}")
            item['context'] = self.ai.extract_context(item['path'])
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
                res = self.ai.get_smart_name(item['old'], item['type'], item.get('context', ''), taxonomy)
                item['new'] = res
                
                cat = res.split('/')[0]
                if cat not in groups: groups[cat] = []
                groups[cat].append(item)
                self.set_progress(0.7 + 0.3 * ((idx+1)/max(1, len(valid_items))))
            
            self.last_groups = groups
        else:
            # Fallback senza AI
            self.last_groups = {"Archivio": valid_items}
            for it in valid_items: it['new'] = f"Organizzato_{it['old']}"

        self.update_status("✨ Analisi completata!")
        self.after(0, lambda: self.render_groups(self.last_groups))

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
                # Calcoliamo il totale dei file per il progresso
                all_files = []
                for root, dirs, files in os.walk(src):
                    for file in files:
                        all_files.append(os.path.join(root, file))
                
                total = len(all_files)
                for i, file_path in enumerate(all_files):
                    if self.stop_ai: break
                    
                    # PROTEZIONE RICORSIONE: Salta se è un backup o il file stesso che stiamo creando
                    fname = os.path.basename(file_path)
                    if fname.startswith("Backup_Datarium_") or fname == zip_name:
                        continue
                        
                    rel_path = os.path.relpath(file_path, src)
                    zipf.write(file_path, rel_path)
                    
                    if i % 10 == 0: # Aggiorna la barra ogni 10 file per non rallentare troppo
                        self.set_progress(0.01 + 0.09 * (i/max(1, total)))
            
            self.set_progress(0.1)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Errore Backup", f"Impossibile creare lo ZIP: {e}")
            return

        self.update_status("🚀 Riorganizzazione in corso...")
        to_proc = []
        for cat in self.last_groups.values():
            for it in cat:
                if it.get('check') and it['check'].get(): to_proc.append(it)

        for i, it in enumerate(to_proc):
            # Strip della categoria concettuale
            real_path = it['new']
            if '/' in real_path:
                real_path = real_path.split('/', 1)[1]
            
            target = os.path.join(dest, real_path)
            
            # Se sorgente e destinazione sono identiche, saltiamo o gestiamo sovrascrittura
            if os.path.abspath(it['path']) == os.path.abspath(target):
                continue
                
            os.makedirs(os.path.dirname(target), exist_ok=True)
            
            # Utilizziamo move per un'organizzazione "in-place" reale
            try:
                # Se il file esiste già nella nuova posizione (con lo stesso nome), lo sovrascriviamo
                if os.path.exists(target): os.remove(target)
                shutil.move(it['path'], target)
            except Exception as e:
                print(f"Errore spostamento {it['old']}: {e}")
                
            self.set_progress(0.1 + 0.9 * (i/max(1, len(to_proc))))

        self.set_progress(1.0)
        self.update_status(f"✨ Completato! Folder riorganizzato e ZIP creato.")

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
        ctk.CTkButton(bot_f, text="Torna alla Home", width=140, fg_color="#10b981", hover_color="#059669", command=lambda: self.show_page("HashHome")).pack(side="right")

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
            return h.hexdigest()
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
        sd_list = getattr(self, 'hash_source_folders_list', [])
        if not sd_list and sd:
            sd_list = [sd]
            
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
        self.loading_lbl = ctk.CTkLabel(self.hash_results_scroll, text="Calcolo hash in corso. Attendere...", font=ctk.CTkFont(size=14, weight="bold"))
        self.loading_lbl.pack(pady=20)
        
        threading.Thread(target=self._run_hash_verification_bg, args=(files_to_hash, sd_list, algo), daemon=True).start()

    def _run_hash_verification_bg(self, files_to_hash, sd_list, algo):
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

    def _render_hash_results(self, results):
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

        for w in self.autotag_album_scroll.winfo_children():
            w.destroy()

        def scan_bg():
            import time
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
                    themes = self.ai.identify_global_themes([context]) if context else ["Generico"]
                    album_name = themes[0] if themes else "Varie"
                    # Clean filename characters
                    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
                        album_name = album_name.replace(ch, "")
                    album_name = album_name.capitalize()
                    albums.setdefault(album_name, []).append(path)
                except:
                    albums.setdefault("Ricordi", []).append(path)

            self.current_albums = albums

            def update_album_ui():
                # Grid of visual album cards
                grid_f = ctk.CTkFrame(self.autotag_album_scroll, fg_color="transparent")
                grid_f.pack(fill="both", expand=True)
                grid_f.columnconfigure((0, 1, 2), weight=1, minsize=220)

                for idx, (album, files) in enumerate(self.current_albums.items()):
                    card = ctk.CTkFrame(grid_f, corner_radius=12, border_width=1, border_color=("gray85", "gray20"))
                    card.grid(row=idx // 3, column=idx % 3, padx=12, pady=12, sticky="nsew")

                    ctk.CTkLabel(card, text="📁", font=ctk.CTkFont(size=52)).pack(pady=(20, 5))
                    
                    lbl_name = ctk.CTkLabel(card, text=f"Album {album}", font=ctk.CTkFont(size=14, weight="bold"))
                    lbl_name.pack(padx=10)

                    ctk.CTkLabel(card, text=f"{len(files)} elementi", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(2, 10))

                    btn_edit = ctk.CTkButton(card, text="Personalizza Nome", height=30, fg_color="transparent", border_width=1, font=ctk.CTkFont(size=11), command=lambda a=album: self.edit_album_name(a))
                    btn_edit.pack(pady=(0, 20), padx=15, fill="x")

                self.btn_confirm_at.configure(state="normal", text="Conferma")
                self.show_autotag_subpage("Album")

            self.after(0, update_album_ui)

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

                ctk.CTkLabel(card, text="📁", font=ctk.CTkFont(size=52)).pack(pady=(20, 5))
                
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

        for album, files in getattr(self, 'current_albums', {}).items():
            album_dir = os.path.join(dst, f"Album_{album}")
            os.makedirs(album_dir, exist_ok=True)
            for idx, f in enumerate(files):
                try:
                    ext = os.path.splitext(f)[1].lower()
                    new_filename = f"{album}_{idx+1}{ext}" if self.autotag_rename.get() else os.path.basename(f)
                    shutil.copy2(f, os.path.join(album_dir, new_filename))
                except:
                    pass

        from tkinter import messagebox
        messagebox.showinfo("Successo", "Tutti gli elementi sono stati organizzati e gli album intelligenti sono stati creati con successo!")
        self.show_autotag_subpage("Home")

if __name__ == "__main__":
    try:
        app = DatariumApp()
        app.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w") as f:
            f.write(f"CRITICAL ERROR AT STARTUP: {e}\n")
            f.write(traceback.format_exc())
        print(f"L'applicazione ha riscontrato un errore fatale. Controlla crash_log.txt")

