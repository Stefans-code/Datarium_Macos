import os
import platform
import sys
import datetime
import multiprocessing

class ReportGenerator:
    @staticmethod
    def get_hardware_specs():
        """Ottiene le specifiche hardware del PC corrente."""
        system = platform.system()
        os_ver = f"{platform.system()} {platform.release()}"
        if system == "Darwin":
            os_ver = f"macOS {platform.mac_ver()[0]}"
        elif system == "Windows":
            os_ver = f"Windows {platform.win32_ver()[0]}"
            
        processors = multiprocessing.cpu_count()
        # Calcolo RAM approssimato
        ram_gb = 16
        try:
            if system == "Windows":
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                ram_gb = int(stat.ullTotalPhys / (1024 ** 3))
            elif system == "Darwin":
                import subprocess
                cmd = "sysctl hw.memsize"
                mem = subprocess.check_output(cmd, shell=True).decode().strip()
                ram_gb = int(mem.split(":")[-1].strip()) // (1024 ** 3)
        except Exception:
            pass
            
        return {
            "os": os_ver,
            "processors": processors,
            "ram": f"{ram_gb} GB RAM"
        }

    @classmethod
    def generate_html_report(cls, report_id, source_dir, files_list, algo, dest_dirs):
        """Genera un report HTML in stile ShotPut Pro ad alta fedeltà."""
        specs = cls.get_hardware_specs()
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%B %d, %Y at %I:%M:%S %p")
        
        # Calcolo statistiche complessive
        total_files = len(files_list)
        total_size_bytes = sum(f.get("size_bytes", 0) for f in files_list)
        
        # Formattazione dimensione totale
        if total_size_bytes < 1024 * 1024:
            total_size_str = f"{total_size_bytes / 1024:.2f} KB"
        elif total_size_bytes < 1024 * 1024 * 1024:
            total_size_str = f"{total_size_bytes / (1024 * 1024):.2f} MB"
        else:
            total_size_str = f"{total_size_bytes / (1024 * 1024 * 1024):.2f} GB"
            
        total_folders = len(set(os.path.dirname(f["path"]) for f in files_list))
        
        # Status complessivo (tutti verificati o meno)
        overall_status = "Verified"
        if any(f.get("status") == "Failed" for f in files_list):
            overall_status = "Failed"
            
        status_color = "#10b981" if overall_status == "Verified" else "#ef4444"
        status_bg = "rgba(16, 185, 129, 0.2)" if overall_status == "Verified" else "rgba(239, 68, 68, 0.2)"

        # Generazione righe della tabella
        rows_html = ""
        for it in files_list:
            preview_elem = ""
            ext = os.path.splitext(it["name"])[1].lower()
            
            # Icona o anteprima a seconda del tipo
            if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
                # Se è immagine, proviamo a usare il path assoluto per caricarla nel browser
                preview_elem = f'<img class="preview-img" src="file:///{it["path"].replace(chr(92), "/")}" alt="{it["name"]}"/>'
            elif ext in [".mp4", ".mov", ".mxf", ".avi", ".mkv"]:
                # Estrae piu' frame video in base64 per mostrare una strip nel report HTML
                thumbs = cls.extract_video_thumbnails(it["path"])
                if thumbs:
                    import base64
                    imgs = "".join(
                        f'<img class="preview-thumb" src="data:image/jpeg;base64,{base64.b64encode(t).decode("ascii")}" alt="Video Frame {i+1}"/>'
                        for i, t in enumerate(thumbs)
                    )
                    preview_elem = f'<div class="preview-strip">{imgs}</div>'
                else:
                    preview_elem = '<div class="preview-placeholder">🎞️</div>'
            else:
                preview_elem = '<div class="preview-placeholder">🎞️</div>'
                
            # Date
            created_str = it.get("created", "unknown")
            modified_str = it.get("modified", "unknown")
            
            # Hashing info
            hash_label = "xxHash 64:" if algo == "xxHash64" else "SHA-256:"
            hash_label_2 = "SHA-256:" if algo == "xxHash64" else "MD5:"
            hash_val = it.get("hash", "N/A")
            hash_val_2 = it.get("hash_alt", "N/A")

            # Media details
            media_format = it.get("media_format", "Unknown")
            codec = it.get("codec", "N/A")
            duration = it.get("duration", "N/A")
            resolution = it.get("resolution", "N/A")
            camera = it.get("camera", "N/A")
            shot = it.get("shot", "N/A")
            frames = it.get("frames", "N/A")
            bitrate = it.get("bitrate", "N/A")
            audio = it.get("audio", "N/A")

            rows_html += f"""
            <tr>
                <td>
                    {preview_elem}
                    <div class="filename">{it["name"]}</div>
                </td>
                <td>
                    <div class="meta-label">File Size:</div>
                    <div class="meta-val">{it["size_str"]}</div>
                    <div class="meta-label">Date Created:</div>
                    <div class="meta-val-date">{created_str}</div>
                    <div class="meta-label">Date Modified:</div>
                    <div class="meta-val-date">{modified_str}</div>
                </td>
                <td>
                    <div class="meta-label">{hash_label}</div>
                    <div class="hash-val">{hash_val}</div>
                    <div class="meta-label">{hash_label_2}</div>
                    <div class="hash-val">{hash_val_2}</div>
                </td>
                <td>
                    <div class="meta-label">Media Format:</div>
                    <div class="meta-val">{media_format}</div>
                    <div class="meta-label">Codec:</div>
                    <div class="meta-val">{codec}</div>
                    <div class="meta-label">Video Duration:</div>
                    <div class="meta-val">{duration}</div>
                    <div class="meta-label">Video Resolution:</div>
                    <div class="meta-val">{resolution}</div>
                </td>
                <td><div class="meta-val">{camera}</div></td>
                <td><div class="meta-val">{shot}</div></td>
                <td>
                    <div class="meta-label">Total Frames:</div>
                    <div class="meta-val">{frames}</div>
                    <div class="meta-label">Video Bit Rate:</div>
                    <div class="meta-val">{bitrate}</div>
                </td>
                <td>
                    <div class="meta-val-small">{audio}</div>
                </td>
            </tr>
            """

        dests_html = "".join(f"<li>{d}</li>" for d in dest_dirs)

        html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>MHL Verification Report - {report_id}</title>
    <style>
        body {{
            background-color: #1a1a1a;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            font-size: 13px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: #242424;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #3a3a3a;
            padding-bottom: 25px;
            margin-bottom: 25px;
        }}
        .header-left {{
            display: flex;
            align-items: center;
            gap: 20px;
        }}
        .badge {{
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background-color: {status_color};
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            box-shadow: 0 0 15px {status_color}80;
        }}
        .title-section h1 {{
            margin: 0;
            font-size: 26px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}
        .title-section .subtitle {{
            color: #888;
            font-size: 12px;
            margin-top: 4px;
        }}
        .top-stats {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            background-color: #1e1e1e;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border: 1px solid #333;
        }}
        .stat-col {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .stat-row {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
        }}
        .stat-label {{
            color: #888;
        }}
        .stat-val {{
            font-weight: bold;
            color: #fff;
        }}
        .stat-val.verified {{
            color: #10b981;
            background-color: rgba(16,185,129,0.15);
            padding: 1px 8px;
            border-radius: 4px;
        }}
        .stat-val.failed {{
            color: #ef4444;
            background-color: rgba(239,68,68,0.15);
            padding: 1px 8px;
            border-radius: 4px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th {{
            background-color: #1e1e1e;
            color: #888;
            font-weight: 600;
            text-align: left;
            padding: 12px 10px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #3a3a3a;
        }}
        td {{
            padding: 15px 10px;
            border-bottom: 1px solid #2e2e2e;
            vertical-align: top;
        }}
        tr:hover {{
            background-color: #2a2a2a;
        }}
        .preview-img {{
            width: 120px;
            height: 80px;
            object-fit: cover;
            border-radius: 4px;
            border: 1px solid #444;
            background-color: #000;
            display: block;
            margin-bottom: 6px;
        }}
        .preview-strip {{
            display: flex;
            flex-wrap: wrap;
            gap: 3px;
            width: 120px;
            margin-bottom: 6px;
        }}
        .preview-thumb {{
            width: 37px;
            height: 25px;
            object-fit: cover;
            border-radius: 3px;
            border: 1px solid #444;
            background-color: #000;
        }}
        .preview-placeholder {{
            width: 120px;
            height: 80px;
            border-radius: 4px;
            border: 1px solid #444;
            background-color: #1a1a1a;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            margin-bottom: 6px;
        }}
        .filename {{
            font-weight: 600;
            color: #fff;
            word-break: break-all;
            max-width: 150px;
            font-size: 12px;
        }}
        .meta-label {{
            font-size: 10px;
            color: #888;
            margin-top: 6px;
            text-transform: uppercase;
        }}
        .meta-val {{
            font-weight: 500;
            color: #fff;
            margin-top: 1px;
        }}
        .meta-val-date {{
            font-size: 11px;
            color: #bbb;
            margin-top: 1px;
        }}
        .meta-val-small {{
            font-size: 10px;
            color: #aaa;
            line-height: 1.4;
            white-space: pre-line;
        }}
        .hash-val {{
            font-family: monospace;
            font-size: 11px;
            color: #a7f3d0;
            background-color: rgba(16,185,129,0.08);
            padding: 4px 6px;
            border-radius: 4px;
            word-break: break-all;
            margin-top: 2px;
            border: 1px dashed rgba(16,185,129,0.2);
        }}
        .actions {{
            display: flex;
            justify-content: flex-end;
            gap: 15px;
            margin-top: 30px;
        }}
        .btn {{
            background-color: #10b981;
            color: #fff;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }}
        .btn:hover {{
            background-color: #059669;
            transform: translateY(-1px);
        }}
        .btn-outline {{
            background-color: transparent;
            border: 1px solid #444;
            color: #ccc;
        }}
        .btn-outline:hover {{
            background-color: #333;
            color: #fff;
        }}
        .dests-list {{
            margin: 0;
            padding-left: 20px;
            color: #bbb;
            font-size: 11px;
        }}
        @media print {{
            body {{
                background-color: #fff;
                color: #000;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
                padding: 0;
                background-color: #fff;
            }}
            .top-stats {{
                background-color: #f5f5f5;
                border: 1px solid #ccc;
            }}
            .stat-val {{
                color: #000;
            }}
            th {{
                background-color: #f5f5f5;
                color: #333;
                border-bottom: 1px solid #ccc;
            }}
            td {{
                border-bottom: 1px solid #ddd;
            }}
            .hash-val {{
                color: #000;
                background-color: #f0f0f0;
                border: 1px solid #ccc;
            }}
            .filename, .meta-val {{
                color: #000;
            }}
            .actions {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-left">
                <div class="badge">✓</div>
                <div class="title-section">
                    <h1>{report_id}</h1>
                    <div class="subtitle">{timestamp_str}</div>
                </div>
            </div>
            <div>
                <button class="btn btn-outline" onclick="window.print()">🖨️ Stampa / Salva come PDF</button>
            </div>
        </div>

        <div class="top-stats">
            <div class="stat-col">
                <div class="stat-row">
                    <span class="stat-label">Status:</span>
                    <span class="stat-val {overall_status.lower()}">{overall_status}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total Files:</span>
                    <span class="stat-val">{total_files}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total Size:</span>
                    <span class="stat-val">{total_size_str}</span>
                </div>
            </div>
            <div class="stat-col">
                <div class="stat-row">
                    <span class="stat-label">Total Folders:</span>
                    <span class="stat-val">{total_folders}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">macOS / OS:</span>
                    <span class="stat-val">{specs["os"]}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Specs:</span>
                    <span class="stat-val">{specs["processors"]} CPUs, {specs["ram"]}</span>
                </div>
            </div>
            <div class="stat-col" style="grid-column: span 2;">
                <div class="stat-row" style="flex-direction: column; align-items: flex-start; gap: 4px;">
                    <span class="stat-label">Verification:</span>
                    <span class="stat-val" style="color: #60a5fa;">Full Checksum ({algo})</span>
                </div>
                <div class="stat-row" style="flex-direction: column; align-items: flex-start; gap: 4px; margin-top: 6px;">
                    <span class="stat-label">Destinations Backed Up:</span>
                    <ul class="dests-list">
                        {dests_html}
                    </ul>
                </div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th style="width: 20%;">Preview</th>
                    <th style="width: 15%;">File Info</th>
                    <th style="width: 25%;">Checksum</th>
                    <th style="width: 15%;">Media</th>
                    <th style="width: 8%;">Camera</th>
                    <th style="width: 5%;">Shot</th>
                    <th style="width: 8%;">Video</th>
                    <th style="width: 4%;">Audio</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="actions">
            <button class="btn" onclick="window.print()">📥 Esporta Report PDF</button>
        </div>
    </div>
</body>
</html>
"""
        return html_content

    @staticmethod
    def safe_text(text):
        if not isinstance(text, str):
            text = str(text)
        # Sostituisci caratteri Unicode comuni con equivalenti ASCII prima della conversione
        replacements = {
            '\u2022': '-',  # bullet •
            '\u2013': '-',  # en dash
            '\u2014': '-',  # em dash
            '\u2018': "'",  # left single quote
            '\u2019': "'",  # right single quote
            '\u201c': '"',  # left double quote
            '\u201d': '"',  # right double quote
            '\u2026': '...', # ellipsis
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        # Rimuove emoji e caratteri non supportati da latin1 per evitare i fastidiosi "??" nel PDF
        clean_bytes = text.encode('latin1', errors='ignore')
        return clean_bytes.decode('latin1')

    @staticmethod
    def extract_video_thumbnails(video_path, num_thumbnails=5):
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return []
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                return []
            step = max(1, total_frames // (num_thumbnails + 1))
            thumbnails = []
            for i in range(1, num_thumbnails + 1):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
                ret, frame = cap.read()
                if ret:
                    h, w = frame.shape[:2]
                    new_w = 85
                    new_h = int(new_w * (h / w))
                    frame_resized = cv2.resize(frame, (new_w, new_h))
                    ret2, buffer = cv2.imencode('.jpg', frame_resized)
                    if ret2:
                        thumbnails.append(buffer.tobytes())
            cap.release()
            return thumbnails
        except Exception as e:
            return []

    @staticmethod
    def _resolve_ffprobe(ffmpeg_path):
        """Deriva il percorso di ffprobe da quello di ffmpeg (di norma nella stessa cartella
        della stessa distribuzione), con ripiego sul PATH di sistema. Nessuna esecuzione qui:
        se il file non esiste il chiamante ricade su cv2 senza errori."""
        import shutil
        candidates = []
        if ffmpeg_path:
            base_dir = os.path.dirname(ffmpeg_path)
            name = "ffprobe.exe" if ffmpeg_path.lower().endswith(".exe") else "ffprobe"
            candidates.append(os.path.join(base_dir, name))
        which_probe = shutil.which("ffprobe")
        if which_probe:
            candidates.append(which_probe)
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None

    @staticmethod
    def _ffprobe_media_info(file_path, ffprobe_path):
        """
        Interroga ffprobe in JSON per un set di metadati molto più ampio di quanto
        cv2.VideoCapture riesca a leggere: contenitori professionali (MXF, ProRes, BRAW
        con IDT) e soprattutto il TIMECODE incorporato, che cv2 non espone mai.

        Ritorna None se ffprobe non apre il file: e' il caso, tra gli altri, dei RAW
        proprietari delle cineprese (es. RED .R3D) per cui NON esiste un demuxer libero
        ne' in ffmpeg ne' altrove — solo l'SDK proprietario RED (a licenza, non incluso
        in Datarium) sa leggerli. In quel caso resta 'N/A': onesto, non un dato inventato.
        """
        import subprocess
        import json
        try:
            res = subprocess.run(
                [ffprobe_path, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20
            )
            if res.returncode != 0 or not res.stdout:
                return None
            data = json.loads(res.stdout)
        except Exception:
            return None

        fmt = data.get("format", {}) or {}
        streams = data.get("streams", []) or []
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if not v_stream and not a_stream:
            return None  # ffprobe ha "aperto" il file ma non ci ha trovato media utilizzabile

        info = {
            "media_format": "Video" if v_stream else "Audio",
            "codec": "N/A", "duration": "N/A", "resolution": "N/A",
            "camera": "N/A", "shot": "N/A", "frames": "N/A",
            "bitrate": "N/A", "audio": "N/A", "timecode": "N/A",
        }

        duration_s = None
        for src in (fmt, v_stream or {}):
            d = src.get("duration")
            if d:
                try:
                    duration_s = float(d)
                    break
                except (TypeError, ValueError):
                    pass
        if duration_s:
            h = int(duration_s // 3600)
            m = int((duration_s % 3600) // 60)
            s = int(duration_s % 60)
            info["duration"] = f"{h}:{m:02d}:{s:02d}"

        if v_stream:
            w, h_px = v_stream.get("width"), v_stream.get("height")
            if w and h_px:
                info["resolution"] = f"{w} x {h_px}"
            if v_stream.get("codec_name"):
                info["codec"] = v_stream["codec_name"].upper()

            nb_frames = v_stream.get("nb_frames")
            if nb_frames and str(nb_frames).isdigit():
                info["frames"] = nb_frames
            elif duration_s:
                try:
                    num, den = v_stream.get("r_frame_rate", "0/1").split("/")
                    fps = float(num) / float(den) if float(den) else 0
                    if fps:
                        info["frames"] = str(int(duration_s * fps))
                except Exception:
                    pass

            tc = (v_stream.get("tags") or {}).get("timecode")
            if tc:
                info["timecode"] = tc

        if info["timecode"] == "N/A":
            tc = (fmt.get("tags") or {}).get("timecode")
            if tc:
                info["timecode"] = tc

        if a_stream and a_stream.get("codec_name"):
            info["audio"] = a_stream["codec_name"].upper()

        try:
            bit_rate = fmt.get("bit_rate") or (v_stream or {}).get("bit_rate")
            if bit_rate:
                info["bitrate"] = f"{int(bit_rate) / 1_000_000:.1f} Mb/s"
        except Exception:
            pass

        tags = fmt.get("tags") or {}
        make = tags.get("com.apple.quicktime.make") or tags.get("make") or ""
        model = tags.get("com.apple.quicktime.model") or tags.get("model") or ""
        camera = (make + " " + model).strip()
        if camera:
            info["camera"] = camera

        return info

    @staticmethod
    def extract_media_info(file_path, ffmpeg_path=None):
        """Estrae metadati REALI (risoluzione, durata, codec, bitrate, camera, timecode) da
        video e immagini. Ritorna sempre un dizionario; i campi non disponibili valgono
        'N/A' (mai dati fittizi).

        Per i video prova prima ffprobe (se ffmpeg e' configurato in Impostazioni): copre
        molti piu' contenitori di cv2 e soprattutto legge il timecode incorporato, che cv2
        non espone. cv2 resta il fallback quando ffmpeg non e' configurato o il formato non
        e' apribile nemmeno da ffprobe (es. RED .R3D, vedi _ffprobe_media_info)."""
        ext = os.path.splitext(file_path)[1].lower()
        video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v',
                      '.mpg', '.mpeg', '.m2ts', '.mts', '.braw', '.r3d', '.mxf', '.crm']
        image_exts = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif', '.gif',
                      '.heic', '.heif', '.nef', '.cr2', '.cr3', '.arw', '.dng', '.raf', '.rw2', '.orf']

        info = {
            "media_format": "Data",
            "codec": "N/A",
            "duration": "N/A",
            "resolution": "N/A",
            "camera": "N/A",
            "shot": "N/A",
            "frames": "N/A",
            "bitrate": "N/A",
            "audio": "N/A",
            "timecode": "N/A",
        }

        try:
            if ext in video_exts:
                ffprobe_path = ReportGenerator._resolve_ffprobe(ffmpeg_path)
                probed = ReportGenerator._ffprobe_media_info(file_path, ffprobe_path) if ffprobe_path else None
                if probed:
                    return probed

                info["media_format"] = "Video"
                import cv2
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS) or 0
                    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

                    if width and height:
                        info["resolution"] = f"{width} x {height}"
                    if frame_count > 0:
                        info["frames"] = str(frame_count)
                    if fps and frame_count > 0:
                        total_seconds = frame_count / fps
                        h = int(total_seconds // 3600)
                        m = int((total_seconds % 3600) // 60)
                        s = int(total_seconds % 60)
                        info["duration"] = f"{h}:{m:02d}:{s:02d}"
                        try:
                            size_bytes = os.path.getsize(file_path)
                            mbps = (size_bytes / (1024 * 1024)) / total_seconds
                            info["bitrate"] = f"{mbps:.1f} MB/s"
                        except Exception:
                            pass

                    # Codec a partire dal codice FOURCC
                    try:
                        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
                        if fourcc_int:
                            codec = "".join(chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4))
                            codec = "".join(c for c in codec if c.isprintable()).strip()
                            if codec:
                                info["codec"] = codec
                    except Exception:
                        pass
                cap.release()

            elif ext in image_exts:
                info["media_format"] = "Image"
                try:
                    from PIL import Image, ExifTags
                    img = Image.open(file_path)
                    info["resolution"] = f"{img.width} x {img.height}"
                    info["codec"] = img.format or ext.replace('.', '').upper()
                    exif = getattr(img, "_getexif", lambda: None)()
                    if exif:
                        make = model = ""
                        for tag, value in exif.items():
                            decoded = ExifTags.TAGS.get(tag, tag)
                            if decoded == "Make":
                                make = str(value).strip()
                            elif decoded == "Model":
                                model = str(value).strip()
                        camera = (make + " " + model).strip()
                        if camera:
                            info["camera"] = camera
                except Exception:
                    pass
        except Exception:
            pass

        return info

    @classmethod
    def save_report(cls, output_dir, report_id, source_dir, files_list, algo, dest_dirs, production_meta=None, timing=None):
        """Genera e salva un vero e proprio file PDF di verifica Offload usando PyMuPDF.
        production_meta: dizionario opzionale {etichetta: valore} di metadati produzione (stile Silverstack).
        timing: dizionario opzionale {"start": datetime, "finish": datetime, "elapsed_str": str} con la
        durata del job, cosi' il report mostra quando e' iniziato/finito l'Offload (non solo quando e'
        stato generato il PDF)."""
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"{report_id}_MHL_Report.pdf")
        
        import fitz
        doc = fitz.open()
        
        # Stile e Font
        font_name = "helvetica"
        
        # Pagina singola o multipla (LANDSCAPE)
        page_width = 842
        page_height = 595
        page = doc.new_page(width=page_width, height=page_height)
        
        # Disegna Intestazione
        page.draw_rect(fitz.Rect(0, 0, page_width, 80), color=None, fill=(0.1, 0.1, 0.1)) # Grigio scuro
        page.insert_textbox(fitz.Rect(20, 15, 600, 70), "DATARIUM - MHL VERIFICATION REPORT", fontsize=16, fontname=f"{font_name}-bold", color=(1, 1, 1))
        page.insert_textbox(fitz.Rect(20, 45, 600, 75), f"ID: {report_id}  |  Generato il: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", fontsize=9, fontname=font_name, color=(0.8, 0.8, 0.8))
        
        # Badge di stato
        overall_status = "VERIFIED"
        if any(f.get("status") == "Failed" for f in files_list):
            overall_status = "FAILED"
            
        status_color = (0.06, 0.72, 0.5) if overall_status == "VERIFIED" else (0.93, 0.26, 0.26)
        page.draw_rect(fitz.Rect(page_width - 150, 20, page_width - 20, 60), color=None, fill=status_color, width=0, radius=0.25)
        page.insert_textbox(fitz.Rect(page_width - 150, 28, page_width - 20, 55), overall_status, fontsize=12, fontname=f"{font_name}-bold", color=(1, 1, 1), align=1)
        
        # Specifiche Hardware e Dettagli
        specs = cls.get_hardware_specs()
        page.insert_textbox(fitz.Rect(20, 100, 280, 200), 
                             cls.safe_text(f"Specifiche PC:\n- OS: {specs['os']}\n- CPU/RAM: {specs['processors']} CPUs, {specs['ram']}"), 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        # Calcolo statistiche
        total_size_bytes = sum(f.get("size_bytes", 0) for f in files_list)
        if total_size_bytes < 1024 * 1024:
            total_size_str = f"{total_size_bytes / 1024:.2f} KB"
        elif total_size_bytes < 1024 * 1024 * 1024:
            total_size_str = f"{total_size_bytes / (1024 * 1024):.2f} MB"
        else:
            total_size_str = f"{total_size_bytes / (1024 * 1024 * 1024):.2f} GB"
            
        dests_str = "\n".join(f"  - {d}" for d in dest_dirs)
        video_count = sum(1 for f in files_list if f.get("media_format") == "Video")
        timing_lines = ""
        if timing:
            start_str = timing.get("start").strftime("%d/%m/%Y %H:%M:%S") if timing.get("start") else "N/D"
            finish_str = timing.get("finish").strftime("%d/%m/%Y %H:%M:%S") if timing.get("finish") else "N/D"
            elapsed_str = timing.get("elapsed_str", "N/D")
            timing_lines = f"\n- Inizio: {start_str}\n- Fine: {finish_str}\n- Durata: {elapsed_str}"
        page.insert_textbox(fitz.Rect(300, 100, page_width - 20, 244),
                             cls.safe_text(f"Riepilogo Offload:\n- File Totali: {len(files_list)}\n- File Video: {video_count}\n- Dimensione Totale: {total_size_str}\n- Algoritmo: {algo}{timing_lines}\n- Destinazioni:\n{dests_str}"),
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))

        # Sezione Metadati Produzione (stile Silverstack), se forniti
        y = 254
        if production_meta:
            page.draw_rect(fitz.Rect(20, y, page_width - 20, y + 18), color=None, fill=(0.85, 0.87, 0.92))
            page.insert_text((25, y + 13), "METADATI PRODUZIONE", fontsize=10, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
            y += 24
            meta_pairs = [(k, v) for k, v in production_meta.items() if k != "Note"]
            meta_str = "    ".join(f"{k}: {v}" for k, v in meta_pairs)
            if meta_str:
                page.insert_textbox(fitz.Rect(25, y, page_width - 25, y + 45),
                                    cls.safe_text(meta_str), fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
                y += 48
            note_val = production_meta.get("Note")
            if note_val:
                page.insert_textbox(fitz.Rect(25, y, page_width - 25, y + 40),
                                    cls.safe_text(f"Note: {note_val}"), fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
                y += 42
            y += 8

        # Tabella dei File
        for f in files_list:
            if y > page_height - 100:
                page = doc.new_page(width=page_width, height=page_height)
                y = 40
            
            # File Header (grigio chiaro)
            page.draw_rect(fitz.Rect(20, y, page_width - 20, y+20), color=None, fill=(0.92, 0.93, 0.95))
            name_disp = f["name"]
            page.insert_text((25, y+14), cls.safe_text(name_disp), fontsize=10, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
            
            thumb_start_y = y + 25
            y += 25
            
            # Metadata rows (sulla sinistra)
            size_txt = f.get("size_str", "N/A")
            created_txt = f.get("created", "N/A")
            modified_txt = f.get("modified", "N/A")
            hash_algo = "xxHash 64" if algo == "xxHash64" else algo
            hash_val = f.get("hash", "N/A")

            page.insert_text((25, y+10), cls.safe_text(f"Size: {size_txt}   Created: {created_txt}   Modified: {modified_txt}"), fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            y += 15
            
            media_fmt = f.get("media_format", "Unknown")
            codec = f.get("codec", "N/A")
            resolution = f.get("resolution", "N/A")
            duration = f.get("duration", "N/A")
            frames = f.get("frames", "N/A")
            timecode = f.get("timecode", "N/A")

            if media_fmt == "Video":
                page.insert_text((25, y+10), cls.safe_text(f"Video: {resolution} {codec} | Dur: {duration} | Frames: {frames} | TC: {timecode}"), fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            else:
                page.insert_text((25, y+10), cls.safe_text(f"Type: {media_fmt}"), fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            y += 15
            
            page.insert_text((25, y+10), cls.safe_text(f"{hash_algo}: {hash_val}"), fontsize=8, fontname=font_name, color=(0.4, 0.4, 0.4))
            y += 15

            # Stato per-SINGOLA destinazione (stile ShotPut Pro: "Destination N: ... Status: Verified"),
            # non solo un esito complessivo per il file: utile quando una copia su 3 destinazioni fallisce
            # solo su una e le altre due sono comunque valide.
            dest_status = f.get("dest_status")
            if dest_status:
                for i, (d, st) in enumerate(dest_status.items(), 1):
                    st_color = (0.06, 0.6, 0.4) if st == "Verified" else (0.8, 0.2, 0.2)
                    page.insert_text((25, y + 10), cls.safe_text(f"Destination {i}: {d}  —  Status: {st}"), fontsize=7.5, fontname=font_name, color=st_color)
                    y += 12
            
            # Thumbnails row (sulla destra)
            max_y_for_entry = y
            if media_fmt == "Video":
                thumbs = cls.extract_video_thumbnails(f["path"])
                thumb_w = 85
                thumb_h = 48
                for i, t in enumerate(thumbs):
                    thumb_x = 280 + i * (thumb_w + 5)
                    rect = fitz.Rect(thumb_x, thumb_start_y, thumb_x + thumb_w, thumb_start_y + thumb_h)
                    page.insert_image(rect, stream=t)
                max_y_for_entry = max(y, thumb_start_y + thumb_h + 10)
            elif media_fmt == "Image":
                try:
                    import io
                    from PIL import Image
                    img = Image.open(f["path"])
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.thumbnail((120, 85))
                    bio = io.BytesIO()
                    img.save(bio, format="JPEG")
                    # Calcola altezza proporzionale (max 85)
                    tw, th = img.size
                    rect = fitz.Rect(280, thumb_start_y, 280 + tw, thumb_start_y + th)
                    page.insert_image(rect, stream=bio.getvalue())
                    max_y_for_entry = max(y, thumb_start_y + th + 10)
                except Exception as e:
                    print(f"Error thumbnail PDF: {e}")
            
            y = max_y_for_entry + 15
            
        try:
            doc.save(report_path)
        except Exception:
            import time
            report_path = os.path.join(output_dir, f"{report_id}_{int(time.time())}_MHL_Report.pdf")
            doc.save(report_path)
        doc.close()
        return report_path

    # Nomi dei tag XML per ciascun algoritmo, secondo la convenzione dello standard
    # ASC MHL (usato da Silverstack/YoYotta/Pomfort Offload Manager): un tool che
    # legge un file .mhl cerca uno di questi tag per riga, non un campo generico
    # "hash". Necessario per l'interoperabilita' reale con quei tool, non solo per
    # un file "che si chiama mhl" ma dal contenuto arbitrario.
    _MHL_TAGS = {"MD5": "md5", "SHA-1": "sha1", "SHA-256": "sha256", "xxHash64": "xxhash64"}

    @classmethod
    def save_mhl_files(cls, dest_dirs, report_id, files_list, algo, creator_tool="Datarium"):
        """Scrive un file .mhl (XML, standard ASC MediaHashList v1) alla RADICE di ogni
        destinazione, cosi' un altro tool DIT (Silverstack, YoYotta, Pomfort) che scansiona
        quella cartella lo trova e lo legge automaticamente, senza bisogno di aprire Datarium.

        Prima Datarium generava solo un PDF chiamato "..._MHL_Report.pdf": il nome richiamava
        lo standard MHL ma il contenuto non era un file .mhl valido, quindi non interoperabile.

        Un file .mhl per destinazione (non uno globale) perche' i path devono essere relativi
        alla radice DI QUELLA destinazione: e' cosi' che i tool DIT si aspettano di trovarlo.

        Ritorna la lista dei path .mhl scritti (uno per destinazione, quelli riusciti)."""
        import xml.etree.ElementTree as ET
        import datetime as _dt

        hash_tag = cls._MHL_TAGS.get(algo, algo.lower().replace("-", ""))
        written = []
        for dest_dir in dest_dirs:
            try:
                root = ET.Element("hashlist", version="1.1")
                creator = ET.SubElement(root, "creatorinfo")
                ET.SubElement(creator, "name").text = report_id
                ET.SubElement(creator, "hostname").text = platform.node()
                ET.SubElement(creator, "tool").text = creator_tool
                ET.SubElement(creator, "startdate").text = _dt.datetime.now().isoformat()

                for f in files_list:
                    if f.get("status") != "Verified" or not f.get("hash") or f.get("hash") == "ERROR":
                        continue
                    rel = f.get("rel") or f.get("name")
                    entry = ET.SubElement(root, "hash")
                    ET.SubElement(entry, "file").text = rel.replace(os.sep, "/")
                    ET.SubElement(entry, "size").text = str(f.get("size_bytes", 0))
                    if f.get("modified"):
                        ET.SubElement(entry, "lastmodificationdate").text = f["modified"]
                    ET.SubElement(entry, hash_tag).text = f["hash"]

                tree = ET.ElementTree(root)
                ET.indent(tree, space="  ")
                mhl_path = os.path.join(dest_dir, f"{report_id}.mhl")
                tree.write(mhl_path, encoding="utf-8", xml_declaration=True)
                written.append(mhl_path)
            except Exception as e:
                print(f"Errore generazione .mhl per {dest_dir}: {e}")
        return written

    @classmethod
    def save_txt_report(cls, output_dir, report_id, files_list, algo, dest_dirs, timing=None):
        """Esporta un report testuale semplice (stile ShotPut Pro), alternativa leggibile
        senza visualizzatore PDF: utile per script/automazioni o semplice archiviazione."""
        os.makedirs(output_dir, exist_ok=True)
        txt_path = os.path.join(output_dir, f"{report_id}_Report.txt")
        total_size_bytes = sum(f.get("size_bytes", 0) for f in files_list)
        video_count = sum(1 for f in files_list if f.get("media_format") == "Video")
        failed = [f for f in files_list if f.get("status") != "Verified"]
        lines = [
            f"DATARIUM - OFFLOAD REPORT",
            f"ID: {report_id}",
            f"Generato il: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            f"Stato: {'FAILED' if failed else 'VERIFIED'}",
            f"Algoritmo: {algo}",
            f"File totali: {len(files_list)} (di cui {video_count} video)",
            f"Dimensione totale: {total_size_bytes} bytes",
        ]
        if timing:
            lines.append(f"Inizio: {timing.get('start')}  Fine: {timing.get('finish')}  Durata: {timing.get('elapsed_str', 'N/D')}")
        lines.append("Destinazioni: " + ", ".join(dest_dirs))
        lines.append("-" * 70)
        for f in files_list:
            lines.append(
                f"{f.get('name')}\tsize={f.get('size_str', 'N/A')}\tstatus={f.get('status')}\t"
                f"created={f.get('created', 'N/A')}\tmodified={f.get('modified', 'N/A')}\t"
                f"{algo}={f.get('hash', 'N/A')}"
            )
            for i, (d, st) in enumerate(f.get("dest_status", {}).items(), 1):
                lines.append(f"    Destination {i}: {d} -> {st}")
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return txt_path

    @classmethod
    def save_csv_report(cls, output_dir, report_id, files_list, algo):
        """Esporta un report CSV (una riga per file), pensato per essere importato in fogli
        di calcolo o altri strumenti di produzione, non solo letto a schermo."""
        import csv
        os.makedirs(output_dir, exist_ok=True)
        csv_path = os.path.join(output_dir, f"{report_id}_Report.csv")
        fieldnames = ["name", "rel", "size_bytes", "status", "created", "modified", "algorithm", "hash", "media_format", "destinations"]
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for f in files_list:
                dest_status = f.get("dest_status", {})
                writer.writerow({
                    "name": f.get("name", ""),
                    "rel": f.get("rel", f.get("name", "")),
                    "size_bytes": f.get("size_bytes", 0),
                    "status": f.get("status", ""),
                    "created": f.get("created", ""),
                    "modified": f.get("modified", ""),
                    "algorithm": algo,
                    "hash": f.get("hash", ""),
                    "destinations": "; ".join(f"{d}={st}" for d, st in dest_status.items()),
                    "media_format": f.get("media_format", ""),
                })
        return csv_path

    @staticmethod
    def record_job_history(history_path, entry, max_entries=50):
        """Aggiunge `entry` (dict: job_type, report_id, timestamp, status, n_files, n_ok,
        destinations, report_path) a un log JSON persistente su disco, tenendo solo gli
        ultimi `max_entries` (i piu' vecchi vengono scartati automaticamente).

        Prima Datarium non aveva nessuna cronologia job persistente: la coda Ingest teneva
        solo i job della sessione corrente in memoria, persi alla chiusura dell'app. Questo
        e' un log durevole su disco, indipendente dalla sessione, con retention configurabile
        (come "# of jobs to keep in history" di ShotPut Pro)."""
        import json
        history = []
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []
        history.append(entry)
        if max_entries > 0 and len(history) > max_entries:
            history = history[-max_entries:]
        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Errore salvataggio cronologia job: {e}")
        return history

    @staticmethod
    def load_job_history(history_path):
        """Legge la cronologia job persistente. Ritorna [] se non esiste o e' corrotta."""
        import json
        if not os.path.exists(history_path):
            return []
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def purge_job_history(history_path):
        """Svuota la cronologia job persistente (equivalente a 'Purge Report History')."""
        import json
        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception as e:
            print(f"Errore purge cronologia job: {e}")

    @classmethod
    def save_hash_report(cls, output_dir, report_id, files_list, algo, comparison=None):
        """Genera e salva un vero e proprio file PDF di verifica Hash usando PyMuPDF."""
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"{report_id}_Hash_Report.pdf")
        
        import fitz
        doc = fitz.open()
        
        font_name = "helvetica"
        page = doc.new_page(width=595, height=842) # A4
        
        # Disegna Intestazione
        page.draw_rect(fitz.Rect(0, 0, 595, 80), color=None, fill=(0.1, 0.1, 0.1)) # Grigio scuro
        page.insert_textbox(fitz.Rect(20, 15, 400, 70), "DATARIUM - HASH VERIFICATION REPORT", fontsize=16, fontname=f"{font_name}-bold", color=(1, 1, 1))
        page.insert_textbox(fitz.Rect(20, 45, 400, 75), f"ID: {report_id}  |  Generato il: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", fontsize=9, fontname=font_name, color=(0.8, 0.8, 0.8))
        
        # Badge di stato (sempre verified per hash check completato)
        page.draw_rect(fitz.Rect(450, 20, 570, 60), color=None, fill=(0.06, 0.72, 0.5), width=0, radius=0.25)
        page.insert_textbox(fitz.Rect(450, 28, 570, 55), "COMPLETED", fontsize=11, fontname=f"{font_name}-bold", color=(1, 1, 1), align=1)
        
        # Specifiche Hardware e Riepilogo
        specs = cls.get_hardware_specs()
        page.insert_textbox(fitz.Rect(20, 100, 280, 180), 
                             cls.safe_text(f"Specifiche PC:\n- OS: {specs['os']}\n- CPU/RAM: {specs['processors']} CPUs, {specs['ram']}"), 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        page.insert_textbox(fitz.Rect(300, 100, 570, 180), 
                             cls.safe_text(f"Riepilogo Scansione:\n- File Analizzati: {len(files_list)}\n- Algoritmo Checksum: {algo}"), 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        y = 190
        if comparison:
            n_ok, n_diff = len(comparison["identical"]), len(comparison["different"])
            n_a, n_b, n_mv = len(comparison["only_a"]), len(comparison["only_b"]), len(comparison["moved"])
            all_ok = not (n_diff or n_a or n_b or n_mv)
            page.insert_text((20, y+8), "CONFRONTO CARTELLA 1 / CARTELLA 2", fontsize=10, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
            page.insert_text((20, y+24), cls.safe_text("Cartella 1: " + comparison["a_root"])[:95], fontsize=7, fontname=font_name, color=(0.3, 0.3, 0.3))
            page.insert_text((20, y+34), cls.safe_text("Cartella 2: " + comparison["b_root"])[:95], fontsize=7, fontname=font_name, color=(0.3, 0.3, 0.3))
            verdict = "ESITO: CARTELLE IDENTICHE" if all_ok else "ESITO: LE CARTELLE NON COINCIDONO"
            page.insert_text((20, y+52), verdict, fontsize=11, fontname=f"{font_name}-bold", color=(0.06, 0.55, 0.35) if all_ok else (0.8, 0.15, 0.15))
            page.insert_text((20, y+66), f"{n_ok} identici - {n_diff} diversi - {n_a} solo in Cartella 1 - {n_b} solo in Cartella 2 - {n_mv} percorso diverso", fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            y += 80
            problems = ([("DIVERSO", a["rel"]) for a, _b in comparison["different"]]
                        + [("SOLO C1", r["rel"]) for r in comparison["only_a"]]
                        + [("SOLO C2", r["rel"]) for r in comparison["only_b"]]
                        + [("PERCORSO", a["rel"]) for a, _b in comparison["moved"]])
            for label, rel in problems:
                if y > 800:
                    page = doc.new_page(width=595, height=842)
                    y = 40
                page.insert_text((25, y+10), label, fontsize=8, fontname=f"{font_name}-bold", color=(0.8, 0.15, 0.15))
                page.insert_text((85, y+10), cls.safe_text(rel)[:90], fontsize=8, fontname=font_name, color=(0.1, 0.1, 0.1))
                y += 13
            y += 15
            if y > 760:
                page = doc.new_page(width=595, height=842)
                y = 40

        # Tabella dei File
        page.draw_rect(fitz.Rect(20, y, 575, y+20), color=None, fill=(0.95, 0.95, 0.95))
        page.insert_text((25, y+14), "Nome File", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        page.insert_text((220, y+14), "Tipo", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        page.insert_text((280, y+14), f"Valore Checksum ({algo})", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        page.insert_text((510, y+14), "Ruolo", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        
        y += 25
        for f in files_list:
            if y > 800:
                page = doc.new_page(width=595, height=842)
                y = 40
                page.draw_rect(fitz.Rect(20, y, 575, y+20), color=None, fill=(0.95, 0.95, 0.95))
                page.insert_text((25, y+14), "Nome File", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                page.insert_text((220, y+14), "Tipo", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                page.insert_text((280, y+14), f"Valore Checksum ({algo})", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                page.insert_text((510, y+14), "Ruolo", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                y += 25
            
            page.draw_line((20, y+18), (575, y+18), color=(0.9, 0.9, 0.9), width=0.5)
            
            name_disp = cls.safe_text(f["name"])
            if len(name_disp) > 30:
                name_disp = name_disp[:27] + "..."
            page.insert_text((25, y+12), name_disp, fontsize=8, fontname=font_name, color=(0.1, 0.1, 0.1))
            page.insert_text((220, y+12), f.get("type", "FILE"), fontsize=8, fontname=font_name, color=(0.3, 0.3, 0.3))
            
            h_disp = f.get("hash", "N/A")
            if len(h_disp) > 36:
                h_disp = h_disp[:33] + "..."
            page.insert_text((280, y+12), h_disp, fontsize=8, fontname="courier", color=(0.06, 0.5, 0.3))
            
            role_text = "Sorgente" if f.get("is_source") else "Confronto"
            if f.get("root") and comparison:
                role_text = "Cartella 1" if f["root"] == comparison["a_root"] else "Cartella 2"
            role_color = (0.06, 0.72, 0.5) if f.get("is_source") else (0.38, 0.65, 0.98)
            page.insert_text((510, y+12), role_text, fontsize=8, fontname=f"{font_name}-bold", color=role_color)
            
            y += 22
            
        doc.save(report_path)
        doc.close()
        return report_path
