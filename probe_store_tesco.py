"""Sonda nového obchodu: co web nabízí a jestli ho zvládne parse_tiles.

    python3 probe_store.py https://www.hofer.si
    python3 probe_store.py https://www.hofer.si https://www.hofer.si/<stranka-s-produkty> ...

1. běh (jen adresa webu) ukáže strukturu: menu, kategorie, dny, nápovědy.
Další adresy (stránky s produkty) otestují parsování dlaždic a kategorií.
"""
import json
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


def outline(o, path="", depth=0, out=None, maxdepth=7):
    """Stručná osnova JSON: cesty, typy, délky a krátké ukázky hodnot (config se přeskakuje)."""
    out = out if out is not None else []
    if len(out) > 150:
        return out
    if isinstance(o, dict):
        for k, v in list(o.items())[:30]:
            if k in ("config", "_nextI18Next", "header", "footer", "footerConfig", "cookieBanner", "marcom", "__APOLLO_STATE__"):
                continue
            p = f"{path}.{k}"
            if isinstance(v, (dict, list)):
                out.append(f"{p} {type(v).__name__}[{len(v)}]")
                if depth < maxdepth:
                    outline(v, p, depth + 1, out, maxdepth)
            else:
                out.append(f"{p} = {str(v)[:70]!r}")
    elif isinstance(o, list) and o:
        outline(o[0], path + "[0]", depth + 1, out, maxdepth)
    return out


def apollo_summary(state):
    """Vypíše typy Apollo cache a podrobnosti důležité pro letáky, nabídky a produkty."""
    print("\n--- __APOLLO_STATE__ (GraphQL cache) ---")
    groups = {}
    for k, v in state.items():
        t = (v.get("__typename") if isinstance(v, dict) else None) or k.split(":")[0]
        groups.setdefault(t, []).append((k, v))
    for t, items in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
        print(f"{t}: {len(items)}x")

    interesting = re.compile(r"leaflet|offer|promotion|product|price|brand|article|campaign|metadata.?page", re.I)
    print("\n--- podrobné záznamy Apollo pro leták/produkty ---")
    shown = 0
    for t, items in sorted(groups.items()):
        if not interesting.search(t):
            continue
        for k, v in items[:12]:
            if not isinstance(v, dict):
                continue
            print(f"{k}: {json.dumps(v, ensure_ascii=False)[:3500]}")
            shown += 1
            if shown >= 35:
                print("Další záznamy vynechány (limit 35).")
                break
        if shown >= 35:
            break

    root = state.get("ROOT_QUERY")
    if isinstance(root, dict):
        print("\n--- ROOT_QUERY: relevantní klíče a vazby ---")
        for key, value in root.items():
            if interesting.search(key):
                print(f"{key}: {json.dumps(value, ensure_ascii=False)[:2500]}")
        print("Všechny ROOT_QUERY klíče:", [k[:220] for k in root.keys()][:60])

    urls = set()
    for _, v in state.items():
        if isinstance(v, dict):
            for field in ("leafletUrl", "pagePNG", "pdfUrl", "imageUrl", "url"):
                value = v.get(field)
                if isinstance(value, str) and value.startswith("http"):
                    urls.add((field, value))
    if urls:
        print("\n--- nalezené URL souborů ---")
        for field, value in sorted(urls):
            print(f"{field}: {value}")


def tile_container(el):
    """Nejmenší předek, který obsahuje odkaz na produkt i tlačítko Přidat = celá dlaždice."""
    cur = el
    for _ in range(14):
        if cur.parent is None:
            return None
        cur = cur.parent
        if cur.find(class_=re.compile("add-button")) and cur.find("a", href=re.compile(r"/products/\d+")):
            return cur
    return None


def short_html(el, limit=5500):
    h = re.sub(r"<svg.*?</svg>", "<svg/>", str(el), flags=re.S)
    return h[:limit]


def dump_hints(html, url):
    """Stránka bez dlaždic: kde by mohla být data (skripty, PDF, JSON, tlačítko Stáhnout, HTML prvního produktu)."""
    soup = BeautifulSoup(html, "html.parser")
    print("\n--- stopy po datech v HTML ---")
    print("title:", (soup.title.string or "")[:80] if soup.title else "-")
    scripts = [urljoin(url, x["src"]) for x in soup.find_all("script", src=True)]
    print(f"skripty se src: {len(scripts)}", scripts[:3])
    for tag, attr in (("a", "href"), ("iframe", "src"), ("link", "href"), ("img", "src"), ("source", "src"), ("embed", "src"), ("object", "data")):
        hit = [urljoin(url, el.get(attr)) for el in soup.find_all(tag) if el.get(attr) and URL_HINT.search(el.get(attr))]
        if hit:
            print(f"{tag}[{attr}] s nápovědou ({len(hit)}):", hit[:2])
    blob = " ".join(x.get_text() for x in soup.find_all("script") if not x.get("src"))
    urls = sorted(set(re.findall(r"https?://[^\s\"'\\<>]+", blob)))
    print(f"inline skripty: {len(blob)} znaků, adres {len(urls)}, s nápovědou:", [u for u in urls if URL_HINT.search(u)][:4])
    for x in soup.find_all("script", type=re.compile("json")):
        print("JSON blok:", x.get("id") or x.get("type"), x.get_text()[:80].replace("\n", " "))
    for el in soup.find_all(["a", "button"]):
        t = el.get_text(" ", strip=True).lower()
        if "stáhnout" in t or "download" in t:
            print("tlačítko:", t, "| href:", el.get("href"), "| atributy:", {k: v for k, v in el.attrs.items() if k != "class"})
    # Next.js / Apollo: nejdřív běžná cesta, potom hledání cache i v dalších JSON skriptech.
    apollo_found = False
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd:
        try:
            data = json.loads(nd.get_text())
            print("\n--- osnova __NEXT_DATA__ ---")
            print("\n".join(outline(data)))
            state = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__")
            if isinstance(state, dict):
                apollo_summary(state)
                apollo_found = True
        except Exception as e:
            print("__NEXT_DATA__ nejde přečíst:", type(e).__name__)

    if not apollo_found:
        for tag in soup.find_all("script"):
            raw = tag.string or tag.get_text()
            if not raw or "__APOLLO_STATE__" not in raw:
                continue
            try:
                candidate = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            stack = [candidate]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    state = node.get("__APOLLO_STATE__")
                    if isinstance(state, dict):
                        apollo_summary(state)
                        apollo_found = True
                        break
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
            if apollo_found:
                break

    if not apollo_found:
        print("\n__APOLLO_STATE__ nebyl nalezen jako samostatně parsovatelný objekt.")
    if soup.find("a", href=re.compile(r"/products/\d+")):
        print("\n--- dlaždice produktů ---")
        sash = soup.find(class_=re.compile("special-offer-sash"))
        plain = None
        for h in soup.find_all(class_=re.compile("product-tile-product-heading")):
            c = tile_container(h)
            if c is not None and not c.find(class_=re.compile("special-offer-sash")):
                plain = c
                break
        for label, el in (("se slevou", tile_container(sash) if sash else None), ("bez slevy", plain)):
            if el is not None:
                print(f"\nDLAŽDICE {label}:\n", short_html(el))
        for pat in ("price__text", "unit-price__subtext", "promotion__wrapper", "special-offer-sash"):
            texts = [x.get_text(" ", strip=True) for x in soup.find_all(class_=re.compile(pat))][:4]
            print(f"texty *{pat}*:", texts)
        print("odkazy na stránkování:", [x["href"] for x in soup.find_all("a", href=re.compile(r"[?&]page="))][:5])


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
