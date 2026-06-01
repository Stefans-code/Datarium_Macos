import os
import sys
import json
import time
import random
import cv2
import numpy as np
from PIL import Image

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
        
        self.faces_dir = os.path.join(self.models_dir, "faces")
        self.crops_dir = os.path.join(self.faces_dir, "crops")
        
        # Crea le cartelle necessarie
        os.makedirs(self.crops_dir, exist_ok=True)
        
        self.metadata_path = os.path.join(self.faces_dir, "faces_metadata.json")
        self.model_path = os.path.join(self.faces_dir, "lbph_model.xml")
        
        self.metadata = self.load_metadata()
        self.recognizer = self.load_recognizer()
        
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

    def detect_faces(self, image_path_or_pil):
        """
        Rileva tutti i volti nell'immagine fornita.
        Ritorna: (lista_di_rettangoli_faccia, cv_image)
        """
        try:
            if isinstance(image_path_or_pil, str):
                # Utilizziamo imread con caratteri non-ascii gestiti correttamente tramite numpy
                img = cv2.imdecode(np.fromfile(image_path_or_pil, dtype=np.uint8), cv2.IMREAD_COLOR)
            else:
                # Da PIL a OpenCV BGR
                img = cv2.cvtColor(np.array(image_path_or_pil), cv2.COLOR_RGB2BGR)
                
            if img is None:
                return [], None
                
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Percorso del classificatore a cascata integrato in OpenCV
            cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if not os.path.exists(cascade_path):
                # Fallback standard
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                
            face_cascade = cv2.CascadeClassifier(cascade_path)
            # Parametri ottimali per minimizzare falsi positivi e rilevare anche facce piccole
            faces = face_cascade.detectMultiScale(
                gray, 
                scaleFactor=1.1, 
                minNeighbors=5, 
                minSize=(40, 40)
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
