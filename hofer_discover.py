"""Zjištění aktuálních stránek z menu hofer.at (dny Angebote, letáky, akční sekce).

Při každém běhu se načte menu a podle něj se zjistí, co právě existuje:
  - dny   /angebote/<datum>              (+ témata ?theme=...)
  - letáky /flugblatt/<něco>              (Tiefpreis, Bier, případně nové)
  - sekce /produkte/<něco>/k/<id>         (Preiswochen, Dauerhaft, Weihnachten, Ostern, Grillen, ...)
Při selhání zjišťování se použijí záložní adresy.
"""
import re
from urllib.parse import unquote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from hofer_common import STORE_URL

BASE = STORE_URL
NAV_URL = BASE + "/flugblatt"

# přejmenování zdrojů na stabilní krátké názvy
ALIASES = {
    "hofer-preis-wochen": "preiswochen",
    "hofer-preiswochen": "preiswochen",
    "hofer-preis-dauerhaft-guenstiger": "dauerhaft",
}
OFFER_SECTIONS = {"preiswochen"}          # sekce, které jsou akce (ostatní jsou katalog = listing)

FALLBACK_FLYERS = {
    "tiefpreis": BASE + "/flugblatt/tiefpreis-aktionen",
    "bier": BASE + "/flugblatt/bier-aktionen",
}
FALLBACK_SECTIONS = {
    "preiswochen": BASE + "/produkte/hofer-preiswochen/k/1588161434751158",
    "dauerhaft": BASE + "/produkte/hofer-preis-dauerhaft-guenstiger/",
}


def find_dates_and_themes(html):
    dates, themes = [], {}
    for d, th in re.findall(r"/angebote/(\d{4}-\d{2}-\d{2})(?:\?theme=([^\"'&<>\s]+))?", html):
        if d not in dates:
            dates.append(d)
        if th:
            th = unquote_plus(th)
            themes.setdefault(d, [])
            if th not in themes[d]:
                themes[d].append(th)
    return sorted(dates), themes


def _name(slug):
    slug = re.sub(r"-aktionen$", "", slug)
    return ALIASES.get(slug, slug.replace("-", "_"))


def parse_nav(html):
    soup = BeautifulSoup(html, "html.parser")
    dates, themes = find_dates_and_themes(html)

    flyers = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path.rstrip("/")
        m = re.fullmatch(r"/flugblatt/([a-z0-9-]+)", path)
        if m:
            flyers.setdefault(_name(m.group(1)), urljoin(BASE, path))

    # položky menu Produkty: jednoúrovňové /produkte/<slug>/k/<id>
    items = {}
    for a in soup.find_all("a", href=True):
        path = urlparse(a["href"]).path
        m = re.fullmatch(r"/produkte/([a-z0-9-]+)/k/(\d+)", path)
        if not m:
            continue
        li = a.find_parent("li")
        has_children = bool(li and li.find("ul"))
        slug, cid = m.groups()
        prev = items.get(slug)
        items[slug] = {"id": cid, "url": urljoin(BASE, path),
                       "children": has_children or (prev["children"] if prev else False)}
    # běžný katalog = položky s podkategoriemi (jejich ID jsou delší); akční sekce jsou listy s kratším ID
    with_children = [len(v["id"]) for v in items.values() if v["children"]]
    ref = max(with_children) if with_children else max((len(v["id"]) for v in items.values()), default=0)
    sections = {_name(s): v["url"] for s, v in items.items() if not v["children"] and len(v["id"]) < ref}
    return {"dates": dates, "themes": themes, "flyers": flyers, "sections": sections}


def discover(session):
    disc = {"dates": [], "themes": {}, "flyers": {}, "sections": {}}
    try:
        r = session.get(NAV_URL, timeout=60)
        if r.status_code == 200:
            disc = parse_nav(r.text)
        else:
            print(f"Menu: status {r.status_code}, používám záložní adresy.")
    except Exception as e:
        print(f"Menu: chyba ({type(e).__name__}), používám záložní adresy.")
    if not disc["flyers"]:
        disc["flyers"] = dict(FALLBACK_FLYERS)
    if not disc["sections"]:
        disc["sections"] = dict(FALLBACK_SECTIONS)
    for n in disc["flyers"]:
        register_source(n, "offer")
    for n in disc["sections"]:
        register_source(n, "offer" if n in OFFER_SECTIONS else "listing")
    print("Objeveno z menu:")
    print("  dny Angebote:", disc["dates"])
    print("  letáky:      ", list(disc["flyers"]))
    print("  sekce:       ", list(disc["sections"]))
    return disc


def get_discovery(session, opts):
    if "discovery" not in opts:
        opts["discovery"] = discover(session)
    return opts["discovery"]
