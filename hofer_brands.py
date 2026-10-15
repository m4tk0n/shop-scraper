"""Kontrola značek sladkostí -> jeden JSON se všemi výsledky.

Čte už vytvořené výstupy (<timestamp>_hofer-at_*.json), z každého zdroje vezme nejnovější soubor,
vybere sladkosti (tabulky, bonboniéry, tyčinky, želé, marcipán, pralinky, sušenky...) a seskupí je
podle značky. Značky se zjišťují z dat, není třeba je znát. Pokud existuje znacky.txt, porovná
výsledky s ním (které značky ze seznamu mají sladkosti a které nové značky se v datech objevily).

    python3 hofer_brands.py                       # všechny sladkosti
    python3 hofer_brands.py --chocolate           # jen čokoláda
    python3 hofer_brands.py --categories bonbony,cokolady   # vlastní výběr kategorií
    python3 hofer_brands.py --dir /cesta          # jiná složka s výstupy
"""
import glob
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from hofer_common import COUNTRY, CURRENCY, STORE, content_hash, outdir, tokens_of

SWEET_CATEGORIES = {"cokolady", "sladkosti", "susenky", "bonbony"}      # tabulky, bonboniéry, tyčinky, želé, marcipán...
CHOC_WORDS = ("schoko", "schokolade", "praline", "pralinen", "nougat", "kakao", "trüffel", "lindor", "bueno",
              "mozartkugel", "choco", "chocolate", "rocher", "raffaello", "dominostein", "dominosteine")

# známé značky sladkostí (jen pomůcka pro rozpoznání, seznam si můžeš upravit)
KNOWN_BRANDS = {
    "milka", "lindt", "lindor", "toblerone", "ritter sport", "ferrero", "kinder", "merci", "storck", "raffaello",
    "rocher", "mon chéri", "mars", "snickers", "twix", "bounty", "m&m's", "hershey's", "manner", "zotter", "hachez",
    "schogetten", "villars", "suchard", "cailler", "hanuta", "duplo", "nutella", "toffifee", "smarties", "kitkat",
    "nestlé", "oreo", "reber", "heindl", "berger", "frey", "lauenstein", "waldbaur", "heilemann", "lotus biscoff",
    "haribo", "kägi", "mondelez", "danone", "dunkin'",
}
# vlastní značky Hofer/Aldi (podle mých znalostí; ověř a případně uprav)
OWN_BRANDS = {"choceur": "čokoláda", "moser roth": "prémiová čokoláda", "monarc": "sezónní sladkosti",
              "nutoka": "oříškový čokoládový krém"}
LABELS = {"bio", "vegan"}              # nejsou to značky, ale označení


def bkey(s):
    return re.sub(r"[^a-z0-9äöüßé&']+", " ", (s or "").lower()).strip()


def kind_of(key):
    if not key:
        return "missing"
    if key in OWN_BRANDS:
        return "own_brand"
    if key in LABELS:
        return "label"
    if key in KNOWN_BRANDS:
        return "known_brand"
    return "unknown"


def latest_files(folder):
    """Z každého zdroje (source + source_url) nejnovější soubor."""
    best = {}
    for f in glob.glob(os.path.join(folder, f"*_{STORE.replace('_', '-')}_*.json")):
        if "_brands" in os.path.basename(f):
            continue
        try:
            j = json.load(open(f, encoding="utf-8"))
            m = j["meta"]
            k = (m["source"], m["source_url"])
        except Exception:
            continue
        if k not in best or m["generated_at"] > best[k][1]["generated_at"]:
            best[k] = (f, m, j["products"])
    return list(best.values())


def is_in_scope(p, key, mode, categories):
    """mode: 'sweets' (výchozí, všechny sladkosti) | 'chocolate' | 'custom' (--categories)."""
    cat = p["category"]
    tk = tokens_of(p["brand"], p["name"])
    choc_word = any(t.startswith(w) for t in tk for w in CHOC_WORDS)
    if mode == "custom":
        return cat in categories
    if mode == "sweets":
        if cat in SWEET_CATEGORIES:
            return True
        return cat == "snidane" and (choc_word or key in ("nutella", "nutoka"))      # čokoládové krémy
    # chocolate
    if cat == "cokolady":
        return True
    if cat not in SWEET_CATEGORIES:
        return cat == "snidane" and key in ("nutella", "nutoka")
    if choc_word:
        return True
    if cat in ("sladkosti", "susenky"):
        return key in KNOWN_BRANDS or key in OWN_BRANDS
    return False


def build(folder, mode="sweets", categories=None, watch=()):
    files = latest_files(folder)
    all_products = [dict(p, _src=m["source"]) for _, m, ps in files for p in ps]
    seen = Counter(bkey(p["brand"]) for p in all_products if p["brand"])
    brand_keys = {k for k in seen if k} | KNOWN_BRANDS | set(OWN_BRANDS)
    watch_keys = {bkey(w["name"]): w["name"] for w in watch}

    merged = {}
    for p in all_products:
        key = bkey(p["brand"])
        source_of_brand = "listed" if key else "missing"
        if not key:                                   # zkus doplnit značku ze začátku názvu
            tk = bkey(p["name"]).split()
            for n in (3, 2, 1):
                cand = " ".join(tk[:n])
                if cand in brand_keys:
                    key, source_of_brand = cand, "inferred"
                    break
        mk = p["store_product_id"] or f"{key}|{bkey(p['name'])}"
        if not is_in_scope(p, key, mode, categories or set()):
            continue
        if mk in merged:
            merged[mk]["sources"] = sorted(set(merged[mk]["sources"]) | {p["_src"]})
            continue
        merged[mk] = {
            "store_product_id": p["store_product_id"],
            "brand": p["brand"],
            "brand_key": key,
            "brand_kind": kind_of(key),
            "brand_source": source_of_brand,
            "in_watchlist": key in watch_keys,
            "name": p["name"],
            "category": p["category"],
            "amount": p["amount"], "unit": p["unit"],
            "price": p["price"], "original_price": p["original_price"],
            "valid_from": p["valid_from"], "valid_to": p["valid_to"],
            "sources": [p["_src"]],
        }
    products = sorted(merged.values(), key=lambda x: (x["brand_key"] or "~", x["name"].lower()))

    groups = defaultdict(list)
    for p in products:
        groups[p["brand_key"]].append(p)
    brands = []
    for key, ps in groups.items():
        if not key:
            continue
        spell = Counter(p["brand"] for p in ps if p["brand"])
        prices = [float(p["price"]) for p in ps if p["price"]]
        brands.append({
            "brand": spell.most_common(1)[0][0] if spell else key,
            "brand_key": key,
            "kind": kind_of(key),
            "note": OWN_BRANDS.get(key, ""),
            "in_watchlist": key in watch_keys,
            "product_count": len(ps),
            "categories": dict(Counter(p["category"] for p in ps).most_common()),
            "sources": sorted({s for p in ps for s in p["sources"]}),
            "spellings": sorted(spell),
            "price_min": f"{min(prices):.2f}" if prices else "",
            "price_max": f"{max(prices):.2f}" if prices else "",
            "examples": [p["name"] for p in ps[:5]],
        })
    brands.sort(key=lambda b: (-b["product_count"], b["brand_key"]))
    missing = [{"store_product_id": p["store_product_id"], "name": p["name"], "category": p["category"],
                "sources": p["sources"]} for p in products if not p["brand_key"]]

    # porovnání se seznamem znacky.txt
    sweets_by_key = Counter(p["brand_key"] for p in products)
    all_by_key = Counter()
    for p in all_products:
        all_by_key[bkey(p["brand"])] += 1
    watchlist = [{"name": name, "products_total": all_by_key.get(k, 0), "products_in_scope": sweets_by_key.get(k, 0),
                  "status": ("sladkosti" if sweets_by_key.get(k) else "jen jiné produkty" if all_by_key.get(k) else "v datech není")}
                 for k, name in watch_keys.items()]
    new_brands = [{"brand": b["brand"], "product_count": b["product_count"], "kind": b["kind"]}
                  for b in brands if not b["in_watchlist"]]

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "store": STORE,
        "country": COUNTRY,
        "currency": CURRENCY,
        "report": "brands",
        "scope": mode if mode != "custom" else "categories:" + ",".join(sorted(categories or [])),
        "source_files": [{"source": m["source"], "source_url": m["source_url"], "generated_at": m["generated_at"],
                          "file_id": m.get("file_id", "")} for _, m, _ in files],
        "product_count": len(products),
        "brand_count": len(brands),
        "unknown_brand_count": sum(1 for b in brands if b["kind"] == "unknown"),
        "missing_brand_count": len(missing),
        "watchlist_count": len(watchlist),
        "watchlist_without_sweets": sum(1 for w in watchlist if not w["products_in_scope"]),
        "new_brand_count": len(new_brands),
        "content_hash": content_hash(products),
        "file_id": str(uuid.uuid4()),
    }
    return {"meta": meta, "watchlist": watchlist, "new_brands": new_brands, "brands": brands,
            "missing_brand": missing, "products": products}


def main(argv):
    from hofer_marken import read_watchlist
    folder = outdir()
    if "--dir" in argv:
        folder = argv[argv.index("--dir") + 1]
    mode, categories = "sweets", None
    if "--chocolate" in argv:
        mode = "chocolate"
    if "--categories" in argv:
        mode, categories = "custom", set(argv[argv.index("--categories") + 1].split(","))
    data = build(folder, mode, categories, read_watchlist())
    if not data["meta"]["source_files"]:
        print("Ve složce nejsou žádné soubory *_hofer-at_*.json:", folder)
        return 1
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = "" if mode == "sweets" else f"-{mode}"
    path = os.path.join(folder, f"{ts}_{STORE.replace('_', '-')}_brands{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    m = data["meta"]
    print(f"Rozsah: {m['scope']} | produktů: {m['product_count']} | značek: {m['brand_count']} (neznámých: {m['unknown_brand_count']}) | bez značky: {m['missing_brand_count']}")
    if data["watchlist"]:
        print(f"\nSeznam znacky.txt ({m['watchlist_count']}), bez sladkostí v datech: {m['watchlist_without_sweets']}")
        for w in data["watchlist"]:
            print(f"  {w['name'][:22]:22} {w['status']:18} sladkostí {w['products_in_scope']:3} / celkem {w['products_total']:3}")
    if data["new_brands"]:
        print(f"\nNové značky ve sladkostech, které nejsou v seznamu ({m['new_brand_count']}):")
        print("  " + ", ".join(f"{b['brand']} ({b['product_count']})" for b in data["new_brands"][:30]))
    print("\nUloženo:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
