"""
Parole chiave e persone in formato XMP, lo standard Adobe letto da Lightroom, Bridge,
Capture One, darktable, digiKam e Photo Mechanic.

- RAW: sidecar 'NOME.xmp' accanto al file (il RAW non viene mai modificato).
  Se un .xmp esiste gia' (es. regolazioni di Lightroom) NON viene toccato.
- JPEG: XMP incorporato nel file (Lightroom ignora i sidecar dei JPEG). Si usa solo
  sulle COPIE create da Auto Tag, mai sugli originali; se il JPEG ha gia' un blocco
  XMP viene lasciato com'e'.

Campi scritti: dc:subject (parole chiave), lr:hierarchicalSubject (gerarchia
"Datarium|Album|..." e "Persone|Nome"), Iptc4xmpExt:PersonInImage (persone).
"""
import os
from xml.sax.saxutils import escape

RAW_EXTS = {'.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw', '.srf', '.sr2', '.dng', '.raf', '.rw2',
            '.raw', '.orf', '.pef', '.srw', '.rwl', '.3fr', '.fff', '.iiq', '.erf', '.mef', '.mos', '.x3f'}
JPEG_EXTS = {'.jpg', '.jpeg'}
XMP_APP1_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"


def _bag(items):
    return "".join(f"<rdf:li>{escape(str(i))}</rdf:li>" for i in items)


def build_packet(keywords, people=(), hierarchy=()):
    keywords = [k for k in dict.fromkeys(str(k).strip() for k in keywords) if k]
    people = [p for p in dict.fromkeys(str(p).strip() for p in people) if p]
    subjects = list(dict.fromkeys(keywords + people))
    hier = [h for h in dict.fromkeys(list(hierarchy) + [f"Persone|{p}" for p in people]) if h]
    parts = [
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Datarium">',
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '<rdf:Description rdf:about=""'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:lr="http://ns.adobe.com/lightroom/1.0/"'
        ' xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">',
    ]
    if subjects:
        parts.append(f"<dc:subject><rdf:Bag>{_bag(subjects)}</rdf:Bag></dc:subject>")
    if hier:
        parts.append(f"<lr:hierarchicalSubject><rdf:Bag>{_bag(hier)}</rdf:Bag></lr:hierarchicalSubject>")
    if people:
        parts.append(f"<Iptc4xmpExt:PersonInImage><rdf:Bag>{_bag(people)}</rdf:Bag></Iptc4xmpExt:PersonInImage>")
    parts += ["</rdf:Description>", "</rdf:RDF>", "</x:xmpmeta>", '<?xpacket end="w"?>']
    return "\n".join(parts)


def sidecar_path(media_path):
    return os.path.splitext(media_path)[0] + ".xmp"


def write_sidecar(media_path, keywords, people=(), hierarchy=()):
    """Crea 'NOME.xmp' per un RAW. Ritorna il percorso creato, o None se non applicabile
    o se esiste gia' un sidecar (che potrebbe contenere lavoro dell'utente)."""
    if os.path.splitext(media_path)[1].lower() not in RAW_EXTS:
        return None
    target = sidecar_path(media_path)
    # esiste gia' un sidecar, in stile Lightroom (NOME.xmp) o darktable (NOME.NEF.xmp)?
    if os.path.exists(target) or os.path.exists(media_path + ".xmp") or os.path.exists(media_path + ".XMP"):
        return None
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(build_packet(keywords, people, hierarchy))
        return target
    except OSError as e:
        print(f"[XMP] Sidecar non scritto {target}: {e}")
        return None


def _jpeg_has_xmp(data):
    """Scorre i segmenti JPEG fino all'inizio dell'immagine cercando un APP1 XMP."""
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xDA, 0xD9):  # inizio scansione / fine immagine
            break
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if marker == 0xE1 and data[i + 4:i + 4 + len(XMP_APP1_HEADER)] == XMP_APP1_HEADER:
            return True
        i += 2 + seg_len
    return False


def embed_in_jpeg(jpeg_path, keywords, people=(), hierarchy=()):
    """Inserisce un blocco XMP in un JPEG (da usare solo su copie). True se scritto."""
    if os.path.splitext(jpeg_path)[1].lower() not in JPEG_EXTS:
        return False
    try:
        with open(jpeg_path, "rb") as f:
            data = f.read()
        if data[:2] != b"\xff\xd8" or _jpeg_has_xmp(data):
            return False
        payload = XMP_APP1_HEADER + build_packet(keywords, people, hierarchy).encode("utf-8")
        if len(payload) + 2 > 0xFFFF:
            return False
        segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
        # dopo SOI e dopo gli eventuali APP0 (JFIF) / APP1 (Exif) gia' presenti
        i = 2
        while i + 4 <= len(data) and data[i] == 0xFF and data[i + 1] in (0xE0, 0xE1):
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        tmp = jpeg_path + ".datarium_tmp"
        with open(tmp, "wb") as f:
            f.write(data[:i] + segment + data[i:])
        os.replace(tmp, jpeg_path)
        return True
    except OSError as e:
        print(f"[XMP] XMP non incorporato in {jpeg_path}: {e}")
        return False
