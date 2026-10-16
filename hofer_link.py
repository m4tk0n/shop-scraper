"""Propojení letáku (platnost, bez ID) s dlaždicemi a výpisy (ID, bez platnosti) stažených v tomtéž běhu.

Shoda = stejná cena + stejný název (příp. značka + název) + stejné množství, a den dlaždice leží v intervalu letáku.
Dlaždice bez vlastního valid_from se bere ke dni stažení (musí akce právě platit).
Když se najdou různé intervaly, nehádá se (pole zůstanou prázdná).
"""
import re
from collections import defaultdict

from hofer_common import amount_key


ABV = re.compile(r"\d+(?:[.,]\d+)?\s*%\s*vol\.?", re.I)       # '5,0%Vol.' bývá v názvu z letáku, na dlaždici ne


def _n(s):
    return re.sub(r"[^a-zäöüß0-9]+", " ", ABV.sub(" ", (s or "").lower())).strip()


def _full(p):
    return _n(f"{p['brand']} {p['name']}")


def _in(f, day):
    return bool(f["valid_from"] and f["valid_to"] and f["valid_from"] <= day <= f["valid_to"])


def _same(f, t, price=True):
    if price and f["price"] != t["price"]:
        return False
    if _n(f["name"]) == _n(t["name"]):
        if f["brand"] and t["brand"] and _n(f["brand"]) != _n(t["brand"]):
            return False
    elif _full(f) != _full(t):
        return False
    if f["amount"] and t["amount"] and amount_key(f["amount"], f["unit"]) != amount_key(t["amount"], t["unit"]):
        return False
    return True


def link(flyer_items, tile_items):
    """Obousměrně: ID+URL -> položka letáku, valid_from/valid_to -> dlaždice. Jen jednoznačné shody."""
    idx = defaultdict(list)
    for f in flyer_items:
        for k in {_n(f["name"]), _full(f)}:
            idx[k].append(f)
    stats = {"id": 0, "validity": 0, "ambiguous": 0}
    ids = defaultdict(dict)                                  # položka letáku -> {ID: dlaždice}
    for t in tile_items:
        cands = {id(f): f for k in {_n(t["name"]), _full(t)} for f in idx.get(k, [])}
        # 1) ID: stejný produkt (značka, název, množství), akční cena z letáku se může lišit od běžné na webu
        if t["store_product_id"] and t["product_url"]:
            for f in cands.values():
                if not f["store_product_id"] and _same(f, t, price=False):
                    ids[id(f)][t["store_product_id"]] = (f, t)
        # 2) platnost: stejná cena a akce právě platí
        day = t["valid_from"] or t["source_date"]
        c = [f for f in cands.values() if f["valid_from"] and f["valid_to"] and _same(f, t) and _in(f, day)]
        if not c:
            continue
        if len({(f["valid_from"], f["valid_to"]) for f in c}) > 1:
            stats["ambiguous"] += 1
            continue
        if not t["valid_to"]:
            f = c[0]
            t["valid_to"] = f["valid_to"]
            t["valid_from"] = t["valid_from"] or f["valid_from"]
            t["validity_source"], t["validity_confidence"], t["validity_type"] = "product_group", "matched", "promo"
            stats["validity"] += 1
    for found in ids.values():                               # ID jen když je jednoznačné
        if len(found) == 1:
            f, t = next(iter(found.values()))
            f["store_product_id"], f["product_url"] = t["store_product_id"], t["product_url"]
            stats["id"] += 1
    return stats
