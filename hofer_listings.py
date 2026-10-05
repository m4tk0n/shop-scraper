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
from hofer_common import register_source, run_batches
from hofer_discover import get_discovery

MAX_PAGES = 30


def parse_validity(text, today=None):
    """'... von Mi. 2.9. bis Mi. 30.9.' -> ('2026-09-02', '2026-09-30') nebo ('', '')."""
    today = today or date.today()
    m = re.search(
        r"von\s+(?:[A-Za-zäöü]{2}\.\s*)?(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?\s*bis\s+(?:[A-Za-zäöü]{2}\.\s*)?(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?",
        text or "", re.I)
    if not m:
        return "", ""
    d1, m1, y1, d2, m2, y2 = m.groups()
    y_to = int(y2) if y2 else today.year
    y_from = int(y1) if y1 else y_to
    if not y1 and int(m1) > int(m2):
        y_from = y_to - 1
    return f"{y_from}-{int(m1):02d}-{int(d1):02d}", f"{y_to}-{int(m2):02d}-{int(d2):02d}"


def next_url(html, current):
    a = BeautifulSoup(html, "html.parser").select_one("a[data-test=next-page]")
    return urljoin(current, a["href"]) if a and a.get("href") else None


def fetch_listing(session, name, base_url, pause=0.5, default_group="food"):
    items, seen, page_no, url = [], set(), 0, base_url
    valid_from = valid_to = ""
    today = date.today().isoformat()
    while url and page_no < MAX_PAGES:
        page_no += 1
        r = session.get(url, timeout=60)
        if r.status_code != 200:
            print(f"  ! {name}: status {r.status_code} ({url})")
            break
        if page_no == 1:
            valid_from, valid_to = parse_validity(BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        page = parse_tiles(r.text, name, base_url, today, default_group=default_group, fallback_valid_from=False)
        new = 0
        for p in page:
            key = p["product_url"] or (p["name"], p["price"])
            if key in seen:
                continue
            seen.add(key)
            if not p["valid_from"]:
                p["valid_from"] = valid_from
            p["valid_to"] = valid_to
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
