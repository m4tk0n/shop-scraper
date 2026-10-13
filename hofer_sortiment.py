"""Hofer sortiment (hofer.at/produkte/<kategorie>/...): kategorie, které web člení sám (maso, uzeniny, mléčné, pečivo, ryby).

Kategorie a podkategorie se zjišťují z menu při každém běhu. Kategorie z webu mají přednost před hádáním podle názvu.

    python3 hofer_sortiment.py                         # všechny kategorie sortimentu
    python3 hofer_sortiment.py fleisch-und-wurstwaren  # jen vybraná (podle adresy)
    python3 hofer_sortiment.py --food
"""
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_common import clean, register_source, run_batches
from hofer_discover import BASE, NAV_URL
from hofer_listings import fetch_listing

# podkategorie z menu hofer.at -> naše sdílené kategorie
LEAF_HINTS = {
    "wuerstel": "uzeniny", "wurst-und-wurstwaren": "uzeniny",
    "faschiertes": "maso", "rind": "maso", "schwein": "maso", "gefluegel": "maso",
    "fruchtjoghurt-und-desserts": "mlecne_vyrobky", "kaese-und-aufstriche": "mlecne_vyrobky",
    "schlagobers-und-butter": "mlecne_vyrobky", "joghurt-und-topfen": "mlecne_vyrobky",
    "milch-und-milchgetraenke": "mlecne_vyrobky",
    "suesse-backwaren": "sladkosti", "brot-und-gebaeck": "pecivo", "backbox": "pecivo",
}
TOP_HINTS = {"fisch-und-meeresfruechte": "ryby"}          # kategorie bez podkategorií


def source_name(slug):
    return slug.replace("-", "_")


def parse_tree(html):
    """Kategorie sortimentu z menu: {slug: {url, label, children:[{slug,url,label}]}}.
    Akční sekce (Preiswochen, Dauerhaft, Grillen, Weihnachten...) se vynechají, ty řeší hofer_listings."""
    soup = BeautifulSoup(html, "html.parser")
    tops = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path
        m = re.fullmatch(r"/produkte/([^/]+)(?:/([^/]+))?/k/(\d+)", path)
        if not m:
            continue
        top, leaf, cid = m.groups()
        label = clean(a.get_text(" ", strip=True))
        node = tops.setdefault(top, {"url": "", "label": "", "id": "", "children": []})
        if leaf is None:
            node.update(url=urljoin(BASE, path), label=label, id=cid)
        elif not any(c["slug"] == leaf for c in node["children"]):
            node["children"].append({"slug": leaf, "url": urljoin(BASE, path), "label": label})
    # běžný katalog = kategorie s podkategoriemi a kategorie se stejně dlouhým ID (akční sekce mají kratší ID)
    ref = max((len(n["id"]) for n in tops.values() if n["children"]), default=0)
    return {s: n for s, n in tops.items() if n["url"] and (n["children"] or len(n["id"]) >= ref)}


def fetch_category(session, name, top_slug, node):
    pages = node["children"] or [{"slug": None, "url": node["url"], "label": node["label"]}]
    products, seen = [], set()
    for ch in pages:
        for p in fetch_listing(session, name, ch["url"], default_group="food", validity=False):
            k = p["product_url"] or (p["name"], p["price"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = ch["label"] if ch["slug"] else ""
            hint = LEAF_HINTS.get(ch["slug"]) if ch["slug"] else TOP_HINTS.get(top_slug)
            if hint:
                p["category"] = hint
            products.append(p)
        time.sleep(0.4)
    return products


def collect(session, opts):
    r = session.get(NAV_URL, timeout=60)
    if r.status_code != 200:
        print(f"Menu: status {r.status_code}, nelze pokračovat.")
        return
    tops = parse_tree(r.text)
    print("Sortiment z menu:", {s: len(n["children"]) for s, n in tops.items()})
    for slug, node in tops.items():
        if opts["args"] and slug not in opts["args"]:
            continue
        name = source_name(slug)
        register_source(name, "listing")
        print(f"\n=== {name} ===")
        yield {"source": name, "source_url": node["url"], "label": "", "products": fetch_category(session, name, slug, node)}


if __name__ == "__main__":
    run_batches(collect)
