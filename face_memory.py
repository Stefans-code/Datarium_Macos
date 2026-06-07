import os
import sys
import json
import time
import random
import cv2
import numpy as np
import platform
import shutil

class CustomFaceClassifier:
    def __init__(self, num_classes=2, input_dim=512):
        self.num_classes = num_classes
        self.input_dim = input_dim
        self.W = np.zeros((input_dim, num_classes), dtype=np.float32)
        self.b = np.zeros(num_classes, dtype=np.float32)
        
    def softmax(self, x):
        # Protezione da overflow esponenziale
        max_vals = np.max(x, axis=-1, keepdims=True)
        e_x = np.exp(x - max_vals)
        return e_x / np.sum(e_x, axis=-1, keepdims=True)
        
    def forward(self, X):
        logits = np.dot(X, self.W) + self.b
        return self.softmax(logits)
        
    def train(self, X, y, epochs=150, lr=0.1):
        num_samples = X.shape[0]
        y_one_hot = np.zeros((num_samples, self.num_classes), dtype=np.float32)
        y_one_hot[np.arange(num_samples), y] = 1.0
        
        # Discesa del gradiente con regolarizzazione L2 per few-shot learning
        for _ in range(epochs):
            probs = self.forward(X)
            d_logits = (probs - y_one_hot) / num_samples
            dW = np.dot(X.T, d_logits) + 0.01 * self.W  # L2 weight decay
            db = np.sum(d_logits, axis=0)
            
            # Aggiornamento parametri
            self.W -= lr * dW
            self.b -= lr * db

class FaceMemoryManager:
    def __init__(self, base_models_dir=None):
        self.faces_dir = self._get_faces_directory()
        self.crops_dir = os.path.join(self.faces_dir, "crops")
        
        # Crea le cartelle necessarie per i ritagli
        os.makedirs(self.crops_dir, exist_ok=True)
        
        self.metadata_path = os.path.join(self.faces_dir, "faces_metadata.json")
        self.model_path = os.path.join(self.faces_dir, "lbph_model.xml")
        
        # Inizializzazione Rilevatori e Modelli ONNX
        self.detector = None
        self.recognizer_sf = None
        self.ort_session = None
        self.mode = "fallback"
        self.classifier = None
        self.class_mapping = {}
        
        self._init_advanced_models()
        
        # Carica metadati (esegue migrazione e autorigenerazione embedding se necessario)
        self.metadata = self.load_metadata()
        self.recognizer = self.load_recognizer()
        
    def _init_advanced_models(self):
        """Inizializza YuNet, SFace ed ArcFace dalle nuove cartelle sul Desktop dell'utente."""
        # 1. Trova il Desktop in modo cross-platform e multi-lingua
        home = os.path.expanduser("~")
        desktop = home
        for name in ["Desktop", "Scrivania", "Schreibtisch", "Escritorio", "Bureau"]:
            path = os.path.join(home, name)
            if os.path.exists(path):
                desktop = path
                break
                
        # Rileva automaticamente se usare la versione pesante o leggera sul Desktop
        fp_path = os.path.join(desktop, "facialis_pesante")
        fl_path = os.path.join(desktop, "facialis_leggero")
        
        # Se c'è l'allineatore nella pesante, indica che usiamo ArcFace come facialis
        if os.path.exists(os.path.join(fp_path, "allineatore.onnx")) and os.path.exists(os.path.join(fp_path, "facialis.onnx")):
            self.mode = "pesante"
            self.yunet_model_path = os.path.join(fp_path, "rilevatore.onnx")
            self.sface_model_path = os.path.join(fp_path, "allineatore.onnx")
            self.arcface_model_path = os.path.join(fp_path, "facialis.onnx")
        elif os.path.exists(os.path.join(fl_path, "rilevatore.onnx")) and os.path.exists(os.path.join(fl_path, "facialis.onnx")):
            self.mode = "leggero"
            self.yunet_model_path = os.path.join(fl_path, "rilevatore.onnx")
            self.sface_model_path = os.path.join(fl_path, "facialis.onnx") # SFace fa anche l'allineamento
            self.arcface_model_path = None
        else:
            print("[FaceMemory] Attenzione: Modelli facciali non rilevati sul Desktop. Uso modalità fallback Haar/LBPH.")
            return
            
        # 1. Rilevatore YuNet
        if os.path.exists(self.yunet_model_path):
            try:
                self.detector = cv2.FaceDetectorYN.create(
                    model=self.yunet_model_path,
                    config="",
                    input_size=(320, 320),
                    score_threshold=0.6,
                    nms_threshold=0.3,
                    top_k=5000
                )
                print(f"[FaceMemory] Rilevatore YuNet ({self.mode}) caricato da: {self.yunet_model_path}")
            except Exception as e:
                print(f"[FaceMemory] Errore caricamento rilevatore YuNet: {e}")
                
        # 2. Allineatore/Riconoscitore SFace
        if os.path.exists(self.sface_model_path):
            try:
                self.recognizer_sf = cv2.FaceRecognizerSF.create(
                    model=self.sface_model_path,
                    config=""
                )
                print(f"[FaceMemory] Allineatore/Riconoscitore SFace caricato da: {self.sface_model_path}")
            except Exception as e:
                print(f"[FaceMemory] Errore caricamento allineatore SFace: {e}")
                
        # 3. Estrattore ArcFace (solo versione pesante)
        if self.mode == "pesante" and self.arcface_model_path and os.path.exists(self.arcface_model_path):
            try:
                import onnxruntime as ort
                available_providers = ort.get_available_providers()
                providers = []
                
                if "DmlExecutionProvider" in available_providers:
                    providers.append("DmlExecutionProvider")
                if "CoreMLExecutionProvider" in available_providers:
                    providers.append("CoreMLExecutionProvider")
                if "CUDAExecutionProvider" in available_providers:
                    providers.append("CUDAExecutionProvider")
                providers.append("CPUExecutionProvider")
                
                self.ort_session = ort.InferenceSession(self.arcface_model_path, providers=providers)
                print(f"[FaceMemory] ArcFace ONNX caricato con i provider: {self.ort_session.get_providers()}")
            except Exception as e:
                print(f"[FaceMemory] Errore caricamento ArcFace ONNX Runtime: {e}")

    def _get_faces_directory(self):
        """Individua una cartella scrivibile persistente per i dati di face memory."""
        system = platform.system()
        try:
            if system == "Windows":
                base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
                path = os.path.join(base, "Datarium", "faces")
            elif system == "Darwin": # macOS
                path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium", "faces")
            else:
                path = os.path.join(os.path.expanduser("~"), ".datarium", "faces")
            
            os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            print(f"[FaceMemory] Errore risoluzione cartella scrivibile: {e}, uso fallback locale.")
            home = os.path.expanduser("~")
            path = os.path.join(home, ".datarium", "faces")
            os.makedirs(path, exist_ok=True)
            return path
        
    def load_metadata(self):
        """Carica i metadati ed esegue l'aggiornamento automatico e addestramento del classificatore custom."""
        if os.path.exists(self.metadata_path):
            try:
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception as e:
                print(f"[FaceMemory] Errore lettura metadati: {e}")
                meta = {"names": {}, "crops": {}}
        else:
            meta = {"names": {}, "crops": {}}
            
        if "names" not in meta: meta["names"] = {}
        if "crops" not in meta: meta["crops"] = {}
        
        # Rigenerazione del database (self-healing) da versione precedente o cambio di qualità (128D <-> 512D)
        expected_dim = 512 if (self.ort_session is not None) else 128
        
        if self.recognizer_sf is not None:
            dirty = False
            for crop_file, val in list(meta["crops"].items()):
                needs_update = False
                label_id = None
                
                if isinstance(val, int):
                    needs_update = True
                    label_id = val
                elif isinstance(val, dict):
                    label_id = val.get("label_id")
                    emb = val.get("embedding")
                    if emb is None or len(emb) != expected_dim:
                        needs_update = True
                        
                if needs_update and label_id is not None:
                    crop_path = os.path.join(self.crops_dir, crop_file)
                    if os.path.exists(crop_path):
                        try:
                            img = cv2.imread(crop_path)
                            if img is not None:
                                if len(img.shape) == 2 or img.shape[2] == 1:
                                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                                aligned = cv2.resize(img, (112, 112))
                                emb = self.get_embedding(aligned)
                                if emb is not None:
                                    meta["crops"][crop_file] = {
                                        "label_id": label_id,
                                        "embedding": emb.tolist()
                                    }
                                    dirty = True
                                else:
                                    meta["crops"].pop(crop_file, None)
                                    dirty = True
                            else:
                                meta["crops"].pop(crop_file, None)
                                dirty = True
                        except Exception as ex:
                            print(f"[FaceMemory] Errore rigenerazione embedding '{crop_file}': {ex}")
                    else:
                        meta["crops"].pop(crop_file, None)
                        dirty = True
            if dirty:
                try:
                    with open(self.metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(meta, f, ensure_ascii=False, indent=4)
                    print(f"[FaceMemory] Database autorigenerato per il formato {expected_dim}D.")
                except Exception as we:
                    print(f"[FaceMemory] Errore scrittura database autorigenerato: {we}")
            
            # Addestra la rete neurale custom se ci sono abbastanza classi
            self.train_classifier(meta)
                    
        return meta

    def save_metadata(self):
        try:
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[FaceMemory] Errore scrittura metadati: {e}")

    def load_recognizer(self):
        """Carica il modello LBPH (solo per compatibilità in caso di fallback)."""
        if os.path.exists(self.model_path):
            try:
                recognizer = cv2.face.LBPHFaceRecognizer_create()
                recognizer.read(self.model_path)
                return recognizer
            except Exception as e:
                print(f"[FaceMemory] Errore caricamento modello XML: {e}")
        return None

    def _detect_faces_fallback(self, img):
        """Rilevamento volti di riserva usando Haar Cascades."""
        if img is None:
            return []
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if not os.path.exists(cascade_path):
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            face_cascade = cv2.CascadeClassifier(cascade_path)
            
            if face_cascade.empty():
                for fallback_dir in [sys.prefix, os.path.dirname(cv2.__file__)]:
                    alt_cascade = os.path.join(fallback_dir, "data", "haarcascade_frontalface_default.xml")
                    if os.path.exists(alt_cascade):
                        face_cascade = cv2.CascadeClassifier(alt_cascade)
                        if not face_cascade.empty():
                            break
                            
            faces = face_cascade.detectMultiScale(
                gray, 
                scaleFactor=1.05, 
                minNeighbors=6, 
                minSize=(60, 60)
            )
            return list(faces)
        except Exception as e:
            print(f"[FaceMemory] Errore nel rilevamento volti fallback: {e}")
            return []

    def detect_faces(self, media_path):
        """Rileva volti in un'immagine o video usando YuNet (con fallback a Haar Cascades)."""
        try:
            img = cv2.imread(media_path)
            if img is None:
                cap = cv2.VideoCapture(media_path)
                if cap.isOpened():
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    if total_frames > 0:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, min(30, total_frames // 4))
                    ret, frame = cap.read()
                    if ret:
                        img = frame
                cap.release()
                
            if img is None:
                return [], None
                
            if self.detector is None:
                faces = self._detect_faces_fallback(img)
                return faces, img
                
            # Rilevamento avanzato YuNet
            h, w = img.shape[:2]
            self.detector.setInputSize((w, h))
            retval, faces = self.detector.detect(img)
            
            if faces is None:
                return [], img
            return list(faces), img
        except Exception as e:
            print(f"[FaceMemory] Errore nel rilevamento volti: {e}")
            return [], None

    def _crop_face_fallback(self, img, rect):
        """Ritaglio standard per LBPH."""
        x, y, w, h = rect
        margin = int(w * 0.1)
        h_img, w_img = img.shape[:2]
        
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(w_img, x + w + margin)
        y2 = min(h_img, y + h + margin)
        
        bgr_crop = img[y1:y2, x1:x2]
        if bgr_crop.size == 0:
            bgr_crop = img[y:y+h, x:x+w]
            
        gray_crop = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
        gray_equalized = cv2.equalizeHist(gray_crop)
        gray_resized = cv2.resize(gray_equalized, (120, 120))
        return gray_resized, bgr_crop

    def crop_face(self, img, rect):
        """Ritaglia e allinea geometricamente il volto."""
        if self.detector is None or self.recognizer_sf is None:
            return self._crop_face_fallback(img, rect)
            
        try:
            aligned_face = self.recognizer_sf.alignCrop(img, rect)
            return aligned_face, aligned_face
        except Exception as e:
            print(f"[FaceMemory] Errore allineamento geometrico: {e}. Uso ritaglio semplice...")
            try:
                x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
                crop = img[max(0, y):y+h, max(0, x):x+w]
                crop_resized = cv2.resize(crop, (112, 112))
                return crop_resized, crop_resized
            except Exception as ex:
                print(f"[FaceMemory] Simple crop fallito: {ex}")
                black = np.zeros((112, 112, 3), dtype=np.uint8)
                return black, black

    def get_embedding(self, aligned_face):
        """Genera l'embedding a 128D (SFace) o 512D (ArcFace)."""
        if self.recognizer_sf is None:
            return None
            
        try:
            if self.ort_session is None:
                # Modello leggero: embedding di SFace (128D)
                embedding = self.recognizer_sf.feature(aligned_face)
                emb = embedding[0]
            else:
                # Modello pesante: embedding di ArcFace (512D)
                rgb_aligned = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2RGB)
                img_data = rgb_aligned.astype(np.float32)
                img_data = (img_data - 127.5) / 128.0
                img_data = img_data.transpose((2, 0, 1))
                img_data = np.expand_dims(img_data, axis=0)
                
                inputs = {self.ort_session.get_inputs()[0].name: img_data}
                outputs = self.ort_session.run(None, inputs)
                emb = outputs[0][0]
                
            # Normalizzazione L2
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            return emb
        except Exception as e:
            print(f"[FaceMemory] Errore calcolo embedding: {e}")
            return None

    def train_classifier(self, meta=None):
        """Addestra la nostra rete neurale di classificazione custom in NumPy."""
        if meta is None:
            meta = self.metadata
            
        crops = meta.get("crops", {})
        unique_labels = set()
        X_list = []
        y_list = []
        
        for crop_file, crop_data in crops.items():
            if isinstance(crop_data, dict) and "embedding" in crop_data:
                emb = crop_data["embedding"]
                label_id = crop_data["label_id"]
                X_list.append(emb)
                y_list.append(label_id)
                unique_labels.add(label_id)
                
        # Addestriamo il classificatore solo se ci sono almeno 2 persone registrate
        if len(unique_labels) >= 2:
            # Mappa gli ID in indici continui
            label_to_idx = {lid: idx for idx, lid in enumerate(sorted(unique_labels))}
            self.class_mapping = {idx: str(lid) for lid, idx in label_to_idx.items()}
            
            X = np.array(X_list, dtype=np.float32)
            y = np.array([label_to_idx[lid] for lid in y_list], dtype=np.int32)
            
            input_dim = X.shape[1]
            num_classes = len(unique_labels)
            
            self.classifier = CustomFaceClassifier(num_classes=num_classes, input_dim=input_dim)
            self.classifier.train(X, y, epochs=150, lr=0.1)
            
            meta["classifier"] = {
                "W": self.classifier.W.tolist(),
                "b": self.classifier.b.tolist(),
                "class_mapping": self.class_mapping
            }
            print(f"[FaceMemory] Modello neurale custom addestrato. Classi: {num_classes}, input: {input_dim}D")
        else:
            self.classifier = None
            meta.pop("classifier", None)

    def _predict_face_fallback(self, gray_crop, threshold=80.0):
        if self.recognizer is None:
            return None, 100.0
            
        try:
            label, confidence = self.recognizer.predict(gray_crop)
            if label != 0 and confidence < threshold:
                name = self.metadata["names"].get(str(label))
                if name:
                    return name, confidence
            return None, confidence
        except Exception as e:
            print(f"[FaceMemory] Errore predizione fallback LBPH: {e}")
            return None, 100.0

    def predict_face(self, aligned_face, threshold=0.45):
        """Predice l'identità del volto allineato calcolando la somiglianza del nostro modello."""
        if self.recognizer_sf is None:
            return self._predict_face_fallback(aligned_face)
            
        try:
            query_emb = self.get_embedding(aligned_face)
            if query_emb is None:
                return None, -1.0
                
            # Se la rete neurale custom è addestrata
            if self.classifier is not None:
                probs = self.classifier.forward(query_emb)
                pred_class = int(np.argmax(probs))
                
                label_id = self.class_mapping[pred_class]
                name = self.metadata["names"].get(str(label_id))
                
                # Valida la confidenza tramite somiglianza coseno con il crop più vicino di questo utente
                best_sim = -1.0
                for crop_file, crop_data in self.metadata.get("crops", {}).items():
                    if isinstance(crop_data, dict) and "embedding" in crop_data:
                        if str(crop_data["label_id"]) == str(label_id):
                            emb = np.array(crop_data["embedding"], dtype=np.float32)
                            sim = float(np.dot(query_emb, emb))
                            if sim > best_sim:
                                best_sim = sim
                                
                # Impostiamo soglie diverse per SFace (128D) ed ArcFace (512D)
                min_sim = 0.35 if self.ort_session is None else 0.45
                if best_sim >= min_sim:
                    return name, best_sim
                return None, best_sim
            else:
                # Se c'è solo un utente, usiamo la similarità coseno diretta (1-Nearest Neighbor)
                best_name = None
                best_sim = -1.0
                for crop_file, crop_data in self.metadata.get("crops", {}).items():
                    if isinstance(crop_data, dict) and "embedding" in crop_data:
                        emb = np.array(crop_data["embedding"], dtype=np.float32)
                        sim = float(np.dot(query_emb, emb))
                        if sim > best_sim:
                            best_sim = sim
                            label_id = crop_data["label_id"]
                            best_name = self.metadata["names"].get(str(label_id))
                            
                min_sim = 0.35 if self.ort_session is None else 0.45
                if best_sim >= min_sim:
                    return best_name, best_sim
                return None, best_sim
        except Exception as e:
            print(f"[FaceMemory] Errore durante predict_face: {e}")
            return None, -1.0

    def add_face(self, name, aligned_face):
        """Salva il nuovo volto in memoria ed aggiorna istantaneamente il database neurale."""
        name = name.strip()
        if not name:
            return
            
        label_id = None
        for lid, n in self.metadata["names"].items():
            if n.lower() == name.lower():
                label_id = int(lid)
                break
                
        if label_id is None:
            existing_ids = [int(x) for x in self.metadata["names"].keys()]
            label_id = max(existing_ids) + 1 if existing_ids else 1
            self.metadata["names"][str(label_id)] = name
            
        # Salva l'immagine del ritaglio
        timestamp = int(time.time())
        rand = random.randint(1000, 9999)
        crop_filename = f"{label_id}_{timestamp}_{rand}.png"
        crop_path = os.path.join(self.crops_dir, crop_filename)
        
        try:
            if self.recognizer_sf is None:
                # Fallback LBPH
                cv2.imwrite(crop_path, aligned_face)
                self.metadata["crops"][crop_filename] = label_id
                self.save_metadata()
                self.retrain()
            else:
                # Salva il ritaglio allineato BGR 112x112
                cv2.imwrite(crop_path, aligned_face)
                
                # Calcola l'embedding (128D o 512D)
                emb = self.get_embedding(aligned_face)
                if emb is not None:
                    self.metadata["crops"][crop_filename] = {
                        "label_id": label_id,
                        "embedding": emb.tolist()
                    }
                else:
                    self.metadata["crops"][crop_filename] = label_id
                    
                # Riaddestra la rete neurale custom e salva
                self.train_classifier()
                self.save_metadata()
                print(f"[FaceMemory] Volto '{name}' registrato con successo con il nostro classificatore neurale.")
        except Exception as e:
            print(f"[FaceMemory] Errore durante add_face: {e}")

    def retrain(self):
        """Riaddestra il modello LBPH se siamo in modalità fallback (no-op per i volti avanzati)."""
        if self.recognizer_sf is None:
            images = []
            labels = []
            
            dummy_img = np.random.randint(0, 255, (120, 120), dtype=np.uint8)
            images.append(dummy_img)
            labels.append(0)
            
            for crop_filename, val in list(self.metadata["crops"].items()):
                label_id = val if isinstance(val, int) else val.get("label_id")
                if label_id is not None:
                    crop_path = os.path.join(self.crops_dir, crop_filename)
                    if os.path.exists(crop_path):
                        img = cv2.imread(crop_path, cv2.IMREAD_GRAYSCALE)
                        if img is not None:
                            if img.shape != (120, 120):
                                img = cv2.resize(img, (120, 120))
                            img = cv2.equalizeHist(img)
                            images.append(img)
                            labels.append(int(label_id))
                            
            if len(labels) >= 2:
                try:
                    recognizer = cv2.face.LBPHFaceRecognizer_create()
                    recognizer.train(images, np.array(labels))
                    recognizer.write(self.model_path)
                    self.recognizer = recognizer
                    print(f"[FaceMemory] Modello di fallback LBPH addestrato. Classi: {len(np.unique(labels))-1}")
                except Exception as e:
                    print(f"[FaceMemory] Errore durante l'addestramento di fallback: {e}")
