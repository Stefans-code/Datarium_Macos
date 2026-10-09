"""
Registro degli spostamenti (Organizer, Selezione Foto) per poterli ANNULLARE.

Ogni operazione che sposta file del cliente scrive un registro JSON con le coppie
(origine, destinazione), i file creati da Datarium (es. .xmp) e le cartelle create.
"Annulla" rimette tutto com'era, al contrario e senza mai sovrascrivere un file che
nel frattempo e' ricomparso nella posizione originale.

Gestisce anche i file "compagni" (sidecar) di una foto/video: lo .xmp di Lightroom,
lo .THM delle fotocamere, l'.AAE di iPhone, l'.LRV di GoPro. Senza questo, riordinando
una cartella il RAW finiva in un posto e le sue regolazioni Lightroom in un altro.
"""
import os
import json
import shutil
import datetime
import uuid

SIDECAR_EXTS = ('.xmp', '.thm', '.aae', '.lrv')
MAX_JOURNALS = 15


def find_sidecars(path):
    """File compagni nella stessa cartella: 'IMG_1.xmp' (Lightroom/Bridge) e 'IMG_1.CR2.xmp'
    (darktable/digiKam), confronto senza distinzione maiuscole/minuscole."""
    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0].lower()
    full = name.lower()
    out = []
    try:
        for f in os.listdir(folder or "."):
            fl = f.lower()
            if fl == full:
                continue
            base, ext = os.path.splitext(fl)
            if ext in SIDECAR_EXTS and (base == stem or base == full):
                out.append(os.path.join(folder, f))
    except OSError:
        pass
    return out


def is_sidecar_of_something(path, all_paths_lower):
    """True se 'path' e' un sidecar di un altro file presente nell'elenco (va spostato con lui,
    non trattato come documento a se')."""
    folder, name = os.path.split(path)
    base, ext = os.path.splitext(name)
    if ext.lower() not in SIDECAR_EXTS:
        return False
    base_l = os.path.join(folder, base).lower()
    if base_l in all_paths_lower:              # IMG_1.CR2.xmp -> IMG_1.CR2
        return True
    prefix = base_l + "."
    return any(p.startswith(prefix) and os.path.splitext(p)[1] not in SIDECAR_EXTS
               for p in all_paths_lower)       # IMG_1.xmp -> IMG_1.<qualunque>


def unique_target(target):
    base, ext = os.path.splitext(target)
    counter = 1
    while os.path.exists(target):
        target = f"{base}_{counter}{ext}"
        counter += 1
    return target


class MoveJournal:
    def __init__(self, journal_dir, label, root=""):
        self.journal_dir = journal_dir
        os.makedirs(journal_dir, exist_ok=True)
        self.data = {
            "id": datetime.datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6],
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "label": label,
            "root": root,
            "moves": [],
            "created_files": [],
            "created_dirs": [],
            "undone": False,
        }

    @property
    def path(self):
        return os.path.join(self.journal_dir, self.data["id"] + ".json")

    def _ensure_dir(self, d):
        missing = []
        cur = os.path.abspath(d)
        while cur and not os.path.exists(cur):
            missing.append(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        os.makedirs(d, exist_ok=True)
        self.data["created_dirs"].extend(reversed(missing))

    def move(self, src, target, with_sidecars=True):
        """Sposta src in target (nome reso unico se occupato) insieme ai suoi sidecar.
        Ritorna il percorso finale. Il registro viene salvato dopo OGNI file: se l'app o
        il PC si fermano a meta', l'annullamento copre comunque quanto gia' fatto."""
        sidecars = find_sidecars(src) if with_sidecars else []
        self._ensure_dir(os.path.dirname(target))
        if os.path.abspath(src) != os.path.abspath(target):
            target = unique_target(target)
        shutil.move(src, target)
        self.data["moves"].append([src, target])
        t_folder, t_name = os.path.split(target)
        t_stem = os.path.splitext(t_name)[0]
        for sc in sidecars:
            sc_name = os.path.basename(sc)
            sc_ext = os.path.splitext(sc_name)[1]
            # 'IMG_1.CR2.xmp' segue il nome completo, 'IMG_1.xmp' segue la radice
            if os.path.splitext(os.path.splitext(sc_name)[0])[1]:
                new_name = t_name + sc_ext
            else:
                new_name = t_stem + sc_ext
            sc_target = unique_target(os.path.join(t_folder, new_name))
            try:
                shutil.move(sc, sc_target)
                self.data["moves"].append([sc, sc_target])
            except OSError as e:
                print(f"[Journal] Sidecar non spostato {sc}: {e}")
        self.save()
        return target

    def record_created_file(self, path):
        self.data["created_files"].append(path)
        self.save()

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
        except OSError as e:
            print(f"[Journal] Registro non salvato: {e}")
        _prune(self.journal_dir)


def _prune(journal_dir):
    try:
        files = sorted(f for f in os.listdir(journal_dir) if f.endswith(".json"))
        for f in files[:-MAX_JOURNALS]:
            os.remove(os.path.join(journal_dir, f))
    except OSError:
        pass


def latest(journal_dir, label_prefix=None):
    """Ultimo registro non ancora annullato (opzionalmente filtrato per tipo di operazione)."""
    try:
        files = sorted((f for f in os.listdir(journal_dir) if f.endswith(".json")), reverse=True)
    except OSError:
        return None
    for f in files:
        try:
            with open(os.path.join(journal_dir, f), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if data.get("undone") or not data.get("moves"):
            continue
        if label_prefix and not str(data.get("label", "")).startswith(label_prefix):
            continue
        data["_file"] = os.path.join(journal_dir, f)
        return data
    return None


def undo(data, progress_cb=None):
    """Annulla un registro. Ritorna (ripristinati, [(file, motivo), ...] non ripristinati)."""
    restored, failed = 0, []
    moves = list(reversed(data.get("moves", [])))
    for i, (src, dst) in enumerate(moves):
        if progress_cb:
            progress_cb(i, len(moves))
        if not os.path.exists(dst):
            failed.append((dst, "non piu' presente nella destinazione"))
            continue
        if os.path.exists(src):
            failed.append((src, "nella posizione originale c'e' gia' un file con lo stesso nome"))
            continue
        try:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(dst, src)
            restored += 1
        except OSError as e:
            failed.append((dst, str(e)))
    for f in data.get("created_files", []):
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass
    # cartelle create da Datarium: rimosse solo se rimaste vuote, dalla piu' profonda
    for d in sorted(set(data.get("created_dirs", [])), key=len, reverse=True):
        try:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    data["undone"] = True
    jf = data.pop("_file", None)
    if jf:
        try:
            with open(jf, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass
    return restored, failed
