"""Značka z obrázku letáku: první řádek textového bloku vlevo dole (bílé verzálky na barevném pozadí).

Alt text letáku někdy značku od názvu neoddělí ('Milsani Gouda'), na obrázku je ale vždy zvlášť
('MILSANI' / 'GOUDA'). Výsledek je jen nápověda: hofer_flyer.apply_brand ji přijme, jen když sedí
na začátek názvu z alt textu.
"""
import io
import os
import re
import shutil
import subprocess

import numpy as np
from PIL import Image

if shutil.which("tesseract") is None:
    raise RuntimeError("Binárka 'tesseract' nenalezena (pkg install tesseract / apt install tesseract-ocr)")

BOX = (0.09, 0.42, 0.355, 0.62)          # zlomky šířky obrázku (x0, y0, x1, y1)
_CAPS = re.compile(r"[A-ZÄÖÜ][A-ZÄÖÜ&'.\-]*")
_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")


def brand_line(image_bytes):
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return ""
    w = im.width
    a = np.asarray(im.crop(tuple(int(round(v * w)) for v in BOX))).astype(int)
    if not a.size:
        return ""
    white = a.min(axis=2) > 185                                  # bílý text, barevné pozadí
    m = np.pad(np.where(white, 0, 255).astype(np.uint8), 30, constant_values=255)
    m = np.asarray(Image.fromarray(m).resize((m.shape[1] * 2, m.shape[0] * 2), Image.BICUBIC))
    buf = io.BytesIO()
    Image.fromarray(m).save(buf, format="PNG")
    try:
        r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "6"],
                           input=buf.getvalue(), capture_output=True, timeout=30, env=_ENV)
    except subprocess.TimeoutExpired:
        return ""
    for line in r.stdout.decode("utf-8", "ignore").splitlines()[:4]:
        s = " ".join(t for t in line.split() if _CAPS.fullmatch(t))   # zahodí šum (malá písmena, znaky)
        if len(s.replace(" ", "")) >= 3:
            return s
    return ""
