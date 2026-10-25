"""ALDI SUISSE (aldi-suisse.ch/de) -> JSON ve stejném schématu jako Hofer (store=aldi_ch, country=CH, currency=CHF).

Co existuje (dny, kategorie), se zjišťuje z menu při každém běhu.

    python3 aldi_ch.py                              # angebote + tiefpreisversprechen + suessigkeiten-snacks
    python3 aldi_ch.py angebote                     # jen denní nabídky
    python3 aldi_ch.py suessigkeiten-snacks fleisch # vybrané kategorie sortimentu (podle adresy)
    python3 aldi_ch.py all                          # celý sortiment (stovky požadavků)
    python3 aldi_ch.py --food                       # bez ne-potravin
"""
import os
os.environ["STORE"] = "aldi_ch"          # musí být nastaveno před importem hofer_common

import re
import time
from datetime import date
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_angebote import collect_days, parse_tiles
from hofer_common import CATEGORIES, STORE_URL, clean, register_source, run_batches
from hofer_discover import find_dates_and_themes
from hofer_listings import fetch_listing

BASE = STORE_URL
NAV_URL = BASE + "/de/"
DEFAULT_SOURCES = ["angebote", "tiefpreisversprechen", "suessigkeiten-snacks"]

# hlavní kategorie, které nejsou potraviny (u ostatních je výchozí kategorie 'potraviny')
NONFOOD_TOPS = {"aktionen", "haushalt-wohnen", "gesundheit-koerperpflege-baby"}
# kategorie podle stromu menu Aldi Suisse -> naše sdílené kategorie (ověřeno proti skutečným názvům v menu)
LEAF_HINTS = {
    # sladkosti
    "schokolade": "cokolady", "riegel": "sladkosti", "gebaeck-guetzli": "susenky", "chips-snacks": "chipsy",
    "trockenfruechte-nuesse": "orisky", "desserts": "sladkosti", "desserts-torten-kuchen": "sladkosti",
    # nápoje
    "mineralwasser": "napoje", "softdrinks": "napoje", "saefte-sirup": "napoje", "funktionsgetraenke-energydrinks": "napoje",
    "alkoholfreie-weine-spirituosen-biere": "napoje", "milchgetraenke": "napoje",
    "kaffee": "kava_caj", "tee": "kava_caj",
    "bier": "alkohol", "rotwein": "alkohol", "rosewein": "alkohol", "weisswein": "alkohol", "schweizer-weine": "alkohol",
    "sekt-schaumwein": "alkohol", "spirituosen": "alkohol", "aperitifs-mixgetraenke": "alkohol",
    # mražené, mléčné, maso, ryby, pečivo
    "glace-sorbets": "zmrzlina",
    "eier": "mlecne_vyrobky", "kaese": "mlecne_vyrobky", "butter-milch-rahm": "mlecne_vyrobky",
    "joghurts-quark-desserts": "mlecne_vyrobky",
    "schwein": "maso", "rind-kalb": "maso", "gefluegel": "maso", "lamm-wild": "maso",
    "charcuterie-wurstwaren": "uzeniny", "frischer-fisch-meeresfruechte": "ryby",
    "aufbackwaren": "pecivo", "frische-backwaren-panetteria-": "pecivo", "toast-abgepacktes-brot": "pecivo",
    "knaeckebrot-zwieback": "pecivo", "brot-aperogebaeck-snacks": "pecivo",
    # snídaně, koření, základní potraviny, hotová jídla
    "honig": "snidane", "brotaufstriche-konfitueren": "snidane", "mueesli-flakes": "snidane", "porridge-haferflocken": "snidane",
    "gewuerze": "koreni_omacky", "dressings-oele-saucen": "koreni_omacky", "grillsaucen-gewuerze": "koreni_omacky",
    "margarine-pflanzliche-fette": "koreni_omacky",
    "backzutaten": "zakladni_potraviny", "grundnahrungsmittel": "zakladni_potraviny",
    "salate-kraeuter": "zelenina",
    "fertiggerichte": "hotova_jidla", "fertiggerichte-pizza": "hotova_jidla", "bouillons-suppen": "hotova_jidla",
    "sandwiches-snacks": "hotova_jidla", "fleischersatzprodukte": "potraviny",
    # ne-potraviny (sekce Aktionen a Haushalt)
    "waschmittel-textilpflege": "prani", "putz-reinigungsmittel": "uklid",
    "tierbedarf": "zvirata", "tiernahrung": "zvirata",
    "gesundheit-apothekenprodukte": "hygiena", "koerperhygiene": "hygiena", "koerperpflege-kosmetik": "hygiena",
    "strumpfwaren": "textil", "bekleidung-accessoires": "textil", "damenbekleidung": "textil", "herrenbekleidung": "textil",
    "kinderbekleidung": "textil", "heimtextilien": "textil", "koffer-taschen": "textil",
    "auto-toeff-velo": "auto", "elektronik": "technika", "batterien-akkus": "technika", "beleuchtung": "technika",
    "garten": "zahrada", "pflanzen-blumen": "zahrada", "spielwaren": "hracky", "outdoor-sport-freizeit": "sport",
    "haushalt": "domacnost", "kueche": "domacnost", "deko-artikel": "domacnost", "haushaltsfolien-beutel": "domacnost",
    "toiletten-kuechenpapier-taschentuecher": "domacnost", "weitere-haushaltsprodukte": "domacnost",
}


# podkategorie, které určují jen skupinu (ne konkrétní kategorii): slova rozhodnou uvnitř skupiny,
# jinak platí náhradní kategorie.  slug -> (skupina, náhradní kategorie)
LEAF_GROUP_HINTS = {"weitere-suessigkeiten": ("sladkosti", "sladkosti")}


def source_name(slug):
    return slug.replace("-", "_")


def parse_nav(html):
    """Dny a kategorie z menu: {'dates', 'themes', 'tops': {slug: {url,label,children:[{slug,url,label}]}}}"""
    soup = BeautifulSoup(html, "html.parser")
    html_days = html.replace("/aktionen-und-angebote/", "/angebote/")          # sdílená funkce hledá /angebote/
    dates, themes = find_dates_and_themes(html_days)
    tops = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path
        m = re.fullmatch(r"/de/produkte/([^/]+)(?:/([^/]+))?/k/(\d+)", path)
        if not m:
            continue
        top, leaf, _ = m.groups()
        label = clean(a.get_text(" ", strip=True))
        if leaf is None:
            tops.setdefault(top, {"url": urljoin(BASE, path), "label": label, "children": []})
        else:
            node = tops.setdefault(top, {"url": "", "label": "", "children": []})
            if not any(c["slug"] == leaf for c in node["children"]):
                node["children"].append({"slug": leaf, "url": urljoin(BASE, path), "label": label})
    return {"dates": dates, "themes": themes, "tops": tops}


def top_has_more(session, name, node, seen, default_group):
    """Menu zná jen část podkategorií (např. Früchte & Gemüse má jen Salate & Kräuter). Zkontroluje první stránku
    samotné kategorie: jsou na ní produkty, které z podkategorií nepřišly?"""
    r = session.get(node["url"], timeout=60)
    if r.status_code != 200:
        return False
    page = parse_tiles(r.text, name, node["url"], date.today().isoformat(),
                       default_group=default_group, fallback_valid_from=False)
    return any((p["product_url"] or (p["name"], p["price"])) not in seen for p in page)


def fetch_category(session, name, top_slug, node):
    """Kategorie sortimentu: podkategorie se stahují zvlášť (kvůli upřesnění kategorie podle menu Aldi Suisse)."""
    default_group = None if top_slug in NONFOOD_TOPS else "food"
    pages = node["children"] or ([{"slug": None, "url": node["url"], "label": node["label"]}] if node["url"] else [])
    products, seen = [], set()
    for ch in pages:
        items = fetch_listing(session, name, ch["url"], default_group=default_group, validity=False)
        for p in items:
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            if ch["slug"]:
                p["theme"] = ch["label"]
                hint = LEAF_HINTS.get(ch["slug"])
                if hint:
                    p["category"] = hint
                elif ch["slug"] in LEAF_GROUP_HINTS:
                    group, fallback = LEAF_GROUP_HINTS[ch["slug"]]
                    if CATEGORIES.get(p["category"], ("", ""))[1] != group:
                        p["category"] = fallback
            products.append(p)
        time.sleep(0.4)
    # produkty mimo podkategorie z menu: stránka kategorie se stáhne celá, jen když na ní něco chybí
    if node["children"] and node["url"] and top_has_more(session, name, node, seen, default_group):
        added = 0
        for p in fetch_listing(session, name, node["url"], default_group=default_group, validity=False):
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = node["label"]
            products.append(p)
            added += 1
        print(f"  {name}: stránka kategorie přidala {added} produktů mimo podkategorie z menu")
    return products


def collect(session, opts):
    r = session.get(NAV_URL, timeout=60)
    if r.status_code != 200:
        print(f"Menu: status {r.status_code}, nelze pokračovat.")
        return
    nav = parse_nav(r.text)
    tops = nav["tops"]
    print("Objeveno z menu:")
    print("  dny:       ", nav["dates"])
    print("  kategorie: ", list(tops))
    wanted = opts["args"] or DEFAULT_SOURCES
    if "all" in wanted:
        wanted = ["angebote"] + list(tops)
    register_source("angebote", "offer")

    if "angebote" in wanted:
        print("\n=== angebote ===")
        yield from collect_days(session, lambda d: f"{BASE}/de/aktionen-und-angebote/{d}", nav["dates"], nav["themes"])
    for w in wanted:
        if w == "angebote":
            continue
        if w not in tops:
            print("Neznámá kategorie:", w, "| nalezené:", list(tops))
            continue
        name = source_name(w)
        register_source(name, "listing")
        print(f"\n=== {name} ===")
        yield {"source": name, "source_url": tops[w]["url"], "label": "", "products": fetch_category(session, name, w, tops[w])}


if __name__ == "__main__":
    run_batches(collect)
