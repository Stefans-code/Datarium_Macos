import os
import sys
import json
import time
import random
import cv2
import numpy as np
import platform
import shutil

class FaceMemoryManager:
    def __init__(self, base_models_dir=None):
        # Risolvi la cartella dei modelli
        if base_models_dir:
            self.models_dir = base_models_dir
        else:
            if getattr(sys, 'frozen', False):
                self.models_dir = os.path.join(os.path.dirname(sys.executable), "models")
            else:
                self.models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
        
        self.faces_dir = self._get_faces_directory()
        self.crops_dir = os.path.join(self.faces_dir, "crops")
        
        # Crea le cartelle necessarie
        os.makedirs(self.crops_dir, exist_ok=True)
        
        self.metadata_path = os.path.join(self.faces_dir, "faces_metadata.json")
        self.model_path = os.path.join(self.faces_dir, "lbph_model.xml")
        
        # Modelli ONNX per il riconoscimento avanzato
        self.yunet_model_path = os.path.join(self.models_dir, "face_detection_yunet_2023mar.onnx")
        self.sface_model_path = os.path.join(self.models_dir, "face_recognition_sface_2021dec.onnx")
        self.arcface_model_path = os.path.join(self.models_dir, "arcface.onnx")
        
        # Gestione backup di ArcFace
        bak_path = os.path.join(self.models_dir, "arcface.onnx.bak")
        if not os.path.exists(self.arcface_model_path) and os.path.exists(bak_path):
            try:
                print(f"[FaceMemory] Ripristino ArcFace da backup: {bak_path} -> {self.arcface_model_path}")
                shutil.copy2(bak_path, self.arcface_model_path)
            except Exception as e:
                print(f"[FaceMemory] Errore copia backup ArcFace: {e}")
                
        # Inizializzazione Rivelatori e Modelli ONNX
        self.detector = None
        self.recognizer_sf = None
        self.ort_session = None
        
        self._init_advanced_models()
        
        # Esegui la migrazione automatica se i file esistono nella vecchia posizione
        self._migrate_existing_data()
        
        self.metadata = self.load_metadata()
        self.recognizer = self.load_recognizer()
        
    def _init_advanced_models(self):
        """Inizializza YuNet, SFace ed ArcFace con accelerazione GPU (DirectML) se disponibile."""
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
                print("[FaceMemory] Rilevatore YuNet caricato correttamente.")
            except Exception as e:
                print(f"[FaceMemory] Impossibile caricare YuNet: {e}")
                
        # 2. Allineatore SFace
        if os.path.exists(self.sface_model_path):
            try:
                self.recognizer_sf = cv2.FaceRecognizerSF.create(
                    model=self.sface_model_path,
                    config=""
                )
                print("[FaceMemory] Allineatore SFace caricato correttamente.")
            except Exception as e:
                print(f"[FaceMemory] Impossibile caricare SFace: {e}")
                
        # 3. Estrattore ArcFace (tramite ONNX Runtime con DirectML/GPU)
        if os.path.exists(self.arcface_model_path):
            try:
                import onnxruntime as ort
                available_providers = ort.get_available_providers()
                providers = []
                
                # Aggiungiamo i provider in ordine di preferenza per accelerazione
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
                print(f"[FaceMemory] Impossibile caricare ArcFace ONNX Runtime: {e}")

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
            path = os.path.join(self.models_dir, "faces")
            os.makedirs(path, exist_ok=True)
            return path

    def _migrate_existing_data(self):
        """Migra i dati della faccia dalla vecchia cartella models/faces se presente."""
        old_faces_dir = os.path.join(self.models_dir, "faces")
        if not os.path.exists(old_faces_dir) or os.path.abspath(old_faces_dir) == os.path.abspath(self.faces_dir):
            return
            
        old_meta = os.path.join(old_faces_dir, "faces_metadata.json")
        old_model = os.path.join(old_faces_dir, "lbph_model.xml")
        old_crops = os.path.join(old_faces_dir, "crops")
        
        if os.path.exists(old_meta) and not os.path.exists(self.metadata_path):
            try:
                shutil.copy2(old_meta, self.metadata_path)
                print(f"[FaceMemory] Metadati migrati con successo in: {self.metadata_path}")
            except Exception as me:
                print(f"[FaceMemory] Errore migrazione metadati: {me}")
                
        if os.path.exists(old_model) and not os.path.exists(self.model_path):
            try:
                shutil.copy2(old_model, self.model_path)
                print(f"[FaceMemory] Modello XML migrato con successo in: {self.model_path}")
            except Exception as mo:
                print(f"[FaceMemory] Errore migrazione modello XML: {mo}")
                
        if os.path.exists(old_crops):
            try:
                for f in os.listdir(old_crops):
                    old_f_path = os.path.join(old_crops, f)
                    new_f_path = os.path.join(self.crops_dir, f)
                    if os.path.isfile(old_f_path) and not os.path.exists(new_f_path):
                        shutil.copy2(old_f_path, new_f_path)
                print("[FaceMemory] Ritagli facciali migrati con successo.")
            except Exception as co:
                print(f"[FaceMemory] Errore migrazione ritagli facciali: {co}")
        
    def load_metadata(self):
        """Carica i metadati ed esegue l'aggiornamento automatico se necessario."""
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
        
        # Migrazione autorigenerante (self-healing) da vecchio database a nuovo formato con embedding
        if self.ort_session is not None and self.recognizer_sf is not None:
            dirty = False
            for crop_file, val in list(meta["crops"].items()):
                # Se il valore è un intero, indica che è del vecchio database (solo label_id)
                if isinstance(val, int):
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
                                        "label_id": val,
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
                            print(f"[FaceMemory] Errore migrazione '{crop_file}': {ex}")
                    else:
                        meta["crops"].pop(crop_file, None)
                        dirty = True
            if dirty:
                try:
                    with open(self.metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(meta, f, ensure_ascii=False, indent=4)
                    print("[FaceMemory] Autorigenerazione database: completata ed aggiornata ad ArcFace.")
                except Exception as we:
                    print(f"[FaceMemory] Errore scrittura database autorigenerato: {we}")
                    
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
                
            # Se YuNet non è inizializzato, usa il fallback Haar Cascades
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
        """
        Ritaglia e allinea geometricamente il volto.
        Ritorna: (aligned_crop, aligned_crop) se in modalità avanzata, altrimenti (gray_crop, bgr_crop) per LBPH.
        """
        if self.detector is None or self.recognizer_sf is None:
            return self._crop_face_fallback(img, rect)
            
        try:
            # rect contiene i dati di YuNet (15 elementi, inclusi bounding box e landmarks degli occhi/naso/bocca)
            aligned_face = self.recognizer_sf.alignCrop(img, rect)
            # Restituiamo l'immagine allineata per entrambe le variabili per preservare la firma dei metodi in main.py
            return aligned_face, aligned_face
        except Exception as e:
            print(f"[FaceMemory] Errore allineamento geometrico SFace: {e}. Uso ritaglio semplice...")
            try:
                # Semplice ritaglio rettangolare basato sul bounding box di YuNet
                x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
                crop = img[max(0, y):y+h, max(0, x):x+w]
                crop_resized = cv2.resize(crop, (112, 112))
                return crop_resized, crop_resized
            except Exception as ex:
                print(f"[FaceMemory] Semplice crop fallito: {ex}")
                black = np.zeros((112, 112, 3), dtype=np.uint8)
                return black, black

    def get_embedding(self, aligned_face):
        """Genera l'embedding a 512 dimensioni da ArcFace."""
        if self.ort_session is None:
            return None
            
        try:
            rgb_aligned = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2RGB)
            img_data = rgb_aligned.astype(np.float32)
            # Normalizzazione [-1, 1]
            img_data = (img_data - 127.5) / 128.0
            # HWC -> CHW
            img_data = img_data.transpose((2, 0, 1))
            # Espande a batch dimension
            img_data = np.expand_dims(img_data, axis=0)
            
            # Esecuzione ONNX session
            inputs = {self.ort_session.get_inputs()[0].name: img_data}
            outputs = self.ort_session.run(None, inputs)
            embedding = outputs[0][0]
            
            # Normalizzazione L2
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            return embedding
        except Exception as e:
            print(f"[FaceMemory] Errore calcolo embedding ArcFace: {e}")
            return None

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

    def predict_face(self, aligned_face, threshold=0.40):
        """
        Predice l'identità del volto allineato calcolando la somiglianza coseno.
        Ritorna: (nome, similarità) se trovato, altrimenti (None, similarità)
        """
        if self.ort_session is None or self.recognizer_sf is None:
            return self._predict_face_fallback(aligned_face)
            
        try:
            query_emb = self.get_embedding(aligned_face)
            if query_emb is None:
                return None, -1.0
                
            best_name = None
            best_sim = -1.0
            
            # Esegui la classificazione per similarità coseno in NumPy
            for crop_file, crop_data in self.metadata.get("crops", {}).items():
                if isinstance(crop_data, dict) and "embedding" in crop_data:
                    emb = np.array(crop_data["embedding"], dtype=np.float32)
                    # Dot product = somiglianza coseno poiché entrambi gli embedding sono normalizzati L2
                    sim = float(np.dot(query_emb, emb))
                    if sim > best_sim:
                        best_sim = sim
                        label_id = crop_data["label_id"]
                        best_name = self.metadata["names"].get(str(label_id))
            
            if best_sim >= threshold:
                return best_name, best_sim
            return None, best_sim
        except Exception as e:
            print(f"[FaceMemory] Errore durante predict_face: {e}")
            return None, -1.0

    def add_face(self, name, aligned_face):
        """Salva il nuovo volto in memoria ed aggiorna istantaneamente il database."""
        name = name.strip()
        if not name:
            return
            
        # Trova o crea label_id per questo nome
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
            if self.ort_session is None or self.recognizer_sf is None:
                # Fallback LBPH
                cv2.imwrite(crop_path, aligned_face)
                self.metadata["crops"][crop_filename] = label_id
                self.save_metadata()
                self.retrain()
            else:
                # Salva il ritaglio allineato BGR 112x112
                cv2.imwrite(crop_path, aligned_face)
                
                # Calcola l'embedding ArcFace
                emb = self.get_embedding(aligned_face)
                if emb is not None:
                    self.metadata["crops"][crop_filename] = {
                        "label_id": label_id,
                        "embedding": emb.tolist()
                    }
                else:
                    self.metadata["crops"][crop_filename] = label_id
                    
                self.save_metadata()
                print(f"[FaceMemory] Volto '{name}' registrato con successo con embedding ArcFace (GPU/CPU).")
        except Exception as e:
            print(f"[FaceMemory] Errore durante add_face: {e}")

    def retrain(self):
        """Riaddestra il modello LBPH se siamo in modalità fallback (no-op per ArcFace)."""
        if self.ort_session is None or self.recognizer_sf is None:
            images = []
            labels = []
            
            # Aggiungiamo sempre una classe dummy "0" con rumore casuale per evitare il crash di OpenCV
            dummy_img = np.random.randint(0, 255, (120, 120), dtype=np.uint8)
            images.append(dummy_img)
            labels.append(0)
            
            # Carica tutti i ritagli reali
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
                    print(f"[FaceMemory] Modello di fallback LBPH addestrato con successo. Classi: {len(np.unique(labels))-1}")
                except Exception as e:
                    print(f"[FaceMemory] Errore durante l'addestramento di fallback: {e}")
