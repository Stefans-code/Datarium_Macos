"""
disk_benchmark.py — Test reale di velocità disco per Datarium.

Nato per rispondere alla domanda di un tester: "Datarium è lento per via del
software o per via dell'hardware (3 HDD esterni dietro un hub/adattatore che
fa da collo di bottiglia)?"

Il test copia i file di una cartella sorgente (i dati veri del tester, es.
~20 GB su un HDD) verso una cartella di destinazione (idealmente un SSD) usando
letture/scritture a blocchi, esattamente come farebbe una fase di ingest/copia
di Datarium. Misura:
  - velocità di sola LETTURA dalla sorgente (isola il collo di bottiglia HDD/hub)
  - velocità di copia END-TO-END (lettura + scrittura)
così il tester può confrontare i MB/s ottenuti sull'HDD via hub con quelli su SSD
e capire se il problema è il software o i dischi.

Nessuna dipendenza esterna: solo stdlib.
"""
import os
import time
import shutil


CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB, allineato a un caso reale di copia file grossi


class BenchmarkCancelled(Exception):
    pass


def _iter_files(root, size_limit_bytes=None):
    """Elenca i file sotto root, fermandosi appena si supera size_limit_bytes (se dato)."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            yield path, size
            total += size
            if size_limit_bytes is not None and total >= size_limit_bytes:
                return


def run_read_benchmark(source_dir, size_limit_gb=20, progress_callback=None, cancel_event=None):
    """
    Legge (senza scrivere nulla) fino a size_limit_gb di dati da source_dir.
    Isola la velocità di LETTURA pura del disco/hub sorgente.

    progress_callback(bytes_done, bytes_total_stimati) opzionale.
    cancel_event: oggetto con .is_set() opzionale, per annullare da un'altra UI thread.

    Ritorna dict: bytes_read, elapsed_sec, mbps, files_read.
    """
    size_limit_bytes = int(size_limit_gb * 1024 ** 3) if size_limit_gb else None
    files = list(_iter_files(source_dir, size_limit_bytes))
    total_estimate = sum(sz for _p, sz in files) or 1

    bytes_read = 0
    files_read = 0
    start = time.perf_counter()
    for path, _size in files:
        if cancel_event is not None and cancel_event.is_set():
            raise BenchmarkCancelled()
        try:
            with open(path, "rb") as f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise BenchmarkCancelled()
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    if progress_callback:
                        progress_callback(bytes_read, total_estimate)
        except OSError:
            continue
        files_read += 1

    elapsed = max(time.perf_counter() - start, 1e-6)
    return {
        "bytes_read": bytes_read,
        "elapsed_sec": elapsed,
        "mbps": (bytes_read / (1024 ** 2)) / elapsed,
        "files_read": files_read,
    }


def run_copy_benchmark(source_dir, dest_dir, size_limit_gb=20, progress_callback=None, cancel_event=None,
                        cleanup_after=True):
    """
    Copia fino a size_limit_gb di dati da source_dir a una sottocartella temporanea
    dentro dest_dir, misurando la velocità END-TO-END (lettura + scrittura), come farebbe
    una copia/ingest reale. Ripulisce i file copiati alla fine se cleanup_after=True.

    progress_callback(bytes_done, bytes_total_stimati) opzionale.
    cancel_event: oggetto con .is_set() opzionale.

    Ritorna dict: bytes_copied, elapsed_sec, mbps, files_copied.
    """
    size_limit_bytes = int(size_limit_gb * 1024 ** 3) if size_limit_gb else None
    files = list(_iter_files(source_dir, size_limit_bytes))
    total_estimate = sum(sz for _p, sz in files) or 1

    stage_dir = os.path.join(dest_dir, ".datarium_benchmark_tmp")
    os.makedirs(stage_dir, exist_ok=True)

    bytes_copied = 0
    files_copied = 0
    start = time.perf_counter()
    try:
        for idx, (path, _size) in enumerate(files):
            if cancel_event is not None and cancel_event.is_set():
                raise BenchmarkCancelled()
            dest_path = os.path.join(stage_dir, f"bench_{idx}{os.path.splitext(path)[1]}")
            try:
                with open(path, "rb") as fsrc, open(dest_path, "wb") as fdst:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise BenchmarkCancelled()
                        chunk = fsrc.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        fdst.write(chunk)
                        bytes_copied += len(chunk)
                        if progress_callback:
                            progress_callback(bytes_copied, total_estimate)
            except OSError:
                continue
            files_copied += 1
    finally:
        if cleanup_after:
            shutil.rmtree(stage_dir, ignore_errors=True)

    elapsed = max(time.perf_counter() - start, 1e-6)
    return {
        "bytes_copied": bytes_copied,
        "elapsed_sec": elapsed,
        "mbps": (bytes_copied / (1024 ** 2)) / elapsed,
        "files_copied": files_copied,
    }


# Soglia indicativa sotto la quale conviene sospettare l'hardware (HDD esterni +
# hub/adattatore USB che fa da collo di bottiglia) piuttosto che il software.
# Un hub USB2 o un adattatore SATA->USB scadente con più dischi in parallelo
# spesso scende sotto i 20-30 MB/s anche se i dischi singolarmente farebbero 100+.
SLOW_HARDWARE_THRESHOLD_MBPS = 30


def verdict(mbps):
    """Riga sintetica da mostrare sotto il grafico (i numeri li dà già la barra)."""
    if mbps < SLOW_HARDWARE_THRESHOLD_MBPS:
        return "Sotto soglia: probabile collo di bottiglia hardware (hub/dischi), non software."
    return "Nella norma: se l'app è lenta lo stesso, il tempo va nell'elaborazione, non nella copia."
