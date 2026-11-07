"""
Identita' visiva Nexflamma applicata a Datarium.

Datarium tiene la sua icona; colori, tono e firma ("un prodotto Nexflamma") sono quelli della
casa madre, uguali per tutti i prodotti. Fonte unica: brand/BRAND_NEXFLAMMA.md (copia in
Desktop\\Nexflamma\\brand). Se cambi un colore qui, cambialo anche in assets/material_theme.json
e nelle linee guida.

Ogni coppia e' (tema chiaro, tema scuro). Contrasti verificati WCAG 2.1 AA (testo >= 4.5:1,
elementi grafici >= 3:1) contro gli sfondi APP_BG / SURFACE qui sotto.
"""
import customtkinter as ctk

# --- Superfici --------------------------------------------------------------------------
APP_BG = ("#f6f4f0", "#05070a")        # carta calda / inchiostro (sito: #040508)
SURFACE = ("#ffffff", "#0d1017")       # card e pannelli
SURFACE_RAISED = ("#faf8f5", "#131722")
BORDER = ("#e7e2d8", "#1f2533")
TEXT = ("#14110f", "#f8fafc")          # 17:1 / 19:1

# --- Fiamma (colore primario) -------------------------------------------------------------
# Sul tema scuro l'arancio del sito (#ff5e1e) con testo bianco fa 3.1:1 (non passa): come sul
# sito, il testo sopra l'arancio e' quasi nero (6.5:1). Sul tema chiaro serve un arancio piu'
# scuro per staccare dal bianco, con testo bianco (5.2:1).
ACCENT = ("#c2410c", "#ff5e1e")
ACCENT_HOVER = ("#9a3412", "#ff7a45")
ON_ACCENT = ("#ffffff", "#0a0a0a")
ACCENT_SOFT = ("#ffedd5", "#2a1408")   # sfondo tonale (voce di menu attiva, selezioni)
ACCENT_SOFT_HOVER = ("#fed7aa", "#3a1c0c")
ACCENT_TEXT = ("#9a3412", "#ff8a57")   # testo arancio leggibile: 6.4:1 / 7.5:1 sul tonale

# --- Cristallo (colore secondario: il ciano del logo) ----------------------------------------
CRYSTAL = ("#0e7490", "#00f2fe")       # info, link, anello di focus: 5.4:1 / 14:1

# --- Azioni distruttive -----------------------------------------------------------------------
DANGER = ("#b91c1c", "#dc2626")        # testo bianco 6.5:1 / 4.8:1
DANGER_HOVER = ("#991b1b", "#b91c1c")

FIRMA = "un prodotto Nexflamma"

_installed = False


def install():
    """Da chiamare una volta, prima di creare widget (come ergonomics.install).

    I pulsanti "trasparenti" (Indietro, Annulla, Salta...) ereditavano dal tema il colore del
    testo pensato per i pulsanti pieni: con il testo scuro sull'arancio del tema scuro sarebbero
    diventati illeggibili, e gia' prima sul tema chiaro erano bianco su bianco. Qui il testo dei
    pulsanti senza riempimento prende il colore del testo normale, salvo indicazione esplicita."""
    global _installed
    if _installed:
        return
    _installed = True
    original_init = ctk.CTkButton.__init__

    def patched_init(self, *args, **kwargs):
        if kwargs.get("fg_color") == "transparent" and "text_color" not in kwargs:
            kwargs["text_color"] = TEXT
        original_init(self, *args, **kwargs)

    ctk.CTkButton.__init__ = patched_init
