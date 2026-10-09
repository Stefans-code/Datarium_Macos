"""
Selezione Foto (culling assistito), ispirata al "Assisted culling (focus, bursts)" di
Lightroom/LightCraft, ma con la filosofia di Datarium: niente viene mai cancellato.

- Nitidezza: varianza del Laplaciano su una copia ridotta a larghezza fissa (cosi' il
  valore e' confrontabile fra foto di risoluzioni diverse).
- Somiglianza: dHash a 64 bit (distanza di Hamming fra le impronte).
- Raffiche: scatti consecutivi a pochi secondi l'uno dall'altro E visivamente simili.
- Quasi-doppioni: impronta quasi identica anche se scattati in momenti diversi
  (es. la stessa foto esportata due volte, o ricevuta da WhatsApp e dalla fotocamera).

Le foto "da scartare" vengono SPOSTATE in una sottocartella, con un registro che
permette di annullare l'operazione (vedi move_journal.py).
"""
import os
import datetime

import cv2
import numpy as np

import raw_preview

# RAW compresi: si analizza l'anteprima JPEG che la fotocamera incorpora nel file
CULL_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff', '.heic', '.heif'} | raw_preview.RAW_EXTS
REJECT_DIR_NAME = "_Scartate_Datarium"

SHARP_WIDTH = 800        # larghezza a cui si misura la nitidezza
BURST_GAP_S = 3.0        # scatti piu' vicini di cosi' sono candidati raffica
BURST_HAMMING = 18       # ...se anche l'impronta e' abbastanza simile
DUP_HAMMING = 6          # impronta quasi identica = quasi-doppione a prescindere dall'orario


def _load_gray(path):
    """Immagine in scala di grigi, o None. cv2.imread non legge percorsi non ASCII su
    Windows ne' HEIC: si passa da imdecode e, in seconda battuta, da PIL."""
    if raw_preview.is_raw(path):
        bgr = raw_preview.extract_bgr(path)
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr is not None else None
    img = None
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    except Exception:
        img = None
    if img is None:
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((1600, 1600))
                img = np.asarray(im.convert("L"))
        except Exception:
            return None
    return img


def sharpness(gray):
    h, w = gray.shape[:2]
    if w > SHARP_WIDTH:
        gray = cv2.resize(gray, (SHARP_WIDTH, max(1, int(h * SHARP_WIDTH / w))), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dhash(gray):
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


def hamming(a, b):
    return bin(a ^ b).count("1")


def capture_time(path):
    """Data di scatto EXIF (DateTimeOriginal) come timestamp, altrimenti data di modifica."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        pass
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def list_photos(folder):
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != REJECT_DIR_NAME and not d.startswith("Backup_Datarium_")]
        for f in files:
            if os.path.splitext(f)[1].lower() in CULL_EXTS and not f.startswith("._"):
                out.append(os.path.join(root, f))
    return sorted(out)


def analyze(folder, progress_cb=None, should_stop=None):
    """Ritorna (items, unreadable). items: [{path, sharp, hash, ts}]."""
    paths = list_photos(folder)
    items, unreadable = [], []
    for i, p in enumerate(paths):
        if should_stop and should_stop():
            break
        if progress_cb:
            progress_cb(i, len(paths), os.path.basename(p))
        gray = _load_gray(p)
        if gray is None or gray.size == 0:
            unreadable.append(p)
            continue
        items.append({"path": p, "sharp": sharpness(gray), "hash": dhash(gray), "ts": capture_time(p)})
    if progress_cb:
        progress_cb(len(paths), len(paths), "")
    return items, unreadable


def group_similar(items):
    """Gruppi (liste di item, >= 2 membri) di raffiche e quasi-doppioni.
    In ogni gruppo il primo elemento e' il migliore (il piu' nitido)."""
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    # raffiche: confronto solo fra vicini nel tempo (O(n) invece di O(n^2))
    order = sorted(range(n), key=lambda k: (items[k]["ts"] is None, items[k]["ts"] or 0))
    for a, b in zip(order, order[1:]):
        ta, tb = items[a]["ts"], items[b]["ts"]
        if ta is not None and tb is not None and abs(tb - ta) <= BURST_GAP_S \
                and hamming(items[a]["hash"], items[b]["hash"]) <= BURST_HAMMING:
            union(a, b)
    # quasi-doppioni: bucket sui 16 bit alti per non confrontare tutto con tutto
    # (due impronte a distanza <= 6 differiscono in quei bit raramente; per cartelle
    # piccole si confronta comunque tutto)
    if n <= 3000:
        for i in range(n):
            for j in range(i + 1, n):
                if hamming(items[i]["hash"], items[j]["hash"]) <= DUP_HAMMING:
                    union(i, j)
    else:
        buckets = {}
        for i, it in enumerate(items):
            buckets.setdefault(it["hash"] >> 48, []).append(i)
        for idxs in buckets.values():
            for x in range(len(idxs)):
                for y in range(x + 1, len(idxs)):
                    if hamming(items[idxs[x]]["hash"], items[idxs[y]]["hash"]) <= DUP_HAMMING:
                        union(idxs[x], idxs[y])

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i])
    out = [sorted(g, key=lambda it: -it["sharp"]) for g in groups.values() if len(g) >= 2]
    out.sort(key=lambda g: min((it["ts"] or 0) for it in g))
    return out


def find_blurry(items, exclude_paths=()):
    """Foto probabilmente mosse/sfocate: molto meno nitide della mediana della cartella
    (soglia relativa: un set di ritratti a sfondo sfocato ha valori bassi ovunque) oppure
    sotto una soglia assoluta minima. Escluse quelle gia' presenti in un gruppo."""
    if not items:
        return []
    med = float(np.median([it["sharp"] for it in items]))
    exclude = set(exclude_paths)
    blurry = [it for it in items
              if it["path"] not in exclude
              and (it["sharp"] < 20 or (it["sharp"] < 0.35 * med and it["sharp"] < 150))]
    return sorted(blurry, key=lambda it: it["sharp"])


def sharpness_label(value, median):
    if median <= 0:
        return "nitidezza n/d"
    ratio = value / median
    if ratio >= 1.2:
        return "molto nitida"
    if ratio >= 0.7:
        return "nitida"
    if ratio >= 0.35:
        return "poco nitida"
    return "mossa/sfocata"
