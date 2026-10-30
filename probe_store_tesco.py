"""Tesco probe: prozkoumá web a parsuje produktové dlaždice Tesco.

Použití:
    python probe_store_tesco.py https://www.itesco.cz
    python probe_store_tesco.py https://www.itesco.cz URL_STRANKY_S_PRODUKTY

Skript je samostatný a nepoužívá Hofer parser.
"""
import json
import re
import sys
from collections import Counter
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

PRODUCT_LINK_RE = re.compile(r"/products/(\d+)")
URL_HINT = re.compile(
    r"\.pdf|\.json|/api/|digitalcontent|publitas|issuu|ipaper|flipbook|leaflet|flyer|letak|catalog",
    re.I,
)
HEADING_RE = re.compile(r"online-components-product-tile-product-heading__heading")
IMAGE_RE = re.compile(r"online-components-product-tile-product-image__image")
PRICE_RE = re.compile(r"online-components-product-tile-price__text")
UNIT_PRICE_RE = re.compile(r"online-components-product-tile-unit-price__subtext")
PROMO_RE = re.compile(r"online-components-product-tile-groceries-non-clubcard-promotion__wrapper")
SASH_RE = re.compile(r"online-components-product-tile-special-offer-sash__tag")


def clean_text(element):
    return element.get_text(" ", strip=True).replace("\xa0", " ") if element else ""


def first_text(container, class_re):
    element = container.find(class_=class_re) if container else None
    return clean_text(element)


def parse_amount(name):
    """Vytáhne orientační velikost z názvu; pokud ji nenajde, vrátí prázdný řetězec."""
    match = re.search(
        r"(?<!\w)(\d+(?:[,.]\d+)?)\s*(kg|g|mg|l|ml|cl|ks|kusů?)\b",
        name,
        re.I,
    )
    if not match:
        return "", ""
    amount = match.group(1).replace(",", ".")
    unit = match.group(2).lower()
    return amount, unit


def parse_price(text):
    """Převede českou cenu na číslo; zachová desetinnou tečku."""
    if not text:
        return ""
    match = re.search(r"(\d[\d\s.]*(?:,\d{1,2})?)\s*Kč", text, re.I)
    if not match:
        return ""
    value = match.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return round(float(value), 2)
    except ValueError:
        return ""


def parse_valid_to(text):
    match = re.search(r"Nabídka\s+platí\s+do\s+(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text, re.I)
    if not match:
        return ""
    day, month, year = map(int, match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def find_tile(heading):
    """Najde největší předek jedné produktové dlaždice, ne celý seznam produktů."""
    candidate = None
    for parent in heading.parents:
        if getattr(parent, "name", None) != "div":
            continue
        if not parent.find("a", href=PRODUCT_LINK_RE):
            continue
        if not parent.find("img", class_=IMAGE_RE):
            continue
        headings = parent.find_all(class_=HEADING_RE)
        if len(headings) > 1:
            break
        candidate = parent
    return candidate


def parse_tesco_tiles(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    products = []
    seen = set()

    for heading in soup.find_all(class_=HEADING_RE):
        tile = find_tile(heading)
        if tile is None:
            continue

        link = heading.find("a", href=PRODUCT_LINK_RE) or tile.find("a", href=PRODUCT_LINK_RE)
        if not link:
            continue

        href = urljoin(page_url, link.get("href", ""))
        id_match = PRODUCT_LINK_RE.search(urlparse(href).path)
        if not id_match:
            continue
        product_id = id_match.group(1)
        if product_id in seen:
            continue
        seen.add(product_id)

        name = clean_text(link)
        image = tile.find("img", class_=IMAGE_RE)
        image_url = urljoin(page_url, image.get("src", "")) if image and image.get("src") else ""

        price_text = first_text(tile, PRICE_RE)
        unit_price_text = first_text(tile, UNIT_PRICE_RE)
        promotion_text = first_text(tile, PROMO_RE)
        amount, unit = parse_amount(name)

        original_price_match = re.search(
            r"předtím\s+(\d[\d\s.]*(?:,\d{1,2})?)\s*Kč",
            promotion_text,
            re.I,
        )
        original_price = ""
        if original_price_match:
            original_price = parse_price(original_price_match.group(0))

        category_link = tile.find(
            "a",
            class_=re.compile(r"online-components-product-tile-rest-of-shelf__rest-of-shelf"),
        )
        category = ""
        if category_link:
            category = category_link.get("aria-label", "")
            category = re.sub(r"^Více z kategorie\s*", "", category, flags=re.I).strip()

        products.append({
            "store": "tesco_cz",
            "store_product_id": product_id,
            "brand": "",
            "name": name,
            "amount": amount,
            "unit": unit,
            "price": parse_price(price_text),
            "original_price": original_price,
            "comparison_price": unit_price_text,
            "currency": "CZK",
            "image_url": image_url,
            "product_url": href,
            "valid_from": "",
            "valid_to": parse_valid_to(promotion_text),
            "promotion_text": promotion_text,
            "category": category,
            "is_promotion": bool(promotion_text or tile.find(class_=SASH_RE)),
        })

    return products


def next_tesco_page(html, current_url):
    soup = BeautifulSoup(html, "html.parser")
    current_query = parse_qs(urlparse(current_url).query)
    try:
        current_page = int(current_query.get("page", ["1"])[0])
    except (TypeError, ValueError):
        current_page = 1

    candidates = []
    for link in soup.find_all("a", href=True):
        href = urljoin(current_url, link["href"])
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        if "page" not in query:
            continue
        try:
            page_number = int(query["page"][0])
        except (TypeError, ValueError):
            continue
        if page_number > current_page and parsed.netloc == urlparse(current_url).netloc:
            candidates.append((page_number, href))

    if not candidates:
        return ""
    return min(candidates, key=lambda item: item[0])[1]


def site_links(base, soup):
    host = urlparse(base).netloc
    output = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base.rstrip("/") + "/", anchor["href"]).split("#")[0]
        if urlparse(url).netloc == host and url not in output:
            output.append(url)
    return output


def overview(session, base):
    response = session.get(base.rstrip("/") + "/", timeout=60)
    print(f"{base.rstrip('/')}/ -> status {response.status_code}, {len(response.text)} znaků")
    if response.status_code != 200:
        return

    soup = BeautifulSoup(response.text, "html.parser")
    links = site_links(base, soup)
    print(f"odkazů na stejném webu: {len(links)}")
    segments = Counter("/" + urlparse(url).path.strip("/").split("/")[0] for url in links)
    print("první segmenty cest:", dict(segments.most_common(15)))

    hints = re.compile(r"letak|katalog|akc|produkt|zna|brand|offer|leaflet", re.I)
    matches = [url for url in links if hints.search(urlparse(url).path)]
    print(f"\nstránky s nápovědou (letáky/produkty): {len(matches)}")
    for url in matches[:12]:
        print(" ", url)
    print("\nnadpisy:", [h.get_text(" ", strip=True)[:60] for h in soup.find_all(["h1", "h2", "h3"])[:12]])


def dump_hints(html, url):
    soup = BeautifulSoup(html, "html.parser")
    print("\n--- diagnostika HTML ---")
    print("title:", clean_text(soup.title) or "-")

    scripts = [urljoin(url, tag["src"]) for tag in soup.find_all("script", src=True)]
    print(f"skripty se src: {len(scripts)}", scripts[:5])

    for tag_name, attr in (("a", "href"), ("iframe", "src"), ("link", "href"),
                           ("img", "src"), ("source", "src"), ("embed", "src")):
        found = [
            urljoin(url, tag.get(attr))
            for tag in soup.find_all(tag_name)
            if tag.get(attr) and URL_HINT.search(tag.get(attr))
        ]
        if found:
            print(f"{tag_name}[{attr}] s nápovědou ({len(found)}):", found[:4])

    print("počet odkazů na produkty:", len(soup.find_all("a", href=PRODUCT_LINK_RE)))
    print("počet nadpisů produktů:", len(soup.find_all(class_=HEADING_RE)))
    print("počet obrázků produktů:", len(soup.find_all("img", class_=IMAGE_RE)))
    print("ceny:", [clean_text(x) for x in soup.find_all(class_=PRICE_RE)[:8]])
    print("jednotkové ceny:", [clean_text(x) for x in soup.find_all(class_=UNIT_PRICE_RE)[:8]])
    print("akční texty:", [clean_text(x) for x in soup.find_all(class_=PROMO_RE)[:8]])
    print("odkazy na další stránky:", [
        x["href"] for x in soup.find_all("a", href=True) if re.search(r"[?&]page=\d+", x["href"])
    ][:8])


def test_page(session, url):
    response = session.get(url, timeout=60)
    print(f"\n=== {url}\nstatus {response.status_code}, {len(response.text)} znaků")
    if response.status_code != 200:
        print("začátek odpovědi:", response.text[:300].replace("\n", " "))
        return

    products = parse_tesco_tiles(response.text, url)
    next_url = next_tesco_page(response.text, url)
    print(f"nalezené produktové dlaždice: {len(products)} | další strana: {next_url or '-'}")

    fields = (
        "store_product_id", "brand", "name", "amount", "price", "original_price",
        "comparison_price", "image_url", "product_url", "valid_from", "valid_to",
    )
    for field in fields:
        filled = sum(1 for product in products if product.get(field) not in ("", None))
        print(f"  {field:18} vyplněno {filled}/{len(products)}")

    print("akční produkty:", sum(1 for product in products if product["is_promotion"]))
    for product in products[:10]:
        print(
            "  ",
            product["store_product_id"], "|", product["name"], "|",
            product["price"], "| původní:", product["original_price"],
            "| do:", product["valid_to"], "|", product["product_url"],
        )

    if not products:
        print("\nParser zatím nenašel produkty; vypisuji diagnostiku.")
        dump_hints(response.text, url)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    base_url = sys.argv[1].rstrip("/")
    session = requests.Session(impersonate="chrome")
    overview(session, base_url)

    for page_url in sys.argv[2:]:
        test_page(session, page_url)
