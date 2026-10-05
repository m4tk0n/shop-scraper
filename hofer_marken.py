"""Stránky značek hofer.at/marken/<ZNAČKA> -> jeden JSON se všemi produkty ze všech značek.

Seznam značek je v textovém souboru znacky.txt (jedna značka na řádek; jméno nebo celá adresa;
řádky začínající # se přeskakují). Značky, které skript sám najde v už vytvořených výstupech
mezi sladkostmi, doplní přepínač --auto.

    python3 hofer_marken.py                  # značky ze znacky.txt
    python3 hofer_marken.py --auto           # + značky nalezené v datech
    python3 hofer_marken.py HARIBO KÄGI      # jen vybrané značky
"""
import os
import re
import sys
import time
from urllib.parse import quote, unquote, urlparse

from hofer_common import outdir, register_source, run_batches
from hofer_listings import fetch_listing

BASE = "https://www.hofer.at"
SOURCE = "marken"
BRANDS_FILE = "znacky.txt"


def bkey(s):
    return re.sub(r"[^a-z0-9äöüßé&']+", " ", (s or "").lower()).strip()


def default_path():
    for d in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        p = os.path.join(d, BRANDS_FILE)
        if os.path.exists(p):
            return p
    return os.path.join(os.getcwd(), BRANDS_FILE)


def read_watchlist(path=None):
    """-> [{'name', 'url' | None}]  (bez duplicit podle názvu)"""
    path = path or default_path()
    out, seen = [], set()
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http"):
            name = unquote(urlparse(line).path.rstrip("/").split("/")[-1])
            url = line
        else:
            name, url = line, None
        if bkey(name) not in seen:
            seen.add(bkey(name))
            out.append({"name": name, "url": url})
    return out


def url_variants(name):
    """Různé zápisy názvu značky v adrese (web používá velká písmena: KÄGI, FINEST%20BAKERY)."""
    cands = [name.upper(), name, name.replace("-", " ").upper(), name.replace(" ", "-").upper(), name.title()]
    out, seen = [], set()
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(f"{BASE}/marken/{quote(c, safe='')}")
    return out


def fetch_brand(session, entry):
    urls = [entry["url"]] if entry["url"] else url_variants(entry["name"])
    for u in urls:
        items = fetch_listing(session, SOURCE, u, pause=0.4)
        if items:
            return u, items
    return None, []


def auto_brands(folder, known):
    """Značky ze sladkostí v nejnovějších výstupech, které ještě nejsou v seznamu."""
    from hofer_brands import SWEET_CATEGORIES, latest_files
    found = {}
    for _, _, products in latest_files(folder):
        for p in products:
            if p["brand"] and p["category"] in SWEET_CATEGORIES and bkey(p["brand"]) not in known:
                found.setdefault(bkey(p["brand"]), p["brand"])
    return list(found.values())


def collect(session, opts):
    register_source(SOURCE, "listing")
    watch = read_watchlist()
    if opts["args"]:                                   # vybrané značky z příkazové řádky
        wanted = {bkey(a) for a in opts["args"]}
        watch = [w for w in watch if bkey(w["name"]) in wanted] + \
                [{"name": a, "url": None} for a in opts["args"] if bkey(a) not in {bkey(w["name"]) for w in watch}]
    elif "--auto" in sys.argv:
        known = {bkey(w["name"]) for w in watch}
        extra = auto_brands(outdir(), known)
        print(f"--auto: doplněno {len(extra)} značek z dat: {extra}")
        watch += [{"name": n, "url": None} for n in extra]
    if not watch:
        print(f"Žádné značky. Vytvoř soubor {BRANDS_FILE} (jedna značka na řádek).")
        return

    products, seen, stats = [], set(), []
    for i, entry in enumerate(watch, 1):
        print(f"\n[{i}/{len(watch)}] {entry['name']}")
        url, items = fetch_brand(session, entry)
        new = 0
        for p in items:
            key = p["store_product_id"] or (p["brand"], p["name"])
            if key in seen:
                continue
            seen.add(key)
            p["theme"] = entry["name"]                 # ze které stránky značky produkt pochází
            products.append(p)
            new += 1
        stats.append((entry["name"], len(items), new, url))
        time.sleep(0.4)

    print("\nShrnutí značek:")
    for name, n, new, url in stats:
        print(f"  {name[:24]:24} {'nalezeno' if n else 'NENALEZENO':10} {n:3} produktů ({new} nových)")
    yield {"source": SOURCE, "source_url": f"{BASE}/marken", "label": "", "products": products}


if __name__ == "__main__":
    run_batches(collect)
