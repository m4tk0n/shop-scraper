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
from store_cats import Selector, nearest_parent

BASE = os.environ.get("STORE_URL", "").rstrip("/")      # jen z DB, v kódu žádná adresa

# Co se nestahuje. Hlavní kategorie podle první části adresy, podkategorie jako "hlavni/podkategorie".
# Zadáš-li kategorii výslovně na příkazové řádce, platí i když je tady.
SKIP_TOPS = {
    "specialbuys",                  # nepravidelné ne-potraviny (oblečení, DIY, elektro, ...)
    "specially-selected",           # prémiová řada, produkty jsou i v běžných kategoriích
    "higher-protein-food-drink",    # sbírka, produkty jsou i v běžných kategoriích
}
SKIP_LEAVES = set()                 # např. {"home-essentials/batteries", "home-essentials/carrier-bags"}

# slug (kterákoli část cesty, od nejhlubší) -> naše kategorie. Použije se jen tam, kde slova nic nenašla.
HINTS = {
    # čerstvé
    "fruit": "ovoce", "vegetables": "zelenina", "stir-fry-vegetables-sauce-noodles": "hotova_jidla",
    "poultry": "maso", "beef": "maso", "pork-gammon": "maso", "lamb": "maso", "game-venison": "maso",
    "black-pudding-haggis-stuffing": "maso", "bacon-sausages": "uzeniny", "fish": "ryby", "seafood-prawns": "ryby",
    # spíž
    "biscuits-crackers": "susenky", "cereals-snack-bars": "snidane", "chocolate-sweets": "sladkosti",
    "crisps-snacks": "chipsy", "desserts": "sladkosti", "jams-spreads-syrups": "snidane",
    "herbs-spices": "koreni_omacky", "rice-pasta-noodles": "testoviny_ryze", "seeds-nuts-dried-fruits": "orisky",
    "sauces-oils-dressings": "koreni_omacky", "sugar-home-baking": "zakladni_potraviny", "tins-cans-packets": "zakladni_potraviny",
    # chlazené
    "milk": "mlecne_vyrobky", "dairy": "mlecne_vyrobky", "eggs": "mlecne_vyrobky", "cheese": "mlecne_vyrobky",
    "yogurts": "mlecne_vyrobky", "chilled-desserts": "sladkosti", "ready-meals": "hotova_jidla",
    "pizza-pasta-garlic-bread": "hotova_jidla", "sides-starters": "hotova_jidla", "soups": "hotova_jidla",
    "chilled-meats": "uzeniny", "party-food-pies-salads": "hotova_jidla",
    # mražené
    "meat-poultry": "maso", "fish-seafood": "ryby", "chips-potato": "hotova_jidla", "vegetables-sides": "zelenina",
    "pizzas-garlic-bread": "hotova_jidla", "party-food-snacks-pies": "hotova_jidla", "fruit-smoothies": "ovoce",
    "ice-cream-desserts": "zmrzlina", "frozen-vegetarian-food": "hotova_jidla", "frozen-vegetarian": "hotova_jidla",
    "chilled-vegetarian": "hotova_jidla", "chilled-vegan": "hotova_jidla",
    # pečivo
    "bakery": "pecivo", "bread": "pecivo", "bread-rolls": "pecivo", "breakfast-pastries": "pecivo",
    "scones-teacakes": "pecivo", "wraps-naans-pittas-thins": "pecivo", "bagels": "pecivo",
    "cakes": "sladkosti", "sweet-treats": "sladkosti",
    # nápoje
    "alcohol": "alkohol", "beers-ciders": "alkohol", "spirits-liqueurs": "alkohol", "red-wine": "alkohol",
    "rose-wine": "alkohol", "white-wine": "alkohol", "prosecco-champagne-sparkling-wine": "alkohol",
    "port-sherry-fortified-wine": "alkohol", "no-low-alcohol": "napoje",
    "tea": "kava_caj", "coffee": "kava_caj", "hot-chocolate-malted-drinks": "kava_caj",
    "soft-drinks-juices": "napoje", "water": "napoje", "tonic-mixers": "napoje", "plant-based-drinks": "napoje",
    # drogerie a domácnost
    "health-beauty": "hygiena", "baby-toddler": "potraviny", "nappies": "hygiena", "wipes-creams-nappy-sacks": "hygiena",
    "pet-care": "zvirata", "home-essentials": "domacnost", "dishwashing": "uklid", "house-cleaning": "uklid",
    "laundry": "prani", "flowers": "zahrada", "batteries": "technika",
    # sezónní
    "cheeseboard": "mlecne_vyrobky", "starters": "hotova_jidla", "party-food": "hotova_jidla",
    "sides-trimmings-sauces": "hotova_jidla", "desserts-sweet-treats": "sladkosti",
    "halloween-confectionery": "sladkosti", "halloween-drinks": "napoje", "halloween-deli-range": "hotova_jidla",
    "pumpkins": "zelenina", "autumn-drinks": "napoje", "autumn-midweek-meals": "hotova_jidla",
    "autumn-freezer-favourites": "hotova_jidla",
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


def fetch_category(session, name, top, t, nodes, sel):
    # aktivní podle DB (store_categories); SKIP_LEAVES platí jen bez DB
    leaves = [sp for sp in t["leaves"] if sel.active(sp) and (sel.enabled or sp not in SKIP_LEAVES)]
    if t["leaves"] and not leaves:
        return []                                    # všechny podkategorie jsou vypnuté
    skipped = len(leaves) < len(t["leaves"])
    pages = [{"path": sp, "url": nodes[sp]["url"], "label": nodes[sp]["label"] or sp.split("/")[-1]} for sp in leaves]
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
    if t["leaves"] and t["url"] and not skipped and top_has_more(session, name, t["url"], seen):   # při vynechaných podkategoriích se celá stránka nestahuje
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
        print(f"  {top}: {len(leaves)} koncových kategorií", leaves)
    # kategorie obchodu v DB (store_categories): nové se přidají jako aktivní, stahují se jen aktivní
    sel = Selector(session)
    known = set(nodes) | set(tops)
    sync_nodes = [{"path": top, "parent": "", "name": t["label"] or top, "url": t["url"]} for top, t in tops.items()]
    sync_nodes += [{"path": sp, "parent": nearest_parent(sp, known), "name": n["label"] or sp.split("/")[-1], "url": n["url"]}
                   for sp, n in nodes.items() if "/" in sp]
    sel.sync(sync_nodes)
    args = opts["args"]
    if sel.enabled and (not args or "all" in args):
        wanted = [w for w in tops if sel.active(w)]
    else:
        wanted = args or ["all"]
        if "all" in wanted:
            wanted = [w for w in tops if w not in SKIP_TOPS]
            print("Vynechané hlavní kategorie:", sorted(SKIP_TOPS & set(tops)))
    fetch_sel = Selector.disabled(session) if args else sel     # výslovně zadané kategorie se stahují vždy
    for w in wanted:
        t = tops.get(w)
        if not t or not (t["url"] or t["leaves"]):
            print("Neznámá kategorie:", w, "| nalezené:", list(tops))
            continue
        name = source_name(w)
        register_source(name, "listing")
        print(f"\n=== {name} ===")
        url = t["url"] or nodes[t["leaves"][0]]["url"]
        yield {"source": name, "source_url": url, "label": "", "products": fetch_category(session, name, w, t, nodes, fetch_sel)}


if __name__ == "__main__":
    run_batches(collect)
