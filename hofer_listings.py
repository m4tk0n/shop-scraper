"""Hofer akční a sezónní sekce (/produkte/...) se stránkováním -> jeden JSON na sekci.

Které sekce existují, se zjišťuje z menu při každém běhu (Preiswochen, Dauerhaft,
Weihnachten, Ostern, Grillen, ...).

    python3 hofer_listings.py                 # všechny nalezené sekce
    python3 hofer_listings.py dauerhaft       # jen vybraná (podle názvu)
    python3 hofer_listings.py https://www.hofer.at/produkte/neco/k/123   # vlastní adresa
    python3 hofer_listings.py --food
"""
import re
import time
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_angebote import parse_tiles
from hofer_common import parse_validity, register_source, run_batches
from hofer_discover import get_discovery

MAX_PAGES = 30


def next_url(html, current):
    a = BeautifulSoup(html, "html.parser").select_one("a[data-test=next-page]")
    return urljoin(current, a["href"]) if a and a.get("href") else None


def fetch_listing(session, name, base_url, pause=0.5, default_group="food", validity=True):
    """validity=False: katalogové stránky (sortiment, značky), kde text stránky platnost akce neříká."""
    items, seen, page_no, url = [], set(), 0, base_url
    valid_from = valid_to = ""
    today = date.today().isoformat()
    while url and page_no < MAX_PAGES:
        page_no += 1
        r = session.get(url, timeout=60)
        if r.status_code != 200:
            print(f"  ! {name}: status {r.status_code} ({url})")
            break
        if page_no == 1 and validity:
            valid_from, valid_to = parse_validity(BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        page = parse_tiles(r.text, name, base_url, today, default_group=default_group, fallback_valid_from=False)
        new = 0
        for p in page:
            key = p["product_url"] or (p["name"], p["price"])
            if key in seen:
                continue
            seen.add(key)
            own = p["valid_from"]                       # 'Verfügbar ab' u produktu má přednost
            if valid_to and not p["valid_to"] and (not own or valid_from <= own <= valid_to):
                p["valid_to"] = valid_to
                p["valid_from"] = own or valid_from
                p["validity_source"], p["validity_confidence"] = "product_group", "verified"
            items.append(p)
            new += 1
        print(f"  {name} strana {page_no}: {len(page)} dlaždic, nových {new}")
        nxt = next_url(r.text, url)
        if not new or nxt == url:
            break
        url = nxt
        time.sleep(pause)
    return items


def collect(session, opts):
    sections = dict(get_discovery(session, opts)["sections"])
    chosen = {}
    for a in opts["args"]:
        if a.startswith("http"):                       # vlastní adresa
            slug = [s for s in urlparse(a).path.split("/") if s and s != "k" and not s.isdigit()][-1]
            n = slug.replace("-", "_")
            register_source(n, "listing")
            chosen[n] = a
        elif a in sections:
            chosen[a] = sections[a]
        else:
            print("Neznámá sekce:", a, "| nalezené:", list(sections))
    if not opts["args"]:
        chosen = sections
    for n, url in chosen.items():
        print(f"\n=== {n} ===")
        yield {"source": n, "source_url": url, "label": "", "products": fetch_listing(session, n, url)}


if __name__ == "__main__":
    run_batches(collect)
