"""Souhrn kvality dat: z každého zdroje nejnovější soubor, jedna tabulka. Stačí ji vložit do chatu.

    python3 report_output.py               # složka s výstupy
    python3 report_output.py /cesta        # jiná složka
"""
import glob, json, os, re, sys
from collections import Counter
from hofer_common import outdir

NAME = re.compile(r"^(\d{8}_\d{6})_([a-z]+(?:-[a-z]+)*)_(?!brands)([a-z0-9_\-]+)\.json$")
folder = sys.argv[1] if len(sys.argv) > 1 else outdir()
UNSURE = {"", "potraviny", "nonfood"}                 # záložní nebo prázdná kategorie

latest = {}
for f in glob.glob(os.path.join(folder, "*.json")):
    m = NAME.match(os.path.basename(f))
    if not m:
        continue
    try:
        j = json.load(open(f, encoding="utf-8")); meta, ps = j["meta"], j["products"]
    except Exception:
        continue
    key = (meta["store"], meta["source"], meta["source_url"])
    if key not in latest or meta["generated_at"] > latest[key][0]["generated_at"]:
        latest[key] = (meta, ps)


def pct(ps, fn):
    return f"{sum(1 for p in ps if fn(p)) * 100 // len(ps):3d}" if ps else "  -"


print(f"{'obchod/zdroj':36}{'ks':>5} {'ID%':>4} {'URL%':>5} {'brand':>6} {'množ.':>6} {'sleva':>6} {'kat?':>5} {'valid':>6} {'to%':>5}  nejčastější kategorie")
ids = {}
for (store, src, url), (meta, ps) in sorted(latest.items()):
    label = f"{store.split('_')[0]}/{src}" + (f" {url[-10:]}" if src == "angebote" else "")
    top = ", ".join(f"{c} {n}" for c, n in Counter(p["category"] or "∅" for p in ps).most_common(3))
    print(f"{label[:36]:36}{len(ps):5} {pct(ps, lambda p: p['store_product_id']):>4} {pct(ps, lambda p: p['product_url']):>5} "
          f"{pct(ps, lambda p: p['brand']):>6} {pct(ps, lambda p: p['amount']):>6} {pct(ps, lambda p: p['original_price']):>6} "
          f"{pct(ps, lambda p: p['category'] in UNSURE):>5} {pct(ps, lambda p: p['valid_from']):>6} {pct(ps, lambda p: p['valid_to']):>5}  {top}")
    for p in ps:
        if p["store_product_id"]:
            ids.setdefault(store, {}).setdefault(p["store_product_id"], p)

print("\nSloupce: ID%/URL% = vyplněné ID a odkaz, kat? = záložní nebo prázdná kategorie, valid/to% = vyplněné valid_from/valid_to")
for store, d in ids.items():
    print(f"  {store}: {len(d)} různých produktů s ID")
if len(ids) == 2:
    a, b = list(ids.values())
    common = set(a) & set(b)
    print(f"  společná ID mezi obchody: {len(common)}", ("; ".join(f"{a[k]['name'][:24]} / {b[k]['name'][:24]}" for k in sorted(common)[:3])) if common else "")
