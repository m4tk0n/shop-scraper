"""Dlaždice produktů (Hofer i Aldi Suisse): parsování, stránkování, denní nabídky -> jeden JSON na den.

    python3 hofer_angebote.py                  # všechny dny z menu hofer.at
    python3 hofer_angebote.py 2026-10-02       # jen vybrané dny
    python3 hofer_angebote.py --food           # jen potraviny/nápoje/sladkosti
"""
import re
import sys
import time
from datetime import date
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from hofer_common import STORE_URL
from hofer_discover import get_discovery

BASE = STORE_URL
MAX_PAGES = 30
COMP_RE = re.compile(r"(?:€|CHF)?\s*((?:\d{1,3}(?:[.'’]\d{3})+|\d+)[,.]\d{2})\s*/\s*([\d.,]*\s*[A-Za-z]+)")
AVAIL_RE = re.compile(r"verfügbar\s+(?:seit|ab)\s+(\d{2})\.(\d{2})\.(\d{4})", re.I)


def text(el, sel):
    e = el.select_one(sel)
    return clean(e.get_text(" ", strip=True)) if e else ""


def pick_image(t):
    """Fotka produktu. Dlaždice mívají i vlajku/štítek (overlay-badges), ty se přeskakují."""
    for img in t.select(".product-tile__picture img"):
        src = img.get("src") or img.get("data-src") or ""
        if src and not src.endswith(".svg") and "overlay-badges-image__image" not in (img.get("class") or []):
            return src
    for img in t.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if (src and not src.endswith(".svg") and "Flagge" not in src
                and not img.find_parent(class_=re.compile("overlay-badges|energy-label"))
                and "overlay-badges-image__image" not in (img.get("class") or [])):
            return src
    return ""


def tile_to_product(t, source, source_url, source_date, theme="", default_group=None, fallback_valid_from=True):
    a = t.find("a")
    href = a.get("href", "") if a else ""
    pid = re.search(r"(\d{6,})$", href.split("?")[0])
    brand = text(t, ".product-tile__brandname")
    name = text(t, ".product-tile__name") or clean(t.get("title", ""))
    amount, unit, atg, approx = parse_size(text(t, ".product-tile__unit-of-measurement"))

    box = t.select_one("[data-test=product-tile__price]")
    cur = original = deposit = per = deposit_type = ""
    if box:
        ins = box.select_one("ins.base-price__discounted")
        if ins:
            cur = price(ins.get_text())
            d = box.select_one(".base-price__was-price del")
            original = price(d.get_text()) if d else ""
        else:
            reg = box.select_one(".base-price__regular > span:not(.base-price__superscript)")
            cur = price(reg.get_text() if reg else box.get_text())
        iv = box.select_one(".base-price__interval")
        per = clean(iv.get_text()).lstrip("/ ") if iv else ""
        dep = box.select_one(".base-price__deposit")
        if dep:
            deposit = price(dep.get_text())
            low = dep.get_text().lower()
            deposit_type = "EINWEG" if "einweg" in low else ("MEHRWEG" if "mehrweg" in low else "")
    if not amount and per:                       # cena platí za např. 0,5 kg
        a2, u2, _, _ = parse_size(per)
        amount, unit = a2, u2

    cm = COMP_RE.search(text(t, ".product-tile__comparison-price"))
    badges = [clean(b.get_text(" ", strip=True)) for b in t.select(".product-tile__badges .base-label")]
    ttxt = clean(t.get_text(" ", strip=True))
    dm = AVAIL_RE.search(ttxt)
    valid_from = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else (source_date if fallback_valid_from else "")
    valid_to = parse_until(ttxt)                  # 'gültig bis …' přímo u produktu (zatím nespatřeno, jen pojistka)
    if valid_to:
        vsrc, vconf = "product", "verified"
    elif dm:
        vsrc, vconf = "product", "start_only"     # 'Verfügbar ab' = jen začátek prodeje
    elif valid_from:
        vsrc, vconf = "product_group", "start_only"   # den stránky 'Ab Dienstag, 13. Oktober'
    else:
        vsrc, vconf = "unknown", "unknown"
    tags = derive_tags(brand, name, [b for b in badges if not b.lower().startswith("verfügbar")])
    return make_product(
        source,
        store_product_id=pid.group(1).zfill(18) if pid else "",
        brand=brand, name=name, amount=amount, unit=unit,
        product_url=urljoin(source_url, href) if href else "",
        image_url=pick_image(t),
        category=categorize(brand, name, unit, tags, default_group),
        price=cur, original_price=original,
        comparison_price=price(cm.group(1)) if cm else "", comparison_per=clean(cm.group(2)) if cm else "",
        valid_from=valid_from, valid_to=valid_to, source_date=source_date, theme=theme, tags=tags,
        deposit=deposit, deposit_type=deposit_type, approx_amount=approx, drained_weight=atg,
        variants=False, validity_source=vsrc, validity_confidence=vconf,
    )


def parse_tiles(html, source, source_url, source_date, theme_map=None, default_group=None, fallback_valid_from=True):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for t in soup.find_all("div", class_="product-tile"):
        a = t.find("a")
        href = a.get("href", "") if a else ""
        full = urljoin(source_url, href) if href else ""
        theme = ", ".join((theme_map or {}).get(full, []))
        p = tile_to_product(t, source, source_url, source_date, theme, default_group, fallback_valid_from)
        if p["name"] or p["price"]:
            out.append(p)
    return out


def next_page_url(html, current):
    a = BeautifulSoup(html, "html.parser").select_one("a[data-test=next-page]")
    return urljoin(current, a["href"]) if a and a.get("href") else None


def fetch_pages(session, url, pause=0.4):
    """Vrací HTML všech stránek výpisu (sleduje odkaz na další stránku); vyrobí se jen stránky se stavem 200."""
    seen_urls = set()
    n = 0
    while url and n < MAX_PAGES and url not in seen_urls:
        seen_urls.add(url)
        n += 1
        r = session.get(url, timeout=60)
        if r.status_code != 200:
            print(f"  ! status {r.status_code} ({url})")
            return
        yield r.text
        url = next_page_url(r.text, url)
        if url:
            time.sleep(pause)


def parse_all_pages(session, url, source, source_url, source_date, theme_map=None):
    """Všechny stránky výpisu -> produkty bez duplicit."""
    out, seen = [], set()
    for html in fetch_pages(session, url):
        for p in parse_tiles(html, source, source_url, source_date, theme_map):
            k = p["product_url"] or (p["name"], p["price"])
            if k not in seen:
                seen.add(k)
                out.append(p)
    return out


def collect_days(session, day_url, dates, themes, source="angebote", skip_past=True):
    """Denní nabídky. day_url(datum) -> adresa stránky; themes: {datum: [témata]}.
    skip_past: dny před dneškem se nestahují (web je po skončení dne může zobrazit jinak a přepsal by se starší, správný stav)."""
    today = date.today().isoformat()
    for d in dates:
        if skip_past and d < today:
            print(f"  {d}: minulý den, přeskakuji")
            continue
        url = day_url(d)
        base_items = parse_all_pages(session, url, source, url, d)
        if not base_items:
            print(f"  {d}: žádné produkty")
            continue
        tmap = {}
        for th in themes.get(d, []):          # téma -> produkty (jen pokud filtr opravdu filtruje)
            time.sleep(0.4)
            items = parse_all_pages(session, f"{url}?theme={quote_plus(th)}", source, url, d)
            if 0 < len(items) < len(base_items):
                for it in items:
                    tmap.setdefault(it["product_url"], []).append(th)
        for p in base_items:
            if p["product_url"] in tmap:
                p["theme"] = ", ".join(tmap[p["product_url"]])
        print(f"  {d}: {len(base_items)} produktů, témata namapována: {len(tmap)}")
        yield {"source": source, "source_url": url, "label": d, "products": base_items}
        time.sleep(0.4)


def collect(session, opts):
    disc = get_discovery(session, opts)
    dates, themes = disc["dates"], disc["themes"]
    if opts["args"]:
        dates = opts["args"]
    if not dates:
        print("Angebote: žádné dny nenalezeny.")
        return
    print("Angebote dny:", dates)
    # ručně zadané dny (python hofer_angebote.py 2026-10-12) se stáhnou vždy
    yield from collect_days(session, lambda d: f"{BASE}/angebote/{d}", dates, themes,
                            skip_past=not opts["args"])


if __name__ == "__main__":
    run_batches(collect)
