import os
import sys
import json
import platform
import threading
import urllib.request
import uuid
import cv2
import numpy as np

import raw_preview

# Modelli dedicati (NON LLM) per i volti, caricati nativamente da OpenCV (opencv-contrib):
#   - YuNet  -> rilevamento volti
#   - SFace  -> riconoscimento volti (embedding 128-dim, confronto coseno)
# Vengono scaricati una sola volta dall'OpenCV Zoo nella cartella 'faces' (NON in 'models').
YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/" + YUNET_FILE
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/" + SFACE_FILE

# Soglia coseno consigliata da OpenCV: score >= 0.363 => stessa persona
COSINE_THRESHOLD = 0.363
MAX_SAMPLES_PER_PERSON = 10


class FaceMemoryManager:
    """Riconoscimento volti basato su YuNet + SFace (OpenCV), senza alcun LLM.
    Mantiene l'interfaccia usata da main.py: detect_faces / crop_face / predict_face / add_face."""

    def __init__(self, base_models_dir=None):
        # base_models_dir mantenuto per compatibilita' di firma (non piu' usato per i volti)
        self.faces_dir = self._get_faces_directory()
        os.makedirs(self.faces_dir, exist_ok=True)

        self.metadata_path = os.path.join(self.faces_dir, "faces_sface.json")
        # L'analisi gira su thread in background mentre la pagina Persone legge/modifica
        self._lock = threading.RLock()
        self.metadata = self.load_metadata()
        self.pending = self._load_pending()

        self.detector = None
        self.recognizer = None
        self._haar = None
        self._models_ready = False  # caricamento/scaricamento lazy (non blocca l'avvio)

    # ------------------------------------------------------------------ paths
    def _get_faces_directory(self):
        """Cartella persistente e scrivibile per dati e modelli dei volti."""
        system = platform.system()
        try:
            if system == "Windows":
                base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
                path = os.path.join(base, "Datarium", "faces")
            elif system == "Darwin":
                path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium", "faces")
            else:
                path = os.path.join(os.path.expanduser("~"), ".datarium", "faces")
            os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            print(f"[FaceMemory] Errore risoluzione cartella volti: {e}")
            fallback = os.path.join(os.path.expanduser("~"), ".datarium_faces")
            os.makedirs(fallback, exist_ok=True)
            return fallback

    # ------------------------------------------------------------- metadata
    def load_metadata(self):
        if os.path.exists(self.metadata_path):
            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "people" in data:
                        return data
            except Exception as e:
                print(f"[FaceMemory] Errore lettura metadati: {e}")
        # people: { nome: [ [128 float], ... ] }
        return {"people": {}}

    def save_metadata(self):
        try:
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False)
        except Exception as e:
            print(f"[FaceMemory] Errore scrittura metadati: {e}")

    # --------------------------------------------------------- model loading
    def _download(self, url, dest):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
                out.write(resp.read())
            return os.path.exists(dest) and os.path.getsize(dest) > 0
        except Exception as e:
            print(f"[FaceMemory] Download fallito {os.path.basename(dest)}: {e}")
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            return False

    def _ensure_models(self):
        """Carica YuNet+SFace al primo utilizzo, scaricandoli se assenti.
        Se non disponibili, ripiega su Haar (solo rilevamento) + identificazione manuale."""
        if self._models_ready:
            return
        self._models_ready = True

        yunet_path = os.path.join(self.faces_dir, YUNET_FILE)
        sface_path = os.path.join(self.faces_dir, SFACE_FILE)

        try:
            if not os.path.exists(yunet_path):
                self._download(YUNET_URL, yunet_path)
            if not os.path.exists(sface_path):
                self._download(SFACE_URL, sface_path)

            if os.path.exists(yunet_path):
                self.detector = cv2.FaceDetectorYN.create(yunet_path, "", (320, 320), 0.7, 0.3, 5000)
            if os.path.exists(sface_path):
                self.recognizer = cv2.FaceRecognizerSF.create(sface_path, "")
        except Exception as e:
            print(f"[FaceMemory] Errore inizializzazione modelli volti: {e}")

        # Fallback per il solo rilevamento se YuNet non e' disponibile (es. offline al primo avvio)
        if self.detector is None:
            try:
                cascade = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
                if os.path.exists(cascade):
                    self._haar = cv2.CascadeClassifier(cascade)
            except Exception as e:
                print(f"[FaceMemory] Fallback Haar non disponibile: {e}")

    # --------------------------------------------------------------- detection
    def detect_faces(self, media_path):
        """Rileva i volti in un'immagine (o nel primo frame utile di un video).
        Ritorna (lista_volti, immagine_bgr). Ogni 'volto' e' una riga YuNet (box+landmark)
        oppure un box [x,y,w,h] in modalita' fallback Haar."""
        self._ensure_models()
        try:
            img = None
            if raw_preview.is_raw(media_path):
                img = raw_preview.extract_bgr(media_path)
            else:
                # imdecode invece di imread: imread fallisce sui percorsi non ASCII su Windows
                try:
                    img = cv2.imdecode(np.fromfile(media_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                except Exception:
                    img = None
            if img is None:
                cap = cv2.VideoCapture(media_path)
                if cap.isOpened():
                    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    if total > 0:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, min(30, total // 4))
                    ok, frame = cap.read()
                    if ok:
                        img = frame
                cap.release()
            if img is None:
                return [], None

            if self.detector is not None:
                h, w = img.shape[:2]
                self.detector.setInputSize((w, h))
                _, faces = self.detector.detect(img)
                return (list(faces) if faces is not None else []), img

            if self._haar is not None:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                boxes = self._haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))
                return list(boxes), img

            return [], img
        except Exception as e:
            print(f"[FaceMemory] Errore rilevamento volti: {e}")
            return [], None

    def _safe_box_crop(self, img, x, y, w, h):
        h_img, w_img = img.shape[:2]
        x1 = max(0, int(x)); y1 = max(0, int(y))
        x2 = min(w_img, int(x + w)); y2 = min(h_img, int(y + h))
        if x2 <= x1 or y2 <= y1:
            return img
        return img[y1:y2, x1:x2]

    def crop_face(self, img, face):
        """Ritorna (volto_allineato_per_SFace, ritaglio_BGR_per_anteprima).
        Compatibile con la firma usata da main.py."""
        # YuNet row: [x, y, w, h, 5x landmark(10), score] -> almeno 15 valori
        try:
            face_arr = np.asarray(face, dtype=np.float32).flatten()
        except Exception:
            face_arr = None

        if self.recognizer is not None and face_arr is not None and face_arr.shape[0] >= 15:
            try:
                aligned = self.recognizer.alignCrop(img, face_arr)
                x, y, w, h = face_arr[0], face_arr[1], face_arr[2], face_arr[3]
                bgr = self._safe_box_crop(img, x, y, w, h)
                return aligned, bgr
            except Exception as e:
                print(f"[FaceMemory] alignCrop fallito, uso ritaglio semplice: {e}")

        # Fallback: ritaglio del box (Haar o YuNet senza recognizer)
        if face_arr is not None and face_arr.shape[0] >= 4:
            x, y, w, h = face_arr[0], face_arr[1], face_arr[2], face_arr[3]
        else:
            x, y, w, h = 0, 0, img.shape[1], img.shape[0]
        bgr = self._safe_box_crop(img, x, y, w, h)
        return bgr, bgr

    # ------------------------------------------------------------- recognition
    def _feature(self, aligned_face):
        feat = self.recognizer.feature(aligned_face)
        return np.asarray(feat, dtype=np.float32).reshape(1, -1)

    def predict_face(self, aligned_face, threshold=COSINE_THRESHOLD):
        """Confronta il volto con quelli in memoria (coseno SFace).
        Ritorna (nome, score) se sopra soglia, altrimenti (None, miglior_score)."""
        if self.recognizer is None:
            return None, 0.0
        try:
            feat = self._feature(aligned_face)
            best_name, best_score = None, -1.0
            with self._lock:
                people = {n: list(f) for n, f in self.metadata.get("people", {}).items()}
            for name, feats in people.items():
                for f in feats:
                    ref = np.asarray(f, dtype=np.float32).reshape(1, -1)
                    score = self.recognizer.match(feat, ref, cv2.FaceRecognizerSF_FR_COSINE)
                    if score > best_score:
                        best_score, best_name = score, name
            if best_name is not None and best_score >= threshold:
                return best_name, float(best_score)
            return None, float(max(best_score, 0.0))
        except Exception as e:
            print(f"[FaceMemory] Errore predizione: {e}")
            return None, 0.0

    def add_face(self, name, aligned_face, preview_bgr=None):
        """Memorizza l'embedding del volto sotto il nome indicato (nessun training necessario).
        preview_bgr (opzionale) diventa la miniatura della persona nella pagina Persone."""
        if self.recognizer is None:
            return
        name = (name or "").strip()
        if not name:
            return
        try:
            feat = self._feature(aligned_face).flatten().tolist()
            with self._lock:
                self._add_feature(name, feat)
                if preview_bgr is not None and not self.metadata.get("thumbs", {}).get(name):
                    thumb = self._save_thumb(preview_bgr)
                    if thumb:
                        self.metadata.setdefault("thumbs", {})[name] = thumb
                self.save_metadata()
        except Exception as e:
            print(f"[FaceMemory] Errore aggiunta volto: {e}")

    def _add_feature(self, name, feat):
        samples = self.metadata.setdefault("people", {}).setdefault(name, [])
        samples.append(feat)
        # Limita a 10 campioni per persona per mantenere il confronto rapido
        if len(samples) > MAX_SAMPLES_PER_PERSON:
            self.metadata["people"][name] = samples[-MAX_SAMPLES_PER_PERSON:]

    def retrain(self):
        """No-op: SFace non richiede addestramento (mantenuto per compatibilita')."""
        return

    # ------------------------------------------------------- miniature volti
    def _thumbs_dir(self):
        path = os.path.join(self.faces_dir, "thumbs")
        os.makedirs(path, exist_ok=True)
        return path

    def _save_thumb(self, bgr):
        """Salva un ritaglio 160px del volto; ritorna il nome file (relativo a thumbs/)."""
        try:
            if bgr is None or bgr.size == 0:
                return None
            h, w = bgr.shape[:2]
            scale = 160.0 / max(h, w)
            if scale < 1:
                bgr = cv2.resize(bgr, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
            fname = uuid.uuid4().hex + ".jpg"
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not ok:
                return None
            # imencode + scrittura binaria: cv2.imwrite fallisce sui percorsi con caratteri non ASCII su Windows
            with open(os.path.join(self._thumbs_dir(), fname), "wb") as f:
                f.write(buf.tobytes())
            return fname
        except Exception as e:
            print(f"[FaceMemory] Miniatura non salvata: {e}")
            return None

    def thumb_path(self, fname):
        if not fname:
            return None
        p = os.path.join(self._thumbs_dir(), fname)
        return p if os.path.exists(p) else None

    def _remove_thumb(self, fname):
        p = self.thumb_path(fname)
        if p:
            try:
                os.remove(p)
            except OSError:
                pass

    # ------------------------------------------------- gestione persone (UI)
    def list_people(self):
        """[(nome, n_campioni, percorso_miniatura_o_None)] in ordine alfabetico."""
        with self._lock:
            thumbs = self.metadata.get("thumbs", {})
            return sorted(
                [(n, len(f), self.thumb_path(thumbs.get(n))) for n, f in self.metadata.get("people", {}).items()],
                key=lambda x: x[0].lower())

    def rename_person(self, old, new):
        """Rinomina; se 'new' esiste gia' le due persone vengono unite (stessa persona)."""
        new = (new or "").strip()
        with self._lock:
            people = self.metadata.get("people", {})
            if not new or old not in people or new == old:
                return False
            if new in people:
                self._merge_locked(old, new)
            else:
                people[new] = people.pop(old)
                thumbs = self.metadata.setdefault("thumbs", {})
                if old in thumbs:
                    thumbs[new] = thumbs.pop(old)
            self.save_metadata()
            return True

    def merge_people(self, src, dst):
        with self._lock:
            if src == dst or src not in self.metadata.get("people", {}) or dst not in self.metadata.get("people", {}):
                return False
            self._merge_locked(src, dst)
            self.save_metadata()
            return True

    def _merge_locked(self, src, dst):
        people = self.metadata["people"]
        for feat in people.pop(src, []):
            self._add_feature(dst, feat)
        thumbs = self.metadata.setdefault("thumbs", {})
        t = thumbs.pop(src, None)
        if t and not thumbs.get(dst):
            thumbs[dst] = t
        elif t:
            self._remove_thumb(t)

    def delete_person(self, name):
        with self._lock:
            if name not in self.metadata.get("people", {}):
                return False
            self.metadata["people"].pop(name, None)
            self._remove_thumb(self.metadata.setdefault("thumbs", {}).pop(name, None))
            self.save_metadata()
            return True

    def delete_all_face_data(self):
        """Diritto all'oblio: cancella persone, campioni, miniature e volti in attesa.
        I file dei modelli (YuNet/SFace) restano: non sono dati personali."""
        with self._lock:
            self.metadata = {"people": {}, "thumbs": {}}
            self.pending = []
            self.save_metadata()
            self._save_pending()
            for f in os.listdir(self._thumbs_dir()):
                try:
                    os.remove(os.path.join(self._thumbs_dir(), f))
                except OSError:
                    pass

    # ------------------------------------- volti da identificare (in attesa)
    def _pending_path(self):
        return os.path.join(self.faces_dir, "pending_faces.json")

    def _load_pending(self):
        try:
            with open(self._pending_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_pending(self):
        try:
            with open(self._pending_path(), "w", encoding="utf-8") as f:
                json.dump(self.pending, f, ensure_ascii=False)
        except Exception as e:
            print(f"[FaceMemory] Errore scrittura volti in attesa: {e}")

    def pending_count(self):
        with self._lock:
            return len(self.pending)

    def add_pending(self, aligned_face, preview_bgr, source_path):
        """Mette da parte un volto non riconosciuto, da nominare dopo nella pagina Persone
        (invece di interrompere l'analisi con un popup per ogni volto)."""
        if self.recognizer is None:
            return False
        try:
            feat = self._feature(aligned_face).flatten().tolist()
        except Exception as e:
            print(f"[FaceMemory] Volto in attesa non calcolabile: {e}")
            return False
        thumb = self._save_thumb(preview_bgr)
        with self._lock:
            self.pending.append({"id": uuid.uuid4().hex, "feat": feat, "thumb": thumb, "source": source_path})
            self._save_pending()
        return True

    def _sim(self, a, b):
        a = np.asarray(a, dtype=np.float32).reshape(1, -1)
        b = np.asarray(b, dtype=np.float32).reshape(1, -1)
        return float(self.recognizer.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))

    def pending_groups(self, threshold=COSINE_THRESHOLD):
        """Raggruppa i volti in attesa che si somigliano (collegamento singolo sulla
        somiglianza coseno), cosi' si nomina un gruppo intero con un solo gesto.
        Ritorna [{'ids': [...], 'thumbs': [percorsi], 'sources': [...], 'suggested': nome|None}]
        dal gruppo piu' numeroso al piu' piccolo."""
        with self._lock:
            items = list(self.pending)
        if not items:
            return []
        # i modelli servono solo se c'e' qualcosa da confrontare (aprire la pagina Persone
        # non deve scaricare nulla)
        self._ensure_models()
        n = len(items)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        if self.recognizer is not None:
            feats = np.asarray([it["feat"] for it in items], dtype=np.float32)
            norms = np.linalg.norm(feats, axis=1, keepdims=True)
            norms[norms == 0] = 1
            unit = feats / norms
            sims = unit @ unit.T  # coseno, identico a FR_COSINE ma in un colpo solo
            for i in range(n):
                for j in range(i + 1, n):
                    if sims[i, j] >= threshold:
                        ri, rj = find(i), find(j)
                        if ri != rj:
                            parent[rj] = ri
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(items[i])
        out = []
        for members in groups.values():
            suggested = None
            if self.recognizer is not None:
                best_name, best = None, -1.0
                with self._lock:
                    people = {k: list(v) for k, v in self.metadata.get("people", {}).items()}
                for name, feats_ in people.items():
                    for f in feats_:
                        s = self._sim(members[0]["feat"], f)
                        if s > best:
                            best, best_name = s, name
                if best >= threshold:
                    suggested = best_name
            out.append({
                "ids": [m["id"] for m in members],
                "thumbs": [p for p in (self.thumb_path(m.get("thumb")) for m in members) if p],
                "sources": list(dict.fromkeys(m.get("source") for m in members if m.get("source"))),
                "suggested": suggested,
            })
        out.sort(key=lambda g: -len(g["ids"]))
        return out

    def name_pending(self, ids, name):
        """Assegna un nome a un gruppo di volti in attesa: diventano campioni della persona."""
        name = (name or "").strip()
        if not name:
            return 0
        ids = set(ids)
        with self._lock:
            chosen = [p for p in self.pending if p["id"] in ids]
            for p in chosen:
                self._add_feature(name, p["feat"])
            thumbs = self.metadata.setdefault("thumbs", {})
            for p in chosen:
                if not thumbs.get(name) and p.get("thumb"):
                    thumbs[name] = p["thumb"]
                    p["thumb"] = None  # la miniatura ora appartiene alla persona
            for p in chosen:
                self._remove_thumb(p.get("thumb"))
            self.pending = [p for p in self.pending if p["id"] not in ids]
            self.save_metadata()
            self._save_pending()
            return len(chosen)

    def discard_pending(self, ids):
        ids = set(ids)
        with self._lock:
            for p in self.pending:
                if p["id"] in ids:
                    self._remove_thumb(p.get("thumb"))
            self.pending = [p for p in self.pending if p["id"] not in ids]
            self._save_pending()

    def scan_folder(self, folder, progress_cb=None, should_stop=None):
        """Cerca volti in tutte le foto di una cartella: quelli riconosciuti vengono contati,
        gli sconosciuti finiscono tra i volti da identificare. Ritorna (foto, riconosciuti, nuovi)."""
        self._ensure_models()
        exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'} | raw_preview.RAW_EXTS
        paths = []
        for root, _, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in exts and not f.startswith("._"):
                    paths.append(os.path.join(root, f))
        known = new = 0
        for i, p in enumerate(paths):
            if should_stop and should_stop():
                break
            if progress_cb:
                progress_cb(i, len(paths), os.path.basename(p))
            faces, img = self.detect_faces(p)
            for face in faces or []:
                aligned, bgr = self.crop_face(img, face)
                name, _ = self.predict_face(aligned)
                if name:
                    known += 1
                elif self.add_pending(aligned, bgr, p):
                    new += 1
        if progress_cb:
            progress_cb(len(paths), len(paths), "")
        return len(paths), known, new
