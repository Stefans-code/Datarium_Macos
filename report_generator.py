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
                # Estrae un thumbnail video in base64 per HTML
                thumbs = cls.extract_video_thumbnails(it["path"], num_thumbnails=1)
                if thumbs:
                    import base64
                    b64 = base64.b64encode(thumbs[0]).decode('ascii')
                    preview_elem = f'<img class="preview-img" src="data:image/jpeg;base64,{b64}" alt="Video Preview"/>'
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
    def extract_video_thumbnails(video_path, num_thumbnails=6):
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
    def extract_media_info(file_path):
        """Estrae metadati REALI (risoluzione, durata, codec, bitrate, camera) da video e immagini.
        Ritorna sempre un dizionario; i campi non disponibili valgono 'N/A' (mai dati fittizi)."""
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
        }

        try:
            if ext in video_exts:
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
    def save_report(cls, output_dir, report_id, source_dir, files_list, algo, dest_dirs, production_meta=None):
        """Genera e salva un vero e proprio file PDF di verifica Offload usando PyMuPDF.
        production_meta: dizionario opzionale {etichetta: valore} di metadati produzione (stile Silverstack)."""
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
        page.insert_textbox(fitz.Rect(300, 100, page_width - 20, 200), 
                             cls.safe_text(f"Riepilogo Offload:\n- File Totali: {len(files_list)}\n- Dimensione Totale: {total_size_str}\n- Algoritmo: {algo}\n- Destinazioni:\n{dests_str}"), 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        # Sezione Metadati Produzione (stile Silverstack), se forniti
        y = 210
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
            hash_algo = "xxHash 64" if algo == "xxHash64" else algo
            hash_val = f.get("hash", "N/A")
            
            page.insert_text((25, y+10), cls.safe_text(f"Size: {size_txt}   Created: {created_txt}"), fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            y += 15
            
            media_fmt = f.get("media_format", "Unknown")
            codec = f.get("codec", "N/A")
            resolution = f.get("resolution", "N/A")
            duration = f.get("duration", "N/A")
            frames = f.get("frames", "N/A")
            
            if media_fmt == "Video":
                page.insert_text((25, y+10), cls.safe_text(f"Video: {resolution} {codec} | Dur: {duration} | Frames: {frames}"), fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            else:
                page.insert_text((25, y+10), cls.safe_text(f"Type: {media_fmt}"), fontsize=8, fontname=font_name, color=(0.2, 0.2, 0.2))
            y += 15
            
            page.insert_text((25, y+10), cls.safe_text(f"{hash_algo}: {hash_val}"), fontsize=8, fontname=font_name, color=(0.4, 0.4, 0.4))
            y += 15
            
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

    @classmethod
    def save_hash_report(cls, output_dir, report_id, files_list, algo):
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
        
        # Tabella dei File
        y = 190
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
            
            name_disp = f["name"]
            if len(name_disp) > 30:
                name_disp = name_disp[:27] + "..."
            page.insert_text((25, y+12), name_disp, fontsize=8, fontname=font_name, color=(0.1, 0.1, 0.1))
            page.insert_text((220, y+12), f.get("type", "FILE"), fontsize=8, fontname=font_name, color=(0.3, 0.3, 0.3))
            
            h_disp = f.get("hash", "N/A")
            if len(h_disp) > 36:
                h_disp = h_disp[:33] + "..."
            page.insert_text((280, y+12), h_disp, fontsize=8, fontname="courier", color=(0.06, 0.5, 0.3))
            
            role_text = "Sorgente" if f.get("is_source") else "Confronto"
            role_color = (0.06, 0.72, 0.5) if f.get("is_source") else (0.38, 0.65, 0.98)
            page.insert_text((510, y+12), role_text, fontsize=8, fontname=f"{font_name}-bold", color=role_color)
            
            y += 22
            
        doc.save(report_path)
        doc.close()
        return report_path
