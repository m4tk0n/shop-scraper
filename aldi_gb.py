"""ALDI UK (aldi.co.uk) -> JSON ve stejném schématu jako ostatní obchody.

Zjišťuje kategorie dynamicky z menu na úvodní stránce.
"""
import os
os.environ.setdefault("STORE", "aldi_gb")

import re
import sys
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_common import clean, register_source, run_batches
from hofer_listings import fetch_listing

BASE = os.environ.get("STORE_URL", "").rstrip("/")
DEFAULT_SOURCES = ["groceries"]

HINTS = {
    "fresh-food": "maso",
    "meat-poultry": "maso",
    "fish-seafood": "ryby",
    "dairy-eggs": "mlecne_vyrobky",
    "milk-butter-eggs": "mlecne_vyrobky",
    "cheese": "mlecne_vyrobky",
    "bakery": "pecivo",
    "snacks": "sladkosti",
    "crisps": "chipsy",
    "chocolate": "cokolady",
    "biscuits": "susenky",
    "sweets": "bonbony",
    "drinks": "napoje",
    "soft-drinks": "napoje",
    "tea-coffee": "kava_caj",
    "alcohol": "alkohol",
    "beer-cider": "alkohol",
    "wine": "alkohol",
    "spirits": "alkohol",
    "pantry": "zakladni_potraviny",
    "fruit-veg": "zelenina",
    "household": "domacnost",
    "health-beauty": "hygiena",
}
FALLBACK_CATS = {"", "potraviny", "nonfood"}


def source_name(slug):
    return slug.replace("-", "_")


def parse_nav(html):
    soup = BeautifulSoup(html, "html.parser")
    tops = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path
        m = re.fullmatch(r"/c/(?:groceries/)?([^/]+)(?:/([^/]+))?", path)
        if not m:
            continue
        top, leaf = m.groups()
        label = clean(a.get_text(" ", strip=True))
        node = tops.setdefault(top, {"url": "", "label": "", "children": []})
        if leaf is None:
            node["url"] = urljoin(BASE + "/", path)
            node["label"] = label or node["label"]
        elif not any(c["slug"] == leaf for c in node["children"]):
            node["children"].append({"slug": leaf, "url": urljoin(BASE + "/", path), "label": label or leaf})
    return {"tops": tops}


def apply_hint(p, slug):
    hint = HINTS.get(slug)
    if hint and p["category"] in FALLBACK_CATS:
        p["category"] = hint


def fetch_category(session, name, top_slug, node):
    pages = node["children"] or ([{"slug": None, "url": node["url"], "label": node["label"]}] if node["url"] else [])
    products, seen = [], set()
    for ch in pages:
        items = fetch_listing(session, name, ch["url"], default_group="food", validity=False)
        for p in items:
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = ch["label"] if ch["slug"] else ""
            apply_hint(p, ch["slug"] or top_slug)
            products.append(p)
        time.sleep(0.4)
    return products


def collect(session, opts):
    if not BASE:
        sys.exit("Chybí STORE_URL (stores.url z DB). Spouštěj přes run_stores.py.")
    
    r = session.get(BASE + "/", timeout=60)
    tops = {}
    if r.status_code == 200:
        nav = parse_nav(r.text)
        tops = nav["tops"]
        print("Objeveno z menu UK (dynamicky):", list(tops))
    else:
        print(f"Menu UK: status {r.status_code}")

    wanted = opts["args"] or DEFAULT_SOURCES
    if "all" in wanted:
        wanted = list(tops.keys())

    for w in wanted:
        node = tops.get(w)
        if not node or not (node["url"] or node["children"]):
            print(f"  ! Kategorie '{w}' nebyla v dynamickém menu nalezena, přeskakuji.")
            continue

        name = source_name(w)
        register_source(name, "listing")
        print(f"\n=== {name} ===")
        yield {
            "source": name, 
            "source_url": node["url"] or (node["children"][0]["url"] if node["children"][0] else BASE), 
            "label": "", 
            "products": fetch_category(session, name, w, node)
        }


if __name__ == "__main__":
    run_batches(collect)
