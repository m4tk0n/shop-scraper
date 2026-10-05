"""Hofer letákové stránky s obrázky (data v alt textu): Tiefpreis a Bier Aktionen.

    python3 hofer_flyer.py                 # tiefpreis + bier
    python3 hofer_flyer.py bier            # jen vybraný
    python3 hofer_flyer.py --no-ocr        # bez OCR původních cen
    python3 hofer_flyer.py --food
"""
import re
import time
from datetime import date

from bs4 import BeautifulSoup

from hofer_common import (SIZE_RE, amount_key, categorize, clean, derive_tags, make_product, outdir, price, run_batches, slug)
from hofer_discover import get_discovery

PAGES = {
    "tiefpreis": "https://www.hofer.at/flugblatt/tiefpreis-aktionen",
    "bier": "https://www.hofer.at/flugblatt/bier-aktionen",
}
VARIANT_TXT = "in verschiedenen Sorten erhältlich"
PRICE_END = re.compile(r"(?:€\s*)?(\d+,\d{2})\s*$")
DATE_RE = re.compile(r"(\d{1,2})\.\s?(\d{1,2})\.")


def section_dates(heading, today=None):
    """'... Wochenstart: Mo. 28.9. bis Do. 1.10.' -> ('2026-09-28', '2026-10-01')"""
    today = today or date.today()
    found = DATE_RE.findall(heading)
    if not found:
        return "", ""
    (d1, m1), (d2, m2) = found[0], found[-1]
    y_to = today.year
    y_from = y_to - 1 if int(m1) > int(m2) else y_to
    return f"{y_from}-{int(m1):02d}-{int(d1):02d}", f"{y_to}-{int(m2):02d}-{int(d2):02d}"


def section_theme(heading):
    h = heading.split(" - ", 1)[-1]
    m = re.match(r"\s*([^:]+):", h)
    return clean(m.group(1)) if m else ""


def parse_alt(alt):
    """'Gösser, Naturgold Alkoholfrei*, 12 x 0,5 l, 6+6 gratis € 0,74' -> dict | None"""
    alt = clean(alt)
    m = PRICE_END.search(alt)
    if not m:
        return None
    cur = price(m.group(1))
    rest = alt[:m.start()].strip().rstrip(",").strip()
    note = ""
    pm = re.search(r"(\d+\+\d+\s*gratis)\s*$", rest)
    if pm:
        note = pm.group(1)
        rest = rest[:pm.start()].strip().rstrip(",").strip()
    amount = unit = ""
    variants = False
    names = []
    for part in [p.strip().rstrip("*").strip() for p in re.split(r",\s+", rest) if p.strip()]:
        if part == VARIANT_TXT:
            variants = True
            continue
        sm = SIZE_RE.match(part)
        if sm and sm.group(2) and not amount:
            amount, unit = sm.group(1).replace(",", ".").replace(" ", ""), sm.group(2).lower()
            continue
        names.append(part)
    brand, name = (names[0], ", ".join(names[1:])) if len(names) >= 2 else ("", names[0] if names else "")
    return {"brand": brand, "name": name, "amount": amount, "unit": unit, "price": cur, "note": note, "variants": variants}


def parse_flyer(html, source, url, today=None):
    today = today or date.today()
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    theme = valid_from = valid_to = ""
    in_section = False
    for el in soup.find_all(["h2", "img"]):
        if el.name == "h2":
            txt = clean(el.get_text(" ", strip=True))
            if DATE_RE.search(txt):
                in_section = True
                valid_from, valid_to = section_dates(txt, today)
                theme = section_theme(txt)
            continue
        src = el.get("src") or el.get("data-src") or ""
        alt = el.get("alt") or ""
        if not in_section or "aldiprodeu" not in src or not alt:
            continue
        a = parse_alt(alt)
        if not a or not a["name"]:
            continue
        fname = src.split("/")[-1].split("?")[0]
        idm = re.match(r"(\d+)_", fname)
        pid = idm.group(1).zfill(18) if idm else ""
        key = (pid or alt, valid_from)
        if key in seen:
            continue
        seen.add(key)
        badges = ([a["note"]] if a["note"] else [])
        tags = derive_tags(a["brand"], a["name"], badges)
        if source == "tiefpreis" and "tiefpreisaktion" not in tags:
            tags.insert(0, "tiefpreisaktion")
        out.append(make_product(
            source,
            store_product_id="", brand=a["brand"], name=a["name"], amount=a["amount"], unit=a["unit"],
            product_url="", image_url=src.split("?")[0],
            category=categorize(a["brand"], a["name"], a["unit"], tags, "food"),
            price=a["price"], original_price="", comparison_price="", comparison_per="",
            valid_from=valid_from, valid_to=valid_to, source_date=today.isoformat(), theme=theme, tags=tags,
            variants=a["variants"],
        ))
    return out


def _norm(s):
    return re.sub(r"[^a-zäöüß0-9]+", " ", (s or "").lower()).strip()


def resolve_ids(products, folder):
    """Doplní skutečné 18místné ID (číslo zboží) ze zdrojů s dlaždicemi. Číslo obrázku z letáku ID není."""
    from hofer_brands import latest_files
    full, by_name = {}, {}
    for _, m, ps in latest_files(folder):
        if m["source"] in ("tiefpreis", "bier"):
            continue
        for p in ps:
            if p["store_product_id"]:
                full.setdefault((_norm(p["brand"]), _norm(p["name"])), []).append(p)
                by_name.setdefault(_norm(p["name"]), []).append(p)

    def pick(cands, p):
        if p["amount"]:                                  # množství musí sedět (i kg vs g), pokud je u obou známé
            cands = [c for c in cands if not c["amount"]
                     or amount_key(c["amount"], c["unit"]) == amount_key(p["amount"], p["unit"])]
        ids = {c["store_product_id"] for c in cands}
        return cands[0] if len(ids) == 1 else None       # jen jednoznačná shoda

    found = 0
    for p in products:
        hit = pick(full.get((_norm(p["brand"]), _norm(p["name"])), []), p)
        if not hit:                                      # značka chybí na jedné straně: stačí shoda jména
            cands = [c for c in by_name.get(_norm(p["name"]), []) if not c["brand"] or not p["brand"]]
            hit = pick(cands, p)
        if hit and hit["product_url"]:                   # ID platí jen spolu s odkazem na stránku produktu
            p["store_product_id"] = hit["store_product_id"]
            p["product_url"] = hit["product_url"]
            found += 1
    return found


def add_original_prices(session, products, ocr):
    """Doplní original_price z obrázku letáku (OCR + kontrola proti procentu slevy)."""
    stats = {}
    for i, p in enumerate(products, 1):
        if i == 7 and stats.get("no_percent", 0) == 6:
            print("  prvních 6 obrázků bez slevy, OCR původních cen se přeskakuje")
            break
        if not p["image_url"]:
            continue
        try:
            r = session.get(p["image_url"] + "?wid=1460", timeout=30)
            if r.status_code != 200:
                raise RuntimeError(r.status_code)
            orig, pct, src = ocr(r.content, p["price"])
        except Exception as e:
            orig, pct, src = None, None, f"error:{type(e).__name__}"
        if orig:
            p["original_price"] = f"{orig:.2f}"
        k = src.split("(")[0].split(":")[0]
        stats[k] = stats.get(k, 0) + 1
        print(f"  [{i}/{len(products)}] {p['name'][:28]:28} {p['price']:>6} -> {p['original_price'] or '?':>6} ({pct}%) {src}", flush=True)
    print("  zdroje původních cen:", stats)


def collect(session, opts):
    pages = get_discovery(session, opts)["flyers"] or PAGES
    names = opts["args"] or list(pages)
    ocr = None
    if not opts.get("no_ocr"):
        try:
            from hofer_ocr import original_price as ocr
        except Exception as e:
            print(f"OCR vypnuto ({e}); original_price zůstane prázdné.")
    for n in names:
        if n not in pages:
            print("Neznámý zdroj:", n, "| nalezené:", list(pages))
            continue
        url = pages[n]
        print(f"\n=== {n} ===")
        r = session.get(url, timeout=60)
        if r.status_code != 200:
            print(f"  ! status {r.status_code}")
            continue
        products = parse_flyer(r.text, n, url)
        print(f"  nalezeno {len(products)} produktů")
        found = resolve_ids(products, outdir())
        print(f"  ID produktu doplněno z ostatních zdrojů: {found} z {len(products)} (zbytek zůstává prázdný)")
        if ocr and products:
            add_original_prices(session, products, ocr)
        yield {"source": n, "source_url": url, "label": "", "products": products}


if __name__ == "__main__":
    run_batches(collect)
