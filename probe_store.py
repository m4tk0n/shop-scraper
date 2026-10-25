"""Sonda nového obchodu: co web nabízí a jestli ho zvládne parse_tiles.

    python3 probe_store.py https://www.hofer.si
    python3 probe_store.py https://www.hofer.si https://www.hofer.si/<stranka-s-produkty> ...

1. běh (jen adresa webu) ukáže strukturu: menu, kategorie, dny, nápovědy.
Další adresy (stránky s produkty) otestují parsování dlaždic a kategorií.
"""
import os
import re
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

os.environ.setdefault("STORE", "hofer_si")      # před importem hofer_common

from bs4 import BeautifulSoup                   # noqa: E402
from curl_cffi import requests                  # noqa: E402

from hofer_angebote import next_page_url, parse_tiles   # noqa: E402

CAT_RE = re.compile(r"/k/\d+")
DAY_RE = re.compile(r"/\d{4}-\d{2}-\d{2}")
HINTS = re.compile(r"flugblatt|letak|katalog|ponudb|akcij|izdelk|produkt|znamk|marke", re.I)


def site_links(base, soup):
    host = urlparse(base).netloc
    out = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base + "/", a["href"]).split("#")[0]
        if urlparse(u).netloc == host and u not in out:
            out.append(u)
    return out


def overview(s, base):
    r = s.get(base + "/", timeout=60)
    print(f"{base}/ -> status {r.status_code}, {len(r.text)} znaků")
    if r.status_code != 200:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    links = site_links(base, soup)
    print(f"odkazů na stejném webu: {len(links)}")
    tops = Counter("/" + urlparse(u).path.strip("/").split("/")[0] for u in links)
    print("první segmenty cest:", dict(tops.most_common(15)))
    for title, rx in (("kategorie /k/<id>", CAT_RE), ("dny /RRRR-MM-DD", DAY_RE), ("nápovědy (letáky, produkty, značky)", HINTS)):
        hit = [u for u in links if rx.search(urlparse(u).path)]
        print(f"\n{title}: {len(hit)}")
        for u in hit[:12]:
            print("  ", u)
    print("\nnadpisy:", [h.get_text(" ", strip=True)[:40] for h in soup.find_all(["h2", "h3"])[:8]])


def test_page(s, url):
    r = s.get(url, timeout=60)
    print(f"\n=== {url}\nstatus {r.status_code}, {len(r.text)} znaků")
    if r.status_code != 200:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    tiles = soup.find_all("div", class_="product-tile")
    print(f"dlaždic product-tile: {len(tiles)} | další strana: {next_page_url(r.text, url) or '-'}")
    prods = parse_tiles(r.text, "probe", url, "")
    print(f"naparsováno produktů: {len(prods)}")
    for f in ("store_product_id", "brand", "name", "amount", "price", "original_price",
              "comparison_price", "image_url", "product_url"):
        print(f"  {f:18} vyplněno {sum(1 for p in prods if p[f])}/{len(prods)}")
    print("  kategorie (podle německých slov):", dict(Counter(p["category"] for p in prods).most_common(6)))
    for p in prods[:6]:
        print("  ", p["brand"], "|", p["name"], "|", p["amount"], p["unit"], "|", p["price"], "|", p["category"])
    if tiles and not prods:
        print("\nprvní dlaždice (nic se nenaparsovalo):\n", str(tiles[0])[:1500])
    elif not tiles:
        cls = Counter(c for el in soup.find_all(class_=True) for c in el["class"] if re.search("product|price|tile|card", c))
        print("žádné product-tile; třídy s product/price/tile/card:", dict(cls.most_common(15)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    base = sys.argv[1].rstrip("/")
    s = requests.Session(impersonate="chrome")
    overview(s, base)
    for u in sys.argv[2:]:
        test_page(s, u)
