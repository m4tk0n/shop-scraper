"""ALDI UK (aldi.co.uk) -> JSON ve stejném schématu jako ostatní obchody.

Adresa webu se bere z DB (stores.url) přes proměnnou STORE_URL, nastavuje ji run_stores.py.
Kategorie se zjišťují z menu při každém běhu: /products/<kategorie>[/<podkategorie>...]/k/<id>
(libovolná hloubka; stahují se koncové kategorie, tedy ty bez podkategorií).

    STORE_URL=https://www.aldi.co.uk python3 aldi_gb.py                    # všechny kategorie
    STORE_URL=... python3 aldi_gb.py fresh-food bakery                     # vybrané (první část adresy)
    STORE_URL=... python3 aldi_gb.py --food
"""
import os
os.environ.setdefault("STORE", "aldi_gb")          # před importem hofer_common

import re
import sys
import time
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_angebote import parse_tiles
from hofer_common import clean, register_source, run_batches
from hofer_listings import fetch_listing

BASE = os.environ.get("STORE_URL", "").rstrip("/")      # jen z DB, v kódu žádná adresa

# slug (kterákoli část cesty, od nejhlubší) -> naše kategorie. Použije se jen tam, kde slova nic nenašla.
# Doplní se podle výpisu kategorií z prvního běhu.
HINTS = {
    "meat-poultry": "maso",
    "fish-seafood": "ryby",
    "cheese": "mlecne_vyrobky",
    "bakery": "pecivo",
    "crisps": "chipsy",
    "chocolate": "cokolady",
    "biscuits": "susenky",
    "sweets": "bonbony",
    "soft-drinks": "napoje",
    "tea-coffee": "kava_caj",
    "beer-cider": "alkohol",
    "wine": "alkohol",
    "spirits": "alkohol",
}
FALLBACK_CATS = {"", "potraviny", "nonfood"}
CAT_PATH = re.compile(r"/products/((?:[^/]+/)*[^/]+)/k/(\d+)")


def source_name(slug):
    return slug.replace("-", "_")


def parse_nav(html):
    """Kategorie z menu -> {cesta: {url, label}}, kde cesta je např. 'fresh-food/meat-poultry'."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path.rstrip("/")
        m = CAT_PATH.fullmatch(path)
        if not m:
            continue
        n = nodes.setdefault(m.group(1), {"url": urljoin(BASE + "/", path), "label": ""})
        n["label"] = n["label"] or clean(a.get_text(" ", strip=True))
    return nodes


def group_tops(nodes):
    """Seskupí cesty podle první části. leaves = cesty, pod kterými už nic dalšího není."""
    tops = {}
    for sp, n in nodes.items():
        top = sp.split("/")[0]
        t = tops.setdefault(top, {"url": "", "label": "", "paths": []})
        if "/" not in sp:
            t["url"], t["label"] = n["url"], n["label"] or t["label"]
        else:
            t["paths"].append(sp)
    for t in tops.values():
        t["leaves"] = [p for p in t["paths"] if not any(q.startswith(p + "/") for q in t["paths"])]
    return tops


def apply_hint(p, path):
    for slug in reversed(path.split("/")):
        hint = HINTS.get(slug)
        if hint:
            if p["category"] in FALLBACK_CATS:
                p["category"] = hint
            return


def top_has_more(session, name, url, seen):
    """Menu nemusí znát všechny podkategorie. Zkontroluje první stránku samotné kategorie: jsou na ní produkty navíc?"""
    r = session.get(url, timeout=60)
    if r.status_code != 200:
        return False
    page = parse_tiles(r.text, name, url, date.today().isoformat(), fallback_valid_from=False)
    return any((p["product_url"] or (p["name"], p["price"])) not in seen for p in page)


def fetch_category(session, name, top, t, nodes):
    pages = [{"path": sp, "url": nodes[sp]["url"], "label": nodes[sp]["label"] or sp.split("/")[-1]} for sp in t["leaves"]]
    if not pages and t["url"]:
        pages = [{"path": top, "url": t["url"], "label": t["label"] or top}]
    products, seen = [], set()
    for ch in pages:
        for p in fetch_listing(session, name, ch["url"], validity=False, default_group=None):
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = ch["label"]
            apply_hint(p, ch["path"])
            products.append(p)
        time.sleep(0.4)
    if t["leaves"] and t["url"] and top_has_more(session, name, t["url"], seen):
        added = 0
        for p in fetch_listing(session, name, t["url"], validity=False, default_group=None):
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = t["label"] or top
            apply_hint(p, top)
            products.append(p)
            added += 1
        print(f"  {name}: stránka kategorie přidala {added} produktů mimo podkategorie z menu")
    return products


def collect(session, opts):
    if not BASE:
        sys.exit("Chybí STORE_URL (stores.url z DB). Spouštěj přes run_stores.py.")
    r = session.get(BASE + "/", timeout=60)
    if r.status_code != 200:
        print(f"Menu UK: status {r.status_code}, nelze pokračovat.")
        return
    nodes = parse_nav(r.text)
    tops = group_tops(nodes)
    print(f"Objeveno z menu UK: {len(nodes)} kategorií, {len(tops)} hlavních")
    for top, t in tops.items():
        leaves = [sp.split("/", 1)[1] for sp in t["leaves"]]
        print(f"  {top}: {len(leaves)} koncových kategorií", leaves[:12])
    wanted = opts["args"] or ["all"]
    if "all" in wanted:
        wanted = list(tops)
    for w in wanted:
        t = tops.get(w)
        if not t or not (t["url"] or t["leaves"]):
            print("Neznámá kategorie:", w, "| nalezené:", list(tops))
            continue
        name = source_name(w)
        register_source(name, "listing")
        print(f"\n=== {name} ===")
        url = t["url"] or nodes[t["leaves"][0]]["url"]
        yield {"source": name, "source_url": url, "label": "", "products": fetch_category(session, name, w, t, nodes)}


if __name__ == "__main__":
    run_batches(collect)
