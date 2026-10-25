"""Značky -> produkty z Hofer AT i Aldi Suisse (stránka značky, záloha: hledání s filtrem podle značky).

Seznam značek se stáhne z BRANDS_URL (PHP endpoint znacky.php, token v BRANDS_TOKEN).
Když stažení selže, použije se znacky.txt z repozitáře.
Každý obchod je zvláštní běh (STORE se čte při importu hofer_common), skript je spustí sám jeden po druhém.

    python3 brands_scrape.py                  # oba obchody
    STORE=aldi_ch python3 brands_scrape.py    # jen jeden obchod
    python3 brands_scrape.py HARIBO KÄGI      # jen vybrané značky
"""
import os
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse

SITES = {
    "hofer_at": {"brand": "/marken/{}", "search": "/suchergebnisse?q={}"},
    "aldi_ch": {"brand": "/de/marken/{}", "search": "/de/ergebnisse?q={}"},
}

if __name__ == "__main__" and "STORE" not in os.environ:
    rc = 0
    for s in SITES:
        print(f"\n######## {s} ########", flush=True)
        rc |= subprocess.call([sys.executable, os.path.abspath(__file__), *sys.argv[1:]],
                              env=dict(os.environ, STORE=s))
    sys.exit(1 if rc else 0)

from hofer_common import STORE, STORE_URL, register_source, run_batches   # noqa: E402
from hofer_listings import fetch_listing                       # noqa: E402

SOURCE = "marken"
APOS = "'\u2018\u2019"
TXT_FILE = "znacky.txt"


def bkey(s):
    s = re.sub("['\u2018\u2019`\u00b4]", "'", s or "")
    return re.sub(r"[^a-z0-9äöüßéèàç&']+", " ", s.lower()).strip()


def spellings(name):
    """PIZZ'AH a PIZZ‘AH jsou pro web různé adresy: zkusí se všechny zápisy apostrofu."""
    out = [name]
    if any(c in name for c in APOS):
        out += [re.sub("['\u2018\u2019]", a, name) for a in APOS]
    return list(dict.fromkeys(out))


def page_urls(name, site):
    out = []
    for s in spellings(name):
        for c in (s.upper(), s, s.title()):
            u = site["base"] + site["brand"].format(quote(c, safe=""))
            if u not in out:
                out.append(u)
    return out


def read_txt(path=TXT_FILE):
    """znacky.txt: název nebo adresa (?q=... / poslední část cesty) -> názvy značek bez duplicit."""
    names, seen = [], set()
    if not os.path.exists(path):
        return names
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http"):
            u = urlparse(line)
            q = parse_qs(u.query).get("q")
            line = q[0] if q else unquote(u.path.rstrip("/").split("/")[-1])
        if bkey(line) not in seen:
            seen.add(bkey(line))
            names.append(line)
    return names


def load_brands(session):
    url = os.environ.get("BRANDS_URL", "").strip()
    if url:
        try:
            r = session.get(url, headers={"X-Token": os.environ.get("BRANDS_TOKEN", "")}, timeout=60)
            if r.status_code == 200:
                data = r.json()
                names = [b["brand"] for b in data.get("brands", []) if b.get("brand")]
                if names:
                    print(f"Značky ze serveru: {len(names)} (vygenerováno {data.get('generated_at')}, {data.get('hash', '')[:15]})")
                    return names
                print("Server vrátil prázdný seznam.")
            else:
                print(f"Seznam značek: status {r.status_code}")
        except Exception as e:
            print(f"Seznam značek: chyba ({type(e).__name__})")
    names = read_txt()
    print(f"Záloha {TXT_FILE}: {len(names)} značek")
    return names


def safe_listing(session, url):
    """Jeden spadlý nebo pomalý požadavek nesmí zahodit všechny značky."""
    try:
        return fetch_listing(session, SOURCE, url, pause=0.4, default_group=None)
    except Exception as e:
        print(f"  ! {type(e).__name__}: {str(e)[:80]} ({url})")
        return []


def fetch_brand(session, site, name):
    """-> (adresa, způsob, produkty). Nejdřív stránka značky, pak hledání (jen produkty se shodnou značkou)."""
    for u in page_urls(name, site):
        items = safe_listing(session, u)
        if items:
            return u, "stránka značky", items
    u = site["base"] + site["search"].format(quote_plus(name))
    key = bkey(name)
    items = [p for p in safe_listing(session, u) if bkey(p["brand"]) == key]
    return u, "hledání", items


def collect(session, opts):
    site = {"base": STORE_URL, **SITES[STORE]}
    register_source(SOURCE, "listing")
    names = opts["args"] or load_brands(session)
    if not names:
        print("Žádné značky.")
        return
    products, seen, stats = [], set(), []
    for i, name in enumerate(names, 1):
        print(f"\n[{i}/{len(names)}] {name}")
        url, how, items = fetch_brand(session, site, name)
        new = 0
        for p in items:
            k = p["store_product_id"] or p["product_url"] or (p["brand"], p["name"])
            if k in seen:
                continue
            seen.add(k)
            p["theme"] = name                          # ze které značky produkt pochází
            products.append(p)
            new += 1
        stats.append((name, how, len(items), new))
        time.sleep(0.4)

    print(f"\nShrnutí značek ({STORE}):")
    for name, how, n, new in stats:
        print(f"  {name[:24]:24} {how if n else 'NENALEZENO':15} {n:3} produktů ({new} nových)")
    yield {"source": SOURCE, "source_url": site["base"] + site["brand"].format("").rstrip("/"),
           "label": "", "products": products}


if __name__ == "__main__":
    run_batches(collect)
