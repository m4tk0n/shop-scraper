"""HOFER SLOVENIJA (hofer.si) -> JSON ve stejném schématu jako ostatní obchody.

Adresa webu se bere z DB (stores.url) přes proměnnou STORE_URL, nastavuje ji run_stores.py.
Co existuje (dny, kategorie), se zjišťuje z menu při každém běhu.

    STORE_URL=https://www.hofer.si python3 hofer_si.py                       # výchozí zdroje
    STORE_URL=... python3 hofer_si.py angebote meso-mesni-izdelki-in-ribe    # vybrané (kategorie podle adresy)
    STORE_URL=... python3 hofer_si.py all                                    # celý sortiment
    STORE_URL=... python3 hofer_si.py --food                                 # bez ne-potravin
"""
import os
os.environ.setdefault("STORE", "hofer_si")          # před importem hofer_common

import re
import sys
import time
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_angebote import collect_days, parse_tiles
from hofer_common import clean, register_source, run_batches
from hofer_discover import find_dates_and_themes
from hofer_listings import fetch_listing

BASE = os.environ.get("STORE_URL", "").rstrip("/")      # jen z DB, v kódu žádná adresa
DEFAULT_SOURCES = ["angebote", "vse-spuscene-cene", "pregled-posebne-ponudbe"]

# sekce, které nejsou běžný sortiment: slug -> typ zdroje (offer = akce, listing = katalog)
SPECIAL = {"vse-spuscene-cene": "listing", "pregled-posebne-ponudbe": "offer", "novo": "listing",
           "kakovost-iz-slovenije": "listing", "vse-za-zar": "listing"}

# slug z menu (kategorie nebo podkategorie) -> naše kategorie. Použije se jen tam, kde slova nic nenašla.
# Další slugy se doplní podle výpisu menu z prvního běhu.
HINTS = {
    "meso-mesni-izdelki-in-ribe": "maso",
    "mleko-mlecni-izdelki-in-jajca": "mlecne_vyrobky",
    "testenine-riz-in-strocnice": "testoviny_ryze",
    "omake-olja-kis-in-zacimbe": "koreni_omacky",
    "konzervirana-hrana-in-pripravljeni-obroki": "hotova_jidla",
    "zamrznjeni-izdelki": "potraviny",
    "sladoledi-in-sorbeti": "zmrzlina",
}
FALLBACK_CATS = {"", "potraviny", "nonfood"}


def source_name(slug):
    return slug.replace("-", "_")


def parse_nav(html):
    """Dny a kategorie z menu: {'dates', 'themes', 'tops': {slug: {url,label,children:[{slug,url,label}]}}}"""
    soup = BeautifulSoup(html, "html.parser")
    html_days = html.replace("/posebna-ponudba/", "/angebote/")             # sdílená funkce hledá /angebote/
    dates, themes = find_dates_and_themes(html_days)
    tops = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path
        m = re.fullmatch(r"/izdelki/([^/]+)(?:/([^/]+))?/k/(\d+)", path)
        if not m:
            continue
        top, leaf, _ = m.groups()
        label = clean(a.get_text(" ", strip=True))
        node = tops.setdefault(top, {"url": "", "label": "", "children": []})
        if leaf is None:
            node["url"] = urljoin(BASE + "/", path)
            node["label"] = label or node["label"]
        elif not any(c["slug"] == leaf for c in node["children"]):
            node["children"].append({"slug": leaf, "url": urljoin(BASE + "/", path), "label": label or leaf})
    return {"dates": dates, "themes": themes, "tops": tops}


def top_has_more(session, name, node, seen, default_group):
    """Menu zná jen část podkategorií. Zkontroluje první stránku samotné kategorie: jsou na ní produkty navíc?"""
    r = session.get(node["url"], timeout=60)
    if r.status_code != 200:
        return False
    page = parse_tiles(r.text, name, node["url"], date.today().isoformat(),
                       default_group=default_group, fallback_valid_from=False)
    return any((p["product_url"] or (p["name"], p["price"])) not in seen for p in page)


def apply_hint(p, slug):
    hint = HINTS.get(slug)
    if hint and p["category"] in FALLBACK_CATS:
        p["category"] = hint


def fetch_category(session, name, top_slug, node):
    """Kategorie: podkategorie se stahují zvlášť (kvůli upřesnění kategorie podle menu)."""
    pages = node["children"] or ([{"slug": None, "url": node["url"], "label": node["label"]}] if node["url"] else [])
    products, seen = [], set()
    for ch in pages:
        food = top_slug in HINTS or ch["slug"] in HINTS
        items = fetch_listing(session, name, ch["url"], default_group="food" if food else None, validity=False)
        for p in items:
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = ch["label"] if ch["slug"] else ""
            apply_hint(p, ch["slug"] or top_slug)
            if ch["slug"]:
                apply_hint(p, top_slug)
            products.append(p)
        time.sleep(0.4)
    if node["children"] and node["url"] and top_has_more(session, name, node, seen, "food" if top_slug in HINTS else None):
        added = 0
        for p in fetch_listing(session, name, node["url"], default_group="food" if top_slug in HINTS else None, validity=False):
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = node["label"]
            apply_hint(p, top_slug)
            products.append(p)
            added += 1
        print(f"  {name}: stránka kategorie přidala {added} produktů mimo podkategorie z menu")
    return products


def collect(session, opts):
    if not BASE:
        sys.exit("Chybí STORE_URL (stores.url z DB). Spouštěj přes run_stores.py.")
    r = session.get(BASE + "/", timeout=60)
    if r.status_code != 200:
        print(f"Menu: status {r.status_code}, nelze pokračovat.")
        return
    nav = parse_nav(r.text)
    tops = nav["tops"]
    print("Objeveno z menu:")
    print("  dny:       ", nav["dates"])
    print("  kategorie: ", {s: len(n["children"]) for s, n in tops.items()})
    wanted = opts["args"] or DEFAULT_SOURCES
    if "all" in wanted:
        wanted = ["angebote"] + list(tops)
    register_source("angebote", "offer")

    if "angebote" in wanted:
        print("\n=== angebote ===")
        yield from collect_days(session, lambda d: f"{BASE}/posebna-ponudba/{d}", nav["dates"], nav["themes"])
    for w in wanted:
        if w == "angebote":
            continue
        node = tops.get(w)
        if not node or not (node["url"] or node["children"]):
            print("Neznámá kategorie:", w, "| nalezené:", list(tops))
            continue
        name = source_name(w)
        register_source(name, SPECIAL.get(w, "listing"))
        print(f"\n=== {name} ===")
        url = node["url"] or node["children"][0]["url"]
        yield {"source": name, "source_url": url, "label": "", "products": fetch_category(session, name, w, node)}


if __name__ == "__main__":
    run_batches(collect)
