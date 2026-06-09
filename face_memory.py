import os
import sys
import json
import platform
import urllib.request
import cv2
import numpy as np

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


class FaceMemoryManager:
    """Riconoscimento volti basato su YuNet + SFace (OpenCV), senza alcun LLM.
    Mantiene l'interfaccia usata da main.py: detect_faces / crop_face / predict_face / add_face."""

    def __init__(self, base_models_dir=None):
        # base_models_dir mantenuto per compatibilita' di firma (non piu' usato per i volti)
        self.faces_dir = self._get_faces_directory()
        os.makedirs(self.faces_dir, exist_ok=True)

        self.metadata_path = os.path.join(self.faces_dir, "faces_sface.json")
        self.metadata = self.load_metadata()

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
            img = cv2.imread(media_path)
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
            for name, feats in self.metadata.get("people", {}).items():
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

    def add_face(self, name, aligned_face):
        """Memorizza l'embedding del volto sotto il nome indicato (nessun training necessario)."""
        if self.recognizer is None:
            return
        name = (name or "").strip()
        if not name:
            return
        try:
            feat = self._feature(aligned_face).flatten().tolist()
            self.metadata.setdefault("people", {}).setdefault(name, []).append(feat)
            # Limita a 10 campioni per persona per mantenere il confronto rapido
            if len(self.metadata["people"][name]) > 10:
                self.metadata["people"][name] = self.metadata["people"][name][-10:]
            self.save_metadata()
        except Exception as e:
            print(f"[FaceMemory] Errore aggiunta volto: {e}")

    def retrain(self):
        """No-op: SFace non richiede addestramento (mantenuto per compatibilita')."""
        return
