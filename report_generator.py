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
        except:
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

    @classmethod
    def save_report(cls, output_dir, report_id, source_dir, files_list, algo, dest_dirs):
        """Genera e salva un vero e proprio file PDF di verifica Offload usando PyMuPDF."""
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"{report_id}_MHL_Report.pdf")
        
        import fitz
        doc = fitz.open()
        
        # Stile e Font
        font_name = "helvetica"
        
        # Pagina singola o multipla
        page = doc.new_page(width=595, height=842) # A4
        
        # Disegna Intestazione
        page.draw_rect(fitz.Rect(0, 0, 595, 80), color=None, fill=(0.1, 0.1, 0.1)) # Grigio scuro
        page.insert_textbox(fitz.Rect(20, 15, 400, 70), "DATARIUM - MHL VERIFICATION REPORT", fontsize=16, fontname=f"{font_name}-bold", color=(1, 1, 1))
        page.insert_textbox(fitz.Rect(20, 45, 400, 75), f"ID: {report_id}  |  Generato il: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", fontsize=9, fontname=font_name, color=(0.8, 0.8, 0.8))
        
        # Badge di stato
        overall_status = "VERIFIED"
        if any(f.get("status") == "Failed" for f in files_list):
            overall_status = "FAILED"
            
        status_color = (0.06, 0.72, 0.5) if overall_status == "VERIFIED" else (0.93, 0.26, 0.26)
        page.draw_rect(fitz.Rect(450, 20, 570, 60), color=None, fill=status_color, width=0, radius=0.25)
        page.insert_textbox(fitz.Rect(450, 28, 570, 55), overall_status, fontsize=12, fontname=f"{font_name}-bold", color=(1, 1, 1), align=1)
        
        # Specifiche Hardware e Dettagli
        specs = cls.get_hardware_specs()
        page.insert_textbox(fitz.Rect(20, 100, 280, 200), 
                             f"Specifiche PC:\n• OS: {specs['os']}\n• CPU/RAM: {specs['processors']} CPUs, {specs['ram']}", 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        # Calcolo statistiche
        total_size_bytes = sum(f.get("size_bytes", 0) for f in files_list)
        if total_size_bytes < 1024 * 1024:
            total_size_str = f"{total_size_bytes / 1024:.2f} KB"
        elif total_size_bytes < 1024 * 1024 * 1024:
            total_size_str = f"{total_size_bytes / (1024 * 1024):.2f} MB"
        else:
            total_size_str = f"{total_size_bytes / (1024 * 1024 * 1024):.2f} GB"
            
        dests_str = "\n".join(f"• {d}" for d in dest_dirs)
        page.insert_textbox(fitz.Rect(300, 100, 570, 200), 
                             f"Riepilogo Offload:\n• File Totali: {len(files_list)}\n• Dimensione Totale: {total_size_str}\n• Algoritmo: {algo}\n• Destinazioni:\n{dests_str}", 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        # Tabella dei File
        # Intestazione Tabella
        y = 210
        page.draw_rect(fitz.Rect(20, y, 575, y+20), color=None, fill=(0.95, 0.95, 0.95))
        page.insert_text((25, y+14), "Nome File", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        page.insert_text((220, y+14), "Dimensione", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        page.insert_text((300, y+14), "Checksum", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        page.insert_text((510, y+14), "Stato", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
        
        y += 25
        for f in files_list:
            # Nuova pagina se andiamo fuori dai limiti dell'A4
            if y > 800:
                page = doc.new_page(width=595, height=842)
                y = 40
                # Re-intestazione ridotta su nuova pagina
                page.draw_rect(fitz.Rect(20, y, 575, y+20), color=None, fill=(0.95, 0.95, 0.95))
                page.insert_text((25, y+14), "Nome File", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                page.insert_text((220, y+14), "Dimensione", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                page.insert_text((300, y+14), "Checksum", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                page.insert_text((510, y+14), "Stato", fontsize=9, fontname=f"{font_name}-bold", color=(0.1, 0.1, 0.1))
                y += 25
            
            # Riga del file
            page.draw_line((20, y+18), (575, y+18), color=(0.9, 0.9, 0.9), width=0.5)
            
            # Troncamento del nome file se troppo lungo
            name_disp = f["name"]
            if len(name_disp) > 30:
                name_disp = name_disp[:27] + "..."
                
            page.insert_text((25, y+12), name_disp, fontsize=8, fontname=font_name, color=(0.1, 0.1, 0.1))
            page.insert_text((220, y+12), f.get("size_str", "N/A"), fontsize=8, fontname=font_name, color=(0.3, 0.3, 0.3))
            
            # Troncamento o formattazione dell'hash
            h_disp = f.get("hash", "N/A")
            if len(h_disp) > 36:
                h_disp = h_disp[:33] + "..."
            page.insert_text((300, y+12), h_disp, fontsize=8, fontname="courier", color=(0.06, 0.5, 0.3))
            
            status_text = f.get("status", "Verified")
            status_txt_color = (0.06, 0.72, 0.5) if status_text == "Verified" else (0.93, 0.26, 0.26)
            page.insert_text((510, y+12), status_text, fontsize=8, fontname=f"{font_name}-bold", color=status_txt_color)
            
            y += 22
            
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
                             f"Specifiche PC:\n• OS: {specs['os']}\n• CPU/RAM: {specs['processors']} CPUs, {specs['ram']}", 
                             fontsize=9, fontname=font_name, color=(0.2, 0.2, 0.2))
        
        page.insert_textbox(fitz.Rect(300, 100, 570, 180), 
                             f"Riepilogo Scansione:\n• File Analizzati: {len(files_list)}\n• Algoritmo Checksum: {algo}", 
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
