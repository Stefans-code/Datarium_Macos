import os
import sys
import json
import time
import random
import cv2
import numpy as np
from PIL import Image
import platform
import shutil

class FaceMemoryManager:
    def __init__(self, base_models_dir=None):
        # Risolvi la cartella dei modelli in modo coerente con AIEngine
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
        
        # Esegui la migrazione automatica se i file esistono nella vecchia posizione
        self._migrate_existing_data()
        
        self.metadata = self.load_metadata()
        self.recognizer = self.load_recognizer()
        
    def _get_faces_directory(self):
        """Individua una cartella scrivibile persistente per i dati di face memory."""
        system = platform.system()
        try:
            if system == "Windows":
                # %LOCALAPPDATA%/Datarium/faces
                base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
                path = os.path.join(base, "Datarium", "faces")
            elif system == "Darwin": # macOS
                # ~/Library/Application Support/Datarium/faces
                path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium", "faces")
            else:
                path = os.path.join(os.path.expanduser("~"), ".datarium", "faces")
            
            os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            # Fallback a sotto-cartella del modello originale
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
        
        # Migrazione metadati
        if os.path.exists(old_meta) and not os.path.exists(self.metadata_path):
            try:
                shutil.copy2(old_meta, self.metadata_path)
                print(f"[FaceMemory] Metadati migrati con successo in: {self.metadata_path}")
            except Exception as me:
                print(f"[FaceMemory] Errore migrazione metadati: {me}")
                
        # Migrazione modello
        if os.path.exists(old_model) and not os.path.exists(self.model_path):
            try:
                shutil.copy2(old_model, self.model_path)
                print(f"[FaceMemory] Modello XML migrato con successo in: {self.model_path}")
            except Exception as mo:
                print(f"[FaceMemory] Errore migrazione modello XML: {mo}")
                
        # Migrazione crops
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
        if os.path.exists(self.metadata_path):
            try:
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[FaceMemory] Errore lettura metadati: {e}")
        return {"names": {}, "crops": {}}

    def save_metadata(self):
        try:
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[FaceMemory] Errore scrittura metadati: {e}")

    def load_recognizer(self):
        if os.path.exists(self.model_path):
            try:
                recognizer = cv2.face.LBPHFaceRecognizer_create()
                recognizer.read(self.model_path)
                return recognizer
            except Exception as e:
                print(f"[FaceMemory] Errore caricamento modello XML: {e}")
        return None

    def detect_faces(self, media_path):
        """Rileva facce in un'immagine o video."""
        try:
            img = cv2.imread(media_path)
            
            # Se cv2.imread fallisce, prova ad aprire come video
            if img is None:
                cap = cv2.VideoCapture(media_path)
                if cap.isOpened():
                    # Salta il primissimo frame nero, vai a un po' più avanti nel video
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    if total_frames > 0:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, min(30, total_frames // 4))
                    ret, frame = cap.read()
                    if ret:
                        img = frame
                cap.release()
                
            if img is None:
                return [], None
                
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Percorso del classificatore a cascata integrato in OpenCV
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if not os.path.exists(cascade_path):
                # Fallback standard
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                
            face_cascade = cv2.CascadeClassifier(cascade_path)
            
            # Se è vuoto, proviamo fallbacks robusti per ambienti frozen/condizionali
            if face_cascade.empty():
                print(f"[FaceMemory] Classificatore a cascata vuoto su '{cascade_path}'. Prova percorsi alternativi...")
                for fallback_dir in [sys.prefix, os.path.dirname(cv2.__file__)]:
                    alt_cascade = os.path.join(fallback_dir, "data", "haarcascade_frontalface_default.xml")
                    if os.path.exists(alt_cascade):
                        face_cascade = cv2.CascadeClassifier(alt_cascade)
                        if not face_cascade.empty():
                            print(f"[FaceMemory] Rilevatore caricato con successo da fallback: {alt_cascade}")
                            break
                            
            # Parametri ottimali per minimizzare falsi positivi e rilevare anche facce piccole
            faces = face_cascade.detectMultiScale(
                gray, 
                scaleFactor=1.05, 
                minNeighbors=6, 
                minSize=(60, 60)
            )
            return list(faces), img
        except Exception as e:
            print(f"[FaceMemory] Errore nel rilevamento volti: {e}")
            return [], None

    def crop_face(self, img, rect):
        """
        Ritaglia e pre-processa il volto dall'immagine originale.
        Ritorna: (gray_crop_resized, bgr_crop)
        """
        x, y, w, h = rect
        # Aggiungiamo un leggero margine attorno alla faccia per catturare più dettagli
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
        
        # Migliora il contrasto (equalizzazione dell'istogramma) per renderlo robusto alle variazioni di luce
        gray_equalized = cv2.equalizeHist(gray_crop)
        
        # Dimensione standard per LBPH recognizer
        gray_resized = cv2.resize(gray_equalized, (120, 120))
        
        return gray_resized, bgr_crop

    def predict_face(self, gray_crop, threshold=80.0):
        """
        Identifica il volto ritagliato.
        Ritorna: (nome, confidenza) se trovato, altrimenti (None, confidenza)
        """
        if self.recognizer is None:
            return None, 100.0
            
        try:
            label, confidence = self.recognizer.predict(gray_crop)
            # LBPH restituisce la distanza chi-quadro; un valore inferiore a 75-80 indica ottima confidenza
            if label != 0 and confidence < threshold:
                name = self.metadata["names"].get(str(label))
                if name:
                    return name, confidence
            return None, confidence
        except Exception as e:
            print(f"[FaceMemory] Errore predizione: {e}")
            return None, 100.0

    def add_face(self, name, gray_crop):
        """
        Salva la nuova faccia nel database e riaddestra il modello.
        """
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
            # Trova il massimo ID numerico esistente
            existing_ids = [int(x) for x in self.metadata["names"].keys()]
            # Salta 0 perché è riservato alla classe dummy
            label_id = max(existing_ids) + 1 if existing_ids else 1
            self.metadata["names"][str(label_id)] = name
            
        # Salva l'immagine del ritaglio
        timestamp = int(time.time())
        rand = random.randint(1000, 9999)
        crop_filename = f"{label_id}_{timestamp}_{rand}.png"
        crop_path = os.path.join(self.crops_dir, crop_filename)
        
        try:
            cv2.imwrite(crop_path, gray_crop)
            self.metadata["crops"][crop_filename] = label_id
            self.save_metadata()
            
            # Riaddestra il modello
            self.retrain()
        except Exception as e:
            print(f"[FaceMemory] Errore durante l'aggiunta del volto: {e}")

    def retrain(self):
        """
        Riaddestra il modello LBPH con tutti i volti salvati in memoria.
        """
        images = []
        labels = []
        
        # Aggiungiamo sempre una classe dummy "0" con rumore casuale per evitare il crash di OpenCV
        # quando c'è solo una persona nel database.
        dummy_img = np.random.randint(0, 255, (120, 120), dtype=np.uint8)
        images.append(dummy_img)
        labels.append(0)
        
        # Carica tutti i ritagli reali
        for crop_filename, label_id in list(self.metadata["crops"].items()):
            crop_path = os.path.join(self.crops_dir, crop_filename)
            if os.path.exists(crop_path):
                img = cv2.imread(crop_path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    # Assicurati della dimensione corretta
                    if img.shape != (120, 120):
                        img = cv2.resize(img, (120, 120))
                    # Applica equalizzazione istogramma per consistenza
                    img = cv2.equalizeHist(img)
                    images.append(img)
                    labels.append(int(label_id))
            else:
                # Rimuovi dai metadati se il file è andato perduto
                self.metadata["crops"].pop(crop_filename, None)
                
        if len(labels) >= 2:
            try:
                recognizer = cv2.face.LBPHFaceRecognizer_create()
                recognizer.train(images, np.array(labels))
                recognizer.write(self.model_path)
                self.recognizer = recognizer
                print(f"[FaceMemory] Modello addestrato con successo. Classi: {len(np.unique(labels))-1}, Immagini: {len(labels)-1}")
            except Exception as e:
                print(f"[FaceMemory] Errore durante l'addestramento: {e}")
