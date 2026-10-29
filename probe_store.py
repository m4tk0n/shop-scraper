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
# adresy, které naznačují zdroj dat letáku nebo seznamu produktů
URL_HINT = re.compile(r"\.pdf|\.json|/api/|digitalcontent|publitas|issuu|ipaper|flipbook|leaflet|flyer|letak|catalog", re.I)


def dump_hints(html, url):
    """Stránka bez dlaždic: kde by mohla být data (skripty, PDF, JSON, tlačítko Stáhnout, HTML prvního produktu)."""
    soup = BeautifulSoup(html, "html.parser")
    print("\n--- stopy po datech v HTML ---")
    print("title:", (soup.title.string or "")[:80] if soup.title else "-")
    scripts = [urljoin(url, x["src"]) for x in soup.find_all("script", src=True)]
    print(f"skripty se src: {len(scripts)}", scripts[:12])
    for tag, attr in (("a", "href"), ("iframe", "src"), ("link", "href"), ("img", "src"), ("source", "src"), ("embed", "src"), ("object", "data")):
        hit = [urljoin(url, el.get(attr)) for el in soup.find_all(tag) if el.get(attr) and URL_HINT.search(el.get(attr))]
        if hit:
            print(f"{tag}[{attr}] s nápovědou ({len(hit)}):", hit[:8])
    blob = " ".join(x.get_text() for x in soup.find_all("script") if not x.get("src"))
    urls = sorted(set(re.findall(r"https?://[^\s\"'\\<>]+", blob)))
    print(f"inline skripty: {len(blob)} znaků, adres {len(urls)}, s nápovědou:", [u for u in urls if URL_HINT.search(u)][:10])
    for x in soup.find_all("script", type=re.compile("json")):
        print("JSON blok:", x.get("id") or x.get("type"), x.get_text()[:300].replace("\n", " "))
    for el in soup.find_all(["a", "button"]):
        t = el.get_text(" ", strip=True).lower()
        if "stáhnout" in t or "download" in t:
            print("tlačítko:", t, "| href:", el.get("href"), "| atributy:", {k: v for k, v in el.attrs.items() if k != "class"})
    a = soup.find("a", href=re.compile(r"/products/\d+"))
    if a:
        el = a
        for _ in range(4):
            if el.parent is not None and el.parent.name not in ("body", "html"):
                el = el.parent
        print("\nHTML prvního produktu (odkaz /products/<id> a okolí):\n", str(el)[:1800])


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
        print("začátek odpovědi:", r.text[:300].replace("\n", " "))
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
        dump_hints(r.text, url)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    base = sys.argv[1].rstrip("/")
    s = requests.Session(impersonate="chrome")
    overview(s, base)
    for u in sys.argv[2:]:
        test_page(s, u)
