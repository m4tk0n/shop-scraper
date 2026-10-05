import io
import os
import re
import shutil
import subprocess
from collections import Counter

import numpy as np
from PIL import Image

PCT_BOX = (195, 255, 425, 340)     # žlutý box "-52%"
ORIG_BOX = (345, 362, 450, 416)    # přeškrtnutá cena
WL_PRICE = "0123456789,"
WL_PCT = "0123456789-%"

if shutil.which("tesseract") is None:
    raise RuntimeError("Binárka 'tesseract' nenalezena (pkg install tesseract / apt install tesseract-ocr)")

_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")


def _tess(arr, whitelist, psm=7):
    """arr: uint8 2D pole. Volá tesseract přes stdin/stdout."""
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    try:
        r = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", str(psm),
             "-c", f"tessedit_char_whitelist={whitelist}"],
            input=buf.getvalue(), capture_output=True, timeout=30, env=_ENV)
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout.decode("utf-8", "ignore").strip()


# --- jednorozměrná morfologie přes kumulativní součty (bez OpenCV/SciPy) ---
def _win_sum(a, k, axis):
    a = a.astype(np.int32)
    before = k // 2
    after = k - 1 - before
    pad = [(0, 0), (0, 0)]
    pad[axis] = (before, after)
    a = np.pad(a, pad)
    c = np.cumsum(a, axis=axis)
    zero_shape = list(c.shape)
    zero_shape[axis] = 1
    c = np.concatenate([np.zeros(zero_shape, c.dtype), c], axis=axis)
    n = c.shape[axis]
    hi = np.take(c, np.arange(k, n), axis=axis)
    lo = np.take(c, np.arange(0, n - k), axis=axis)
    return hi - lo


def _erode(a, k, axis):
    return _win_sum(a, k, axis) == k


def _dilate(a, k, axis):
    return _win_sum(a, k, axis) > 0


def _open(a, k, axis):
    return _dilate(_erode(a, k, axis), k, axis)


def _close(a, k, axis):
    return _erode(_dilate(a, k, axis), k, axis)


def _load(data):
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def read_percent(im):
    g = im.crop(PCT_BOX).convert("L")
    g = g.resize((g.width * 4, g.height * 4), Image.BICUBIC)
    m = (np.asarray(g) > 90).astype(np.uint8) * 255      # tmavý text na žlutém
    m = np.pad(m, 30, constant_values=255)
    t = _tess(m, WL_PCT)
    mt = re.search(r'-\s*(\d{2})', t)
    return int(mt.group(1)) if mt else None


def _clean_orig(im, scale, thr, angle):
    c = im.crop(ORIG_BOX)
    c = c.resize((c.width * scale, c.height * scale), Image.BICUBIC)
    green = np.asarray(c)[:, :, 1]
    m = (green > thr).astype(np.uint8) * 255
    m = np.pad(m, 60)
    h, w = m.shape
    r = Image.fromarray(m).rotate(-angle, resample=Image.BILINEAR)   # srovnat čáru
    r = np.asarray(r) > 127
    line = _open(r, max(3, int(0.22 * w)), axis=1)                   # dlouhá vodorovná čára
    line = _dilate(line, 5, axis=0)
    r = r & ~line
    r = _close(r, 15, axis=0)                                        # slepit mezery v číslicích
    back = Image.fromarray(r.astype(np.uint8) * 255).rotate(angle, resample=Image.BILINEAR)
    return 255 - np.asarray(back)


def candidates(promo, pct):
    """Všechny původní ceny (v centech), které sedí na akční cenu a procento."""
    out = []
    p_cents = round(promo * 100)
    for o in range(p_cents + 1, p_cents * 12):
        p = (1 - p_cents / o) * 100
        if int(p) == pct or round(p) == pct:      # floor i běžné zaokrouhlení
            out.append(o)
    return out


def original_price(image_bytes, promo):
    """-> (original_price | None, pct | None, source)"""
    im = _load(image_bytes)
    if im is None:
        return None, None, "bad_image"
    pct = read_percent(im)
    if not pct or not (5 <= pct <= 90):
        return None, None, "no_percent"
    cands = candidates(float(promo), pct)
    if not cands:
        return None, pct, "no_candidates"
    # klíč = číslice bez čárky ("249"), OCR čárku často vynechá
    cand_str = {f"{c // 100}{c % 100:02d}": c for c in cands}

    votes = Counter()
    for thr in (130, 160, 190):
        for ang in (14, 16.4, 18):
            t = _tess(_clean_orig(im, 6, thr, ang), WL_PRICE).replace(",", "")
            if t in cand_str:
                votes[t] += 1
    if votes:
        (best, n), *rest = votes.most_common()
        # jeden hlas stačí jen u ceny končící na 9; jinak chceme aspoň dva shodné hlasy
        if (not rest or n > rest[0][1]) and (n >= 2 or cand_str[best] % 10 == 9):
            return cand_str[best] / 100, pct, f"ocr({n})"

    nice = [c for c in cands if c % 10 == 9]         # ceny končící na 9
    if len(nice) == 1:
        return nice[0] / 100, pct, "derived"
    return None, pct, f"ambiguous:{','.join(str(c/100) for c in nice[:6])}"
