import jwt
import os
import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone

class LicenseManager:
    # Deve corrispondere a license_maker.py
    LICENSE_SECRET = "vocius_offline_secure_key_2026_x99"
    ALGORITHM = "HS256"

    def __init__(self):
        self.license_path = self._get_license_directory()

    def _get_license_directory(self):
        """Individua una cartella scrivibile persistente per la licenza."""
        system = platform.system()
        try:
            if system == "Windows":
                # %LOCALAPPDATA%/Datarium
                base = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
                path = os.path.join(base, "Datarium")
            elif system == "Darwin": # macOS
                # ~/Library/Application Support/Datarium
                path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Datarium")
            else:
                path = os.path.join(os.path.expanduser("~"), ".datarium")
            
            os.makedirs(path, exist_ok=True)
            return os.path.join(path, "license.datarium")
        except:
            # Fallback alla cartella corrente se tutto fallisce
            return "license.datarium"

    @staticmethod
    def get_hwid():
        """Genera un HWID unico e fisso per il PC (Windows o macOS)."""
        system = platform.system()
        try:
            if system == "Windows":
                # 1. Metodo primario Windows: MachineGuid
                import winreg
                registry = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
                key = winreg.OpenKey(registry, r"SOFTWARE\Microsoft\Cryptography")
                machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                winreg.CloseKey(key)
                
                # 2. Metodo secondario: Seriale MB
                mb_serial = ""
                try:
                    cmd = "powershell -command \"(Get-CimInstance Win32_BaseBoard).SerialNumber\""
                    mb_serial = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
                except:
                    mb_serial = "STABLE-MB-ID"

                raw_id = f"{machine_guid}-{mb_serial}-DATARIUM-SECURE"
            
            elif system == "Darwin": # macOS
                # Seriale Hardware Apple
                cmd = "ioreg -l | grep IOPlatformSerialNumber"
                output = subprocess.check_output(cmd, shell=True).decode()
                # Parsing robuse della stringa ioreg
                serial = output.split('"')[-2] if '"' in output else "MACOS-FALLBACK"
                raw_id = f"{serial}-APPLE-DATARIUM-SECURE"
            
            else:
                raw_id = f"{platform.node()}-{platform.processor()}-GENERIC"

            return hashlib.sha256(raw_id.encode()).hexdigest()[:16].upper()
        except Exception:
            import uuid
            fallback_id = f"{uuid.getnode()}-{platform.node()}-SECURE-FALLBACK"
            return hashlib.sha256(fallback_id.encode()).hexdigest()[:16].upper()

    def verify_license(self, token=None):
        """Verifica se la licenza è valida per questo hardware."""
        if not token:
            if os.path.exists(self.license_path):
                try:
                    with open(self.license_path, "r") as f:
                        token = f.read().strip()
                except:
                    return False, "Errore lettura licenza"
            else:
                return False, "Licenza mancante"

        try:
            payload = jwt.decode(token, self.LICENSE_SECRET, algorithms=[self.ALGORITHM])
            
            # Controllo HWID
            current_hwid = self.get_hwid()
            if payload.get("hwid") != current_hwid:
                return False, f"Hardware ID mismatch (Local: {current_hwid})"
            
            # Controllo Scadenza
            exp = datetime.fromtimestamp(payload['exp'], tz=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return False, "Licenza scaduta"
                
            return True, f"Attiva (Scadenza: {exp.strftime('%d/%m/%Y')})"
        except jwt.ExpiredSignatureError:
            return False, "Licenza scaduta"
        except jwt.InvalidTokenError:
            return False, "Token non valido o corrotto"
        except Exception as e:
            return False, f"Verifica fallita: {str(e)}"

    def save_license(self, token):
        """Salva il token della licenza localmente in un percorso scrivibile."""
        try:
            with open(self.license_path, "w") as f:
                f.write(token)
            return True
        except Exception as e:
            print(f"Errore salvataggio licenza: {e}")
            return False
