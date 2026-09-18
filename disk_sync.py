"""
disk_sync.py — Confronto e sincronizzazione di due dischi/cartelle (A e B) per Datarium.

Logica pura, senza UI. Il confronto e' per percorso relativo:
  solo in A / solo in B / stesso percorso ma contenuto diverso / identici.
Il contenuto si verifica con l'hash solo quando serve: dimensioni diverse = diverso;
stessa dimensione e data (tolleranza 2 s, FAT/exFAT) = identico; stessa dimensione ma
data diversa = hash su entrambi i lati. Con deep=True hash di TUTTI i file.

Sincronizzazione (stile FreeFileSync): ogni riga ha un'AZIONE, deducibile dalla modalita'
e modificabile a mano. Nulla viene cancellato davvero: i file eliminati o sovrascritti
vengono spostati in <disco>/_Datarium_Sync_Cestino/<data-ora>/ e restano recuperabili.
"""
import fnmatch
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

TRASH_DIR = "_Datarium_Sync_Cestino"
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "$recycle.bin",
                 "system volume information", ".spotlight-v100", ".trashes",
                 ".fseventsd", ".temporaryitems", TRASH_DIR.lower()}
MTIME_TOLERANCE = 2.0  # secondi (granularita' FAT/exFAT)
CHUNK = 8 * 1024 * 1024
PART_SUFFIX = ".dsync-part"

ONLY_A, ONLY_B, DIFFERENT, IDENTICAL = "only_a", "only_b", "different", "identical"
A2B, B2A, SKIP, DEL_A, DEL_B = "a2b", "b2a", "skip", "del_a", "del_b"

MODES = {
    "Aggiorna A ▶ B (copia il nuovo, non elimina)": "update",
    "Bidirezionale (vince il file più recente)": "twoway",
    "Specchio A ▶ B (B diventa uguale ad A)": "mirror_ab",
    "Specchio B ▶ A (A diventa uguale a B)": "mirror_ba",
}


def _make_hasher():
    try:
        import xxhash
        return xxhash.xxh64()
    except ImportError:
        import hashlib
        return hashlib.sha256()


def hash_file(path, progress_cb=None):
    h = _make_hasher()
    buf = bytearray(CHUNK)
    view = memoryview(buf)
    with open(path, "rb", buffering=0) as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            h.update(view[:n])
            if progress_cb:
                progress_cb(n)
    return h.hexdigest()


def _excluded(rel, patterns):
    if not patterns:
        return False
    parts = rel.split("/")
    for pat in patterns:
        if fnmatch.fnmatch(rel.lower(), pat) or any(fnmatch.fnmatch(p.lower(), pat) for p in parts):
            return True
    return False


def parse_exclude(text):
    return [p.strip().lower() for p in (text or "").replace(";", ",").split(",") if p.strip()]


def scan_tree(root, exclude=None, cancel=None):
    """{percorso_relativo: (size, mtime)} con separatore normalizzato a '/'."""
    out = {}
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_NAMES]
        if cancel is not None and cancel():
            break
        for name in files:
            if name.lower() in IGNORED_NAMES or name.startswith("._") or name.endswith(PART_SUFFIX):
                continue
            p = os.path.join(cur, name)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if _excluded(rel, exclude):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[rel] = (st.st_size, st.st_mtime)
    return out


def compare(root_a, root_b, deep=False, exclude=None, status_cb=None, cancel=None):
    """Lista di dict ordinata per percorso: {rel, status, a, b, note} con a/b = (size, mtime)|None."""
    if status_cb:
        status_cb("Scansione disco A e disco B...")
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(scan_tree, root_a, exclude, cancel)
        fb = ex.submit(scan_tree, root_b, exclude, cancel)
        a, b = fa.result(), fb.result()

    rows, to_hash = [], []
    for rel in sorted(set(a) | set(b), key=str.lower):
        ia, ib = a.get(rel), b.get(rel)
        if ia and not ib:
            rows.append({"rel": rel, "status": ONLY_A, "a": ia, "b": None, "note": "manca in B"})
        elif ib and not ia:
            rows.append({"rel": rel, "status": ONLY_B, "a": None, "b": ib, "note": "manca in A"})
        elif ia[0] != ib[0]:
            rows.append({"rel": rel, "status": DIFFERENT, "a": ia, "b": ib, "note": "dimensione diversa"})
        elif not deep and abs(ia[1] - ib[1]) <= MTIME_TOLERANCE:
            rows.append({"rel": rel, "status": IDENTICAL, "a": ia, "b": ib, "note": ""})
        else:
            row = {"rel": rel, "status": IDENTICAL, "a": ia, "b": ib, "note": ""}
            rows.append(row)
            to_hash.append(row)

    if to_hash:
        total = len(to_hash)
        done = [0]

        # Un thread per disco: A e B si leggono in parallelo, ogni disco in sequenza.
        def _hash_side(side):
            root = root_a if side == "a" else root_b
            res = {}
            for row in to_hash:
                if cancel is not None and cancel():
                    break
                try:
                    res[row["rel"]] = hash_file(os.path.join(root, row["rel"].replace("/", os.sep)))
                except OSError as e:
                    res[row["rel"]] = f"Error: {e}"
                if side == "a":
                    done[0] += 1
                    if status_cb:
                        status_cb(f"Verifica contenuto {done[0]}/{total}: {row['rel']}")
            return res

        with ThreadPoolExecutor(max_workers=2) as ex:
            fha, fhb = ex.submit(_hash_side, "a"), ex.submit(_hash_side, "b")
            ha, hb = fha.result(), fhb.result()
        for row in to_hash:
            x, y = ha.get(row["rel"]), hb.get(row["rel"])
            bad = x is None or y is None or x.startswith("Error") or y.startswith("Error")
            if bad or x != y:
                row["status"] = DIFFERENT
                row["note"] = "non verificabile" if bad else "stessa dimensione, contenuto diverso"
    return rows


# ---------------------------------------------------------------- azioni

def allowed_actions(row, mode):
    """Azioni tra cui l'utente puo' scegliere per una riga (la prima e' quella di default)."""
    st = row["status"]
    mirror = mode in ("mirror_ab", "mirror_ba")
    if st == ONLY_A:
        acts = [A2B, SKIP] + ([DEL_A] if mirror else [])
    elif st == ONLY_B:
        acts = [B2A, SKIP] + ([DEL_B] if mirror else [])
    elif st == DIFFERENT:
        acts = [A2B, B2A, SKIP]
    else:
        acts = [SKIP]
    return acts


def default_action(row, mode):
    st = row["status"]
    if st == IDENTICAL:
        return SKIP
    if mode == "update":
        if st == ONLY_A:
            return A2B
        if st == ONLY_B:
            return SKIP
        return A2B if row["a"][1] > row["b"][1] + MTIME_TOLERANCE else SKIP
    if mode == "twoway":
        if st == ONLY_A:
            return A2B
        if st == ONLY_B:
            return B2A
        if row["a"][1] > row["b"][1] + MTIME_TOLERANCE:
            return A2B
        if row["b"][1] > row["a"][1] + MTIME_TOLERANCE:
            return B2A
        return SKIP  # stessa data ma contenuto diverso: conflitto, decide l'utente
    if mode == "mirror_ab":
        return {ONLY_A: A2B, ONLY_B: DEL_B, DIFFERENT: A2B}[st]
    if mode == "mirror_ba":
        return {ONLY_A: DEL_A, ONLY_B: B2A, DIFFERENT: B2A}[st]
    return SKIP


def summarize(rows):
    """Riepilogo delle azioni scelte (row['action'])."""
    s = {"a2b": 0, "b2a": 0, "del": 0, "overwrite": 0, "bytes": 0}
    for r in rows:
        act = r.get("action", SKIP)
        if act == A2B:
            s["a2b"] += 1
            s["bytes"] += r["a"][0]
            s["overwrite"] += r["status"] == DIFFERENT
        elif act == B2A:
            s["b2a"] += 1
            s["bytes"] += r["b"][0]
            s["overwrite"] += r["status"] == DIFFERENT
        elif act in (DEL_A, DEL_B):
            s["del"] += 1
    return s


def move_to_trash(root, rel, stamp):
    """Sposta root/rel in root/_Datarium_Sync_Cestino/<stamp>/rel (recuperabile)."""
    src = os.path.join(root, rel.replace("/", os.sep))
    dst = os.path.join(root, TRASH_DIR, stamp, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return dst


def copy_verified(src, dst, verify=True, progress_cb=None):
    """Copia src -> dst su file temporaneo, poi rinomina. Con verify rilegge la
    destinazione e confronta l'hash. Mantiene la data di modifica. Ritorna (ok, errore)."""
    tmp = dst + PART_SUFFIX
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        h = _make_hasher()
        buf = bytearray(CHUNK)
        view = memoryview(buf)
        with open(src, "rb", buffering=0) as fi, open(tmp, "wb", buffering=0) as fo:
            while True:
                n = fi.readinto(buf)
                if not n:
                    break
                h.update(view[:n])
                fo.write(view[:n])
                if progress_cb:
                    progress_cb(n)
            fo.flush()
            try:
                os.fsync(fo.fileno())
            except OSError:
                pass
        if verify and hash_file(tmp) != h.hexdigest():
            os.remove(tmp)
            return False, "verifica hash fallita"
        st = os.stat(src)
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.replace(tmp, dst)
        return True, ""
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False, str(e)


def execute(rows, root_a, root_b, verify=True, progress_cb=None, cancel=None):
    """Esegue le azioni scelte. progress_cb(indice, totale, rel, byte_copiati_nel_blocco).
    Ritorna la lista degli errori [(rel, messaggio)]."""
    jobs = [r for r in rows if r.get("action", SKIP) != SKIP]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    failed = []
    for i, r in enumerate(jobs):
        if cancel is not None and cancel():
            break
        act, rel = r["action"], r["rel"]
        native = rel.replace("/", os.sep)
        try:
            if act in (A2B, B2A):
                src_root, dst_root = (root_a, root_b) if act == A2B else (root_b, root_a)
                src, dst = os.path.join(src_root, native), os.path.join(dst_root, native)
                trashed = move_to_trash(dst_root, rel, stamp) if os.path.exists(dst) else None  # vecchia versione -> cestino
                ok, err = copy_verified(src, dst, verify=verify,
                                        progress_cb=(lambda n, i=i, rel=rel: progress_cb(i, len(jobs), rel, n)) if progress_cb else None)
                if not ok:
                    failed.append((rel, err))
                    if trashed and not os.path.exists(dst):  # copia fallita: rimette a posto la vecchia versione
                        try:
                            shutil.move(trashed, dst)
                        except OSError:
                            pass
            elif act == DEL_A:
                move_to_trash(root_a, rel, stamp)
            elif act == DEL_B:
                move_to_trash(root_b, rel, stamp)
        except Exception as e:
            failed.append((rel, str(e)))
        if progress_cb and act in (DEL_A, DEL_B):
            progress_cb(i, len(jobs), rel, 0)
    return failed


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_date(ts):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
