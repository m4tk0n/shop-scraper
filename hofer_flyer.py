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

from hofer_common import (SIZE_RE, amount_key, categorize, clean, derive_tags, fix_liquid_unit, make_product, norm_unit, outdir, parse_heading_range, price, run_batches, slug)
from hofer_discover import get_discovery

PAGES = {
    "tiefpreis": "https://www.hofer.at/flugblatt/tiefpreis-aktionen",
    "bier": "https://www.hofer.at/flugblatt/bier-aktionen",
}
VARIANT_TXT = "in verschiedenen Sorten erhältlich"
# 'per kg', 'pro kg', 'je 100 g' jako samostatná část alt textu -> množství, na které platí cena
PER_UNIT = re.compile(r"^(?:per|pro|je)\s+(\d+(?:[.,]\d+)?\s*)?(kg|g|l|ml|stk)\.?$", re.I)
# zboží prodávané na váhu bez udání množství v alt textu: 'Äpfel lose aus Österreich' = cena za 1 kg
LOOSE_RE = re.compile(r"\blose\b", re.I)
PRICE_END = re.compile(r"(?:€\s*)?(\d+,\d{2})\s*$")
DATE_RE = re.compile(r"(\d{1,2})\.\s?(\d{1,2})\.")
# velikost na začátku části s dalším textem: '150 g Schale', '2 Stk. Packung'
LEAD_SIZE = re.compile(r"^\s*(\d+(?:[.,]\d+)?(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?)\s*(kg|g|ml|cl|l|stk\.?|stück)(?![a-zäöüß])", re.I)


def section_dates(heading, today=None):
    """'... Wochenstart: Mo. 12.10. bis Do. 15.10.' -> ('2026-10-12', '2026-10-15'); rok se ověřuje podle zkratky dne."""
    return parse_heading_range(heading, today)


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
        pu = PER_UNIT.match(part)
        if pu and not amount:
            amount, unit = (pu.group(1) or "1").replace(",", ".").replace(" ", ""), norm_unit(pu.group(2))
            continue
        sm = SIZE_RE.match(part) or LEAD_SIZE.match(part)
        if sm and sm.group(2) and not amount:
            amount, unit = sm.group(1).replace(",", ".").replace(" ", ""), norm_unit(sm.group(2))
            continue
        names.append(part)
    brand, name = (names[0], ", ".join(names[1:])) if len(names) >= 2 else ("", names[0] if names else "")
    if not amount and LOOSE_RE.search(f"{brand} {name}"):
        amount, unit = "1", "kg"
    unit = fix_liquid_unit(brand, name, unit)
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
        if valid_to and valid_to < today.isoformat():
            continue                                     # skupina letáku, která už skončila
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
            validity_source="product_group" if valid_from else "unknown",
            validity_confidence=("verified" if valid_to else "start_only") if valid_from else "unknown",
        ))
    return out


def _norm(s):
    s = re.sub(r"\d+(?:[.,]\d+)?\s*%\s*vol\.?", " ", (s or "").lower())      # '5,0%Vol.' v názvu z letáku
    return re.sub(r"[^a-zäöüß0-9]+", " ", s).strip()


def resolve_ids(products, folder, pool=None):
    """Doplní skutečné 18místné ID (číslo zboží) ze zdrojů s dlaždicemi. Číslo obrázku z letáku ID není."""
    from hofer_brands import latest_files
    full, by_name = {}, {}
    known = [p for _, m, ps in latest_files(folder) if m["source"] not in ("tiefpreis", "bier") for p in ps]
    for p in known + list(pool or []):               # pool = produkty stažené v tomtéž běhu (ještě nejsou na disku)
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
    streak = 0                                   # obrázků po sobě bez procenta slevy
    found = 0                                    # kolik původních cen se už našlo
    for i, p in enumerate(products, 1):
        if streak >= 15 and not found:           # formát se asi změnil, OCR nemá smysl
            print("  prvních 15 obrázků bez slevy, OCR původních cen se přeskakuje")
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
            found += 1
        k = src.split("(")[0].split(":")[0]
        streak = streak + 1 if k == "no_percent" else 0
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
        found = resolve_ids(products, outdir(), opts.get("pool"))
        print(f"  ID produktu doplněno z ostatních zdrojů: {found} z {len(products)} (zbytek zůstává prázdný)")
        if ocr and products:
            add_original_prices(session, products, ocr)
        yield {"source": n, "source_url": url, "label": "", "products": products}


if __name__ == "__main__":
    run_batches(collect)
