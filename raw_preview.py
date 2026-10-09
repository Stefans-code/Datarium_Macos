"""
Anteprima dei file RAW senza librerie RAW: quasi tutti i formati (CR2, CR3, NEF, ARW, DNG,
RAF, ORF, RW2, PEF, SRW...) incorporano uno o piu' JPEG (miniatura EXIF + anteprima grande
generata dalla fotocamera). Si cercano i marker di inizio JPEG nel file e si tiene quello
decodificato piu' grande.

E' la stessa anteprima che mostrano Lightroom/Bridge prima di sviluppare il RAW: per
valutare nitidezza, somiglianza e volti e' piu' che sufficiente, e non serve compilare
nessuna dipendenza nativa in piu' (importante per la CI Mac Intel).
"""
import os

import cv2
import numpy as np

RAW_EXTS = {'.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.sr2', '.dng', '.raf', '.rw2',
            '.raw', '.orf', '.pef', '.srw', '.rwl', '.3fr', '.fff', '.iiq', '.erf', '.mef', '.mos', '.x3f'}
_SOI = b"\xff\xd8\xff"
_MAX_CANDIDATES = 16


def is_raw(path):
    return os.path.splitext(path)[1].lower() in RAW_EXTS


def extract_bgr(path):
    """Anteprima JPEG piu' grande incorporata nel RAW, come immagine BGR (o None)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    buf = np.frombuffer(data, dtype=np.uint8)
    best, best_area = None, 0
    start, tries = 0, 0
    while tries < _MAX_CANDIDATES:
        i = data.find(_SOI, start)
        if i < 0:
            break
        start = i + 3
        tries += 1
        # i dati RAW veri e propri a volte iniziano con lo stesso marker (JPEG lossless dei
        # Canon): imdecode li rifiuta e si passa al candidato successivo
        try:
            img = cv2.imdecode(buf[i:], cv2.IMREAD_COLOR)
        except cv2.error:
            img = None
        if img is None:
            continue
        area = img.shape[0] * img.shape[1]
        if area > best_area:
            best, best_area = img, area
            if min(img.shape[:2]) >= 1000:
                break  # anteprima grande trovata: inutile decodificare il resto
    return best  # anche solo la miniatura EXIF e' meglio di niente


def extract_pil(path):
    """Come extract_bgr ma come immagine PIL RGB (per le miniature dell'interfaccia)."""
    img = extract_bgr(path)
    if img is None:
        return None
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
