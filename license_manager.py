import jwt
import os
import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone

class LicenseManager:
    # SECURITY: verifica RS256 con SOLO la chiave PUBBLICA (asimmetrica).
    # Prima si usava HS256 con un secret simmetrico hardcoded qui: siccome con HMAC la
    # stessa chiave firma E verifica, chiunque estraesse quella stringa dall'eseguibile
    # distribuito poteva firmarsi da solo licenze valide per qualsiasi HWID/scadenza,
    # bypassando completamente Stripe/Supabase. Con RS256 questa e' la chiave PUBBLICA:
    # puo' verificare una firma ma non puo' crearne una nuova, quindi e' sicura da
    # distribuire dentro il binario. La chiave PRIVATA che firma vive solo nei secrets
    # della Edge Function `sign-license` (mai su un pc cliente).
    LICENSE_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAz9Wiff+MVqgDalOKbonM
qmvjZgEQx3IaCyl0aBkZykNQVhvjpd+zS/pOPlP5cb8gqwpk72qW4MoUK/vErWgW
jEAaEDJ4S7kEhw39OwE9pY0EMB50WuLuJXKHDFZoOT8gn8nt4Q4z+LJuEd5LnF22
eS1+o7mVIuOSmThl5hfdZTk5cQiIoINMJnsGO3lIgkLqc6rdhgl6W67O4/vIDJg+
mcNC+Kw8Srh5GkJ6qORapRSXXnoN6HPoYR3EwJI4WAkGOagorVcKImseUIXaJ7FA
6FGqCIX6WI2cA8m4xlBgAJMG5qgsTb0Rqrc/jDPAoj0vKNWkEOuGoDICCjw+Gtxr
6wIDAQAB
-----END PUBLIC KEY-----"""
    ALGORITHM = "RS256"
    TRIAL_DAYS = 30

    def __init__(self):
        self.license_path = self._get_license_directory()

    def _is_trial_build(self):
        """Vero solo nella build di valutazione: presenza del file 'trial_mode.flag'
        accanto alle risorse dell'app (bundlato SOLO nel DMG/installer trial)."""
        try:
            base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            return os.path.exists(os.path.join(base, "trial_mode.flag"))
        except Exception:
            return False

    def _get_trial_marker_path(self):
        return os.path.join(os.path.dirname(self.license_path), "trial_start.dat")

    def check_trial(self):
        """Modalita' valutazione: TRIAL_DAYS giorni dal primo avvio, nessun HWID/licenza richiesti."""
        marker = self._get_trial_marker_path()
        now = datetime.now(timezone.utc)
        start = now
        if os.path.exists(marker):
            try:
                with open(marker, "r") as f:
                    start = datetime.fromisoformat(f.read().strip())
            except Exception:
                start = now
        else:
            try:
                with open(marker, "w") as f:
                    f.write(now.isoformat())
            except Exception:
                pass
        expiry = start + timedelta(days=self.TRIAL_DAYS)
        if now > expiry:
            return False, f"Periodo di valutazione di {self.TRIAL_DAYS} giorni terminato"
        return True, f"Valutazione (Scadenza: {expiry.strftime('%d/%m/%Y')})"

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
        except Exception:
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
                except Exception:
                    mb_serial = "STABLE-MB-ID"

                raw_id = f"{machine_guid}-{mb_serial}-DATARIUM-SECURE"
            
            elif system == "Darwin": # macOS
                # Seriale Hardware Apple (con query mirata e veloce)
                try:
                    cmd = "ioreg -rd1 -c IOPlatformExpertDevice"
                    output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5).decode()
                    serial = "MACOS-FALLBACK"
                    for line in output.splitlines():
                        if "IOPlatformSerialNumber" in line:
                            serial = line.split("=")[-1].replace('"', '').strip()
                            break
                except Exception:
                    serial = "MACOS-FALLBACK"
                raw_id = f"{serial}-APPLE-DATARIUM-SECURE"
            
            else:
                raw_id = f"{platform.node()}-{platform.processor()}-GENERIC"

            return hashlib.sha256(raw_id.encode()).hexdigest()[:16].upper()
        except Exception:
            import uuid
            fallback_id = f"{uuid.getnode()}-{platform.node()}-SECURE-FALLBACK"
            return hashlib.sha256(fallback_id.encode()).hexdigest()[:16].upper()

    def check_online_validation(self, hwid):
        """Verifica se l'HWID ha una licenza valida su Supabase.
        Restituisce True se ha una licenza attiva online.
        Restituisce False se la licenza è revocata o eliminata dal database.
        Restituisce None se non c'è connessione o se la funzione non esiste (offline fallback).
        """
        import urllib.request
        import json
        
        # 1. Tentativo tramite RPC (Remote Procedure Call) che bypassa l'RLS
        url_rpc = "https://xoowkjepvbokxmhsqmnm.supabase.co/rest/v1/rpc/check_license_validity"
        headers = {
            "apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhvb3dramVwdmJva3htaHNxbW5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY3NTI2NjUsImV4cCI6MjA5MjMyODY2NX0.2S_baIWot9ZkW7bsi16hy84O9Edf_XlBcQBmhXs3H1Y",
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhvb3dramVwdmJva3htaHNxbW5tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY3NTI2NjUsImV4cCI6MjA5MjMyODY2NX0.2S_baIWot9ZkW7bsi16hy84O9Edf_XlBcQBmhXs3H1Y",
            "Content-Type": "application/json"
        }
        try:
            req = urllib.request.Request(url_rpc, data=json.dumps({"p_hwid": hwid}).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=3) as response:
                result = json.loads(response.read().decode())
                if result is True:
                    return True
                elif result is False:
                    return False
        except Exception:
            pass

        # 2. Fallback tramite REST API classica (caso in cui l'RPC non sia stato creato)
        url_rest = f"https://xoowkjepvbokxmhsqmnm.supabase.co/rest/v1/licenses?hwid=eq.{hwid}"
        headers_rest = {
            "apikey": headers["apikey"],
            "Authorization": headers["Authorization"]
        }
        try:
            req = urllib.request.Request(url_rest, headers=headers_rest)
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode())
                if isinstance(data, list):
                    if any(item.get("status") == "active" for item in data):
                        return True
                    if any(item.get("status") == "revoked" for item in data):
                        return False
        except Exception:
            pass
        return None

    def verify_license(self, token=None):
        """Verifica se la licenza è valida per questo hardware."""
        current_hwid = self.get_hwid()
        online_valid = self.check_online_validation(current_hwid)
        if online_valid is False:
            if os.path.exists(self.license_path):
                try: os.remove(self.license_path)
                except Exception: pass
            return False, "Licenza revocata o terminata (Database validation failed)"

        if not token:
            if os.path.exists(self.license_path):
                try:
                    with open(self.license_path, "r") as f:
                        token = f.read().strip()
                except Exception:
                    return False, "Errore lettura licenza"
            else:
                if self._is_trial_build():
                    return self.check_trial()
                return False, "Licenza mancante"

        try:
            payload = jwt.decode(token, self.LICENSE_PUBLIC_KEY, algorithms=[self.ALGORITHM])
            
            # Controllo HWID
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
