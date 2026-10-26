"""ALDI UK (aldi.co.uk) -> JSON ve stejném schématu jako ostatní obchody.

Adresa webu se bere z DB (stores.url) přes proměnnou STORE_URL.
"""
import os
os.environ.setdefault("STORE", "aldi_gb")

import re
import sys
import time
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_angebote import parse_tiles
from hofer_common import clean, register_source, run_batches
from hofer_listings import fetch_listing

BASE = os.environ.get("STORE_URL", "").rstrip("/")
DEFAULT_SOURCES = ["groceries"]

# Přímé kategorie pro Aldi UK, pokud selže parsování menu z úvodní stránky
DIRECT_SOURCES = {
    "groceries": "c/groceries",
    "fresh-food": "c/groceries/fresh-food",
    "dairy-eggs": "c/groceries/dairy-eggs",
    "pantry": "c/groceries/pantry",
    "bakery": "c/groceries/bakery",
    "snacks": "c/groceries/snacks",
    "drinks": "c/groceries/drinks",
    "alcohol": "c/groceries/alcohol",
}

HINTS = {
    "fresh-food": "maso",
    "dairy-eggs": "mlecne_vyrobky",
    "pantry": "zakladni_potraviny",
    "bakery": "pecivo",
    "snacks": "sladkosti",
    "drinks": "napoje",
    "alcohol": "alkohol",
    "freezer": "potraviny",
    "household": "domacnost",
    "health-beauty": "hygiena",
}
FALLBACK_CATS = {"", "potraviny", "nonfood"}


def source_name(slug):
    return slug.replace("-", "_")


def apply_hint(p, slug):
    hint = HINTS.get(slug)
    if hint and p["category"] in FALLBACK_CATS:
        p["category"] = hint


def collect(session, opts):
    if not BASE:
        sys.exit("Chybí STORE_URL (stores.url z DB). Spouštěj přes run_stores.py.")
    
    wanted = opts["args"] or DEFAULT_SOURCES
    if "all" in wanted:
        wanted = list(DIRECT_SOURCES.keys())

    for w in wanted:
        path = DIRECT_SOURCES.get(w, f"c/groceries/{w}")
        target_url = f"{BASE}/{path}"
        name = source_name(w)
        register_source(name, "listing")
        
        print(f"\n=== Stažení kategorie: {name} ({target_url}) ===")
        items = fetch_listing(session, name, target_url, default_group="food", validity=False)
        
        if not items:
            print(f"  ! Žádné produkty nenalezeny pro {w}, zkouším alternativní cestu...")
            # Případný pokus o širší výpis, pokud hlavní cesta selže
            
        for p in items:
            apply_hint(p, w)
            
        if items:
            yield {"source": name, "source_url": target_url, "label": "", "products": items}
        time.sleep(0.4)


if __name__ == "__main__":
    run_batches(collect)
