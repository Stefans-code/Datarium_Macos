"""
Ergonomia e accessibilita' dell'interfaccia (riferimento: ISO 9241-110 / 9241-112 / 9241-171,
WCAG 2.1 AA per contrasto e tastiera).

CustomTkinter di base NON e' utilizzabile da tastiera: pulsanti, checkbox, radio e menu
sono disegnati su un Canvas che non prende mai il focus, quindi Tab non li raggiunge e
Invio/Spazio non li attiva. install() corregge questo a livello di classe, una volta sola,
PRIMA che venga creato qualunque widget: ogni controllo diventa raggiungibile con Tab,
attivabile con Spazio/Invio e mostra un anello di focus ben visibile (solo quando il focus
arriva da tastiera: un clic del mouse non accende l'anello, come :focus-visible sul web).

Qui vivono anche i colori semantici a contrasto verificato (>= 4.5:1 sul tema chiaro E
scuro), i tooltip, le notifiche non bloccanti (toast) e la guida scorciatoie.
"""
import tkinter
import customtkinter as ctk

# ---------------------------------------------------------------------------------------
# Colori semantici (chiaro, scuro). I vecchi "gray"/"#ef4444"/"#10b981" fissi avevano
# contrasto 1.9:1 - 3.7:1 sul tema chiaro (sotto la soglia 4.5:1 per il testo normale).
# Valori verificati contro gli sfondi del tema: #ffffff / #f3f4f6 (chiaro), #12121a / #09090d (scuro).
# ---------------------------------------------------------------------------------------
MUTED = ("gray35", "gray65")          # testo secondario/descrizioni   7.0:1 / 7.6:1
ERROR = ("#b91c1c", "#f87171")        # errori                         6.5:1 / 6.9:1
SUCCESS = ("#047857", "#34d399")      # esito positivo                 5.5:1 / 10:1
INFO = ("#0369a1", "#38bdf8")         # informazioni/stato in corso    5.9:1 / 9.0:1
WARNING = ("#b45309", "#fbbf24")      # avvisi                         5.0:1 / 11:1
FOCUS_RING = ("#d97706", "#fbbf24")   # anello di focus (contrasto non-testo >= 3:1)

_installed = False


def _color(value):
    if isinstance(value, (tuple, list)):
        return value[0] if ctk.get_appearance_mode() == "Light" else value[1]
    return value


# ---------------------------------------------------------------------------------------
# Focus da tastiera
# ---------------------------------------------------------------------------------------
def _scroll_into_view(widget):
    """Se il widget sta dentro un CTkScrollableFrame, scorre quanto basta per mostrarlo:
    senza questo il focus da tastiera finisce su controlli fuori schermo e l'utente lo perde."""
    sf = widget
    while sf is not None and not isinstance(sf, ctk.CTkScrollableFrame):
        sf = getattr(sf, "master", None)
    if sf is None:
        return
    try:
        canvas = sf._parent_canvas
        total_h = sf.winfo_height()
        view_h = canvas.winfo_height()
        if total_h <= view_h or total_h <= 0:
            return
        y = widget.winfo_rooty() - sf.winfo_rooty()
        h = widget.winfo_height()
        top = canvas.canvasy(0)
        margin = 24
        if y < top + margin:
            canvas.yview_moveto(max(0, y - margin) / total_h)
        elif y + h > top + view_h - margin:
            canvas.yview_moveto(max(0, y + h + margin - view_h) / total_h)
    except Exception:
        pass


def _draw_ring(widget, canvas):
    canvas.delete("ergo_focus_ring")
    w, h = canvas.winfo_width(), canvas.winfo_height()
    if w < 4 or h < 4:
        return
    r = 0
    try:
        r = widget._apply_widget_scaling(getattr(widget, "_corner_radius", 0) or 0)
    except Exception:
        pass
    r = max(2, min(r, w / 2 - 1, h / 2 - 1))
    x0, y0, x1, y1 = 1.5, 1.5, w - 1.5, h - 1.5
    # Rettangolo arrotondato come poligono "smooth": segue gli angoli del widget.
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    canvas.create_polygon(pts, smooth=True, fill="", outline=_color(FOCUS_RING),
                          width=3, tags="ergo_focus_ring")
    canvas.tag_raise("ergo_focus_ring")


def _make_keyboard_accessible(widget, activate, canvas=None):
    canvas = canvas if canvas is not None else getattr(widget, "_canvas", None)
    if canvas is None:
        return

    def can_focus(_name=None):
        try:
            if str(widget.cget("state")) == "disabled":
                return 0
            return 1 if widget.winfo_viewable() else 0
        except Exception:
            return 0

    def on_activate(_event=None):
        if can_focus():
            activate()
        return "break"

    def on_focus_in(_event=None):
        _draw_ring(widget, canvas)
        _scroll_into_view(widget)

    canvas.configure(takefocus=can_focus)
    for seq in ("<space>", "<Return>", "<KP_Enter>"):
        canvas.bind(seq, on_activate, add="+")
    canvas.bind("<FocusIn>", on_focus_in, add="+")
    canvas.bind("<FocusOut>", lambda e: canvas.delete("ergo_focus_ring"), add="+")
    # se il widget viene ridisegnato/ridimensionato mentre ha il focus, l'anello lo segue
    canvas.bind("<Configure>", lambda e: (canvas.focus_get() is canvas) and _draw_ring(widget, canvas), add="+")


def _patch(cls, activate_name):
    original_init = cls.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            _make_keyboard_accessible(self, getattr(self, activate_name))
        except Exception:
            pass

    cls.__init__ = __init__


def install():
    """Da chiamare una volta, prima di creare la finestra principale."""
    global _installed
    if _installed:
        return
    _installed = True
    _patch(ctk.CTkButton, "invoke")              # include i segmenti di CTkSegmentedButton
    _patch(ctk.CTkCheckBox, "toggle")
    _patch(ctk.CTkSwitch, "toggle")
    _patch(ctk.CTkRadioButton, "invoke")
    _patch(ctk.CTkOptionMenu, "_open_dropdown_menu")


# ---------------------------------------------------------------------------------------
# Tooltip (autodescrittivita': spiega controlli e scorciatoie senza aprire la guida)
# ---------------------------------------------------------------------------------------
class Tooltip:
    DELAY_MS = 550

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        canvas = getattr(widget, "_canvas", None)
        if canvas is not None:
            # anche chi naviga da tastiera vede la spiegazione
            canvas.bind("<FocusIn>", self._schedule, add="+")
            canvas.bind("<FocusOut>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        self._after = None
        if self._tip or not self.widget.winfo_viewable():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tkinter.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        light = ctk.get_appearance_mode() == "Light"
        tkinter.Label(
            tip, text=self.text, justify="left", wraplength=320,
            background="#1f2937" if light else "#f3f4f6",
            foreground="#ffffff" if light else "#111827",
            padx=8, pady=5, font="TkDefaultFont",
        ).pack()
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def tooltip(widget, text):
    return Tooltip(widget, text)


# ---------------------------------------------------------------------------------------
# Notifica non bloccante (feedback senza interrompere il lavoro con un popup modale)
# ---------------------------------------------------------------------------------------
def toast(root, text, kind="success", duration_ms=2600):
    colors = {"success": ("#065f46", "#065f46"), "info": ("#1e40af", "#1e3a8a"),
              "warning": ("#92400e", "#92400e"), "error": ("#991b1b", "#991b1b")}
    old = getattr(root, "_ergo_toast", None)
    if old is not None:
        try:
            old.destroy()
        except Exception:
            pass
    frame = ctk.CTkFrame(root, corner_radius=10, fg_color=colors.get(kind, colors["info"]))
    ctk.CTkLabel(frame, text=text, text_color="#ffffff", font=ctk.CTkFont(size=13, weight="bold")).pack(padx=18, pady=10)
    frame.place(relx=0.5, rely=1.0, anchor="s", y=-24)
    frame.lift()
    root._ergo_toast = frame

    def _remove():
        try:
            frame.destroy()
        except Exception:
            pass
        if getattr(root, "_ergo_toast", None) is frame:
            root._ergo_toast = None

    root.after(duration_ms, _remove)


# ---------------------------------------------------------------------------------------
# Dialog modali: Esc = annulla, Invio = conferma (conformita' alle aspettative)
# ---------------------------------------------------------------------------------------
def bind_dialog_keys(dialog, on_ok=None, on_cancel=None):
    if on_cancel is not None:
        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    if on_ok is not None:
        dialog.bind("<KP_Enter>", lambda e: on_ok())


# ---------------------------------------------------------------------------------------
# Guida rapida (F1): scorciatoie + cosa fa ogni sezione (apprendibilita')
# ---------------------------------------------------------------------------------------
HELP_SECTIONS = [
    ("Organizer", "Analizza una cartella con l'AI, propone una nuova struttura e la mostra in anteprima. "
                  "Nulla viene spostato finche' non confermi; prima di applicare viene creato un backup ZIP."),
    ("Auto Tag", "Raggruppa foto e video in album, con nomi proposti dall'AI che puoi modificare prima di crearli."),
    ("Hash Check", "Calcola l'impronta dei file per trovare duplicati esatti o verificare che una copia sia identica."),
    ("Offload", "Copia una scheda/SSD su uno o piu' dischi verificando ogni file con checksum, e genera un report."),
    ("Sincronizza Dischi", "Confronta due dischi e mostra cosa manca o e' diverso. Nessuna modifica viene applicata "
                           "senza la tua conferma finale."),
    ("Selezione Foto", "Trova raffiche, quasi-doppioni e foto mosse e propone di tenere la migliore. Le scartate vengono "
                       "spostate in una cartella a parte (mai cancellate) e lo spostamento si puo' annullare."),
    ("Persone", "Le persone che Datarium riconosce: rinominale, uniscile o eliminale. I volti sconosciuti vengono "
                "raggruppati per somiglianza, cosi' si nominano tutti insieme. I dati restano solo su questo computer."),
]


def show_help(root, shortcuts):
    existing = getattr(root, "_ergo_help", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return
    win = ctk.CTkToplevel(root)
    root._ergo_help = win
    win.title("Guida rapida e scorciatoie")
    win.geometry("620x560")
    win.transient(root)
    body = ctk.CTkScrollableFrame(win, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=16, pady=(16, 0))

    ctk.CTkLabel(body, text="Scorciatoie da tastiera", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(0, 8))
    grid = ctk.CTkFrame(body, fg_color="transparent")
    grid.pack(fill="x")
    for i, (keys, desc) in enumerate(shortcuts):
        ctk.CTkLabel(grid, text=keys, font=ctk.CTkFont(family="Consolas", size=13, weight="bold")).grid(row=i, column=0, sticky="w", padx=(0, 18), pady=2)
        ctk.CTkLabel(grid, text=desc, anchor="w", justify="left").grid(row=i, column=1, sticky="w", pady=2)

    ctk.CTkLabel(body, text="Cosa fa ogni sezione", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(18, 8))
    for title, desc in HELP_SECTIONS:
        ctk.CTkLabel(body, text=title, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(body, text=desc, text_color=MUTED, wraplength=540, justify="left").pack(anchor="w", pady=(0, 10))

    btn = ctk.CTkButton(win, text="Chiudi", width=120, command=win.destroy)
    btn.pack(pady=14)
    bind_dialog_keys(win, on_ok=win.destroy, on_cancel=win.destroy)
    win.after(150, lambda: (win.lift(), win.focus_force()))
