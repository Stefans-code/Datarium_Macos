import os
import sys

# Ridirezione standard output/error per evitare crash in modalità --noconsole
# se qualche libreria (es. tqdm/huggingface) prova a scrivere sul terminale inesistente.
if getattr(sys, 'frozen', False):
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

        # UI Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.setup_sidebar()
        self.setup_main_content()
        
        # Default Page
        if self.ai.check_models_missing():
            self.show_page("Setup")
            threading.Thread(target=self.start_setup_flow, daemon=True).start()
        else:
            self.show_page("Home")

    def setup_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)

        self.logo_lbl = ctk.CTkLabel(self.sidebar, text="DATARIUM", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_lbl.grid(row=0, column=0, padx=20, pady=(30, 40))

        self.btn_home = ctk.CTkButton(self.sidebar, text="🏠 Home", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Home"))
        self.btn_home.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        # Bottom Buttons
        self.btn_settings = ctk.CTkButton(self.sidebar, text="⚙️ Impostazioni", fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("Settings"))
        self.btn_settings.grid(row=5, column=0, padx=20, pady=10, sticky="ew")

        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar, values=["Dark", "Light"], command=self.change_appearance_mode)
        self.appearance_mode_optionemenu.grid(row=6, column=0, padx=20, pady=(10, 30))

    def setup_main_content(self):
        self.content_container = ctk.CTkFrame(self, fg_color="transparent")
        self.content_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        
        self.pages = {}
        self.init_home_page()
        self.init_options_page()
        self.init_preview_page()
        self.init_settings_page()
        self.init_setup_page()

    def init_setup_page(self):
        page = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.pages["Setup"] = page
        
        # Centered Panel
        login_box = ctk.CTkFrame(page, width=600, height=400, corner_radius=20)
        login_box.place(relx=0.5, rely=0.5, anchor="center")
        login_box.pack_propagate(False)
        
        ctk.CTkLabel(login_box, text="DATARIUM", font=ctk.CTkFont(size=36, weight="bold")).pack(pady=(50, 10))
        ctk.CTkLabel(login_box, text="Completamento dell'installazione...", font=ctk.CTkFont(size=18), text_color="gray").pack()
        
        self.setup_status_lbl = ctk.CTkLabel(login_box, text="Preparazione dei componenti AI (6GB)...", font=ctk.CTkFont(size=14, weight="bold"))
        self.setup_status_lbl.pack(pady=(60, 10))
        
        self.setup_progress = ctk.CTkProgressBar(login_box, width=450, height=15)
        self.setup_progress.pack(pady=10)
        self.setup_progress.set(0)
        
        ctk.CTkLabel(login_box, text="L'operazione potrebbe richiedere alcuni minuti in base alla connessione.", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=20)

    def start_setup_flow(self):
        # Scarichiamo prima il modello Vision (che tira giù anche il Text se manca)
        success, error_msg = self.ai.download_model_if_needed(True, self.update_setup_status)
        if success:
            self.after(0, lambda: self.show_page("Home"))
        else:
            self.after(0, lambda: self.setup_status_lbl.configure(
                text=f"Errore: {error_msg}\nRiprova tra poco.", 
                text_color="#ef4444"
            ))

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
        
        btn_open = ctk.CTkButton(page, text="📂 Open Folder", font=ctk.CTkFont(size=22, weight="bold"), height=80, width=350, corner_radius=15, command=self.open_source_folder)
        btn_open.place(relx=0.5, rely=0.5, anchor="center")

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
        grid_f.pack(fill="x", padx=40, pady=10)
        grid_f.columnconfigure(1, weight=1)

        # Row 1: Cartella di Controllo
        ctk.CTkLabel(grid_f, text="Cartella di Controllo:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", pady=10)
        ctk.CTkLabel(grid_f, textvariable=self.control_folder, text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, anchor="w", justify="left").grid(row=0, column=1, padx=20, sticky="ew")
        ctk.CTkButton(grid_f, text="📂", width=40, command=self.open_dest_folder).grid(row=0, column=2, sticky="e")

        # Row 2: Posto Salvataggio ZIP
        ctk.CTkLabel(grid_f, text="Posto di Salvataggio ZIP:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, sticky="w", pady=10)
        ctk.CTkLabel(grid_f, textvariable=self.backup_folder, text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, anchor="w", justify="left").grid(row=1, column=1, padx=20, sticky="ew")
        ctk.CTkButton(grid_f, text="📂", width=40, command=self.open_backup_folder).grid(row=1, column=2, sticky="e")

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
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']: counts["Immagini"] += 1
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

        ctk.CTkLabel(page, text="Impostazioni", font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", pady=(0, 40))

        hw_box = ctk.CTkFrame(page, corner_radius=10)
        hw_box.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(hw_box, text="Status Hardware", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        self.hw_info_lbl = ctk.CTkLabel(hw_box, text=f"Rilevato: {self.ai.hardware_info}", text_color="#38bdf8")
        self.hw_info_lbl.pack(anchor="w", padx=20, pady=(0, 15))

        lic_box = ctk.CTkFrame(page, corner_radius=10)
        lic_box.pack(fill="x", padx=10, pady=20)
        ctk.CTkLabel(lic_box, text="Licenza", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(15, 10))
        
        hwid_entry = ctk.CTkEntry(lic_box, width=450)
        hwid_entry.insert(0, f"HWID: {self.license.get_hwid()}")
        hwid_entry.configure(state="readonly")
        hwid_entry.pack(anchor="w", padx=20)
        
        btn_file = ctk.CTkButton(lic_box, text="📁 Carica File Licenza (.datarium)", command=self.load_license_file)
        btn_file.pack(anchor="w", padx=20, pady=15)

        self.lic_status_lbl = ctk.CTkLabel(lic_box, text=f"Stato: {self.license_status}", text_color="#10b981" if self.is_licensed else "#ef4444")
        self.lic_status_lbl.pack(anchor="w", padx=20, pady=(0, 20))

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
        if not self.is_licensed:
            self.show_page("Settings")
            self.lic_status_lbl.configure(text="ATTENZIONE: Attiva la licenza per procedere!", text_color="#facc15")
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
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
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
        if not self.is_licensed:
            from tkinter import messagebox
            messagebox.showwarning("Licenza Mancante", "Devi attivare il software per usare le funzioni AI e l'organizzazione.")
            self.show_page("Settings")
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

    # Removed redundant duplicate methods.

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
