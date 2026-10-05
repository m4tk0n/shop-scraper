"""Porovná naše zařazení podle slov s kategoriemi, které dává samotný web (menu obchodu).

Bere zdroje, které se stáhly po kategoriích sortimentu (produkty mají v poli theme název podkategorie).
Ukáže, kde se slovní pravidla rozcházejí s webem: tam je buď chyba ve slovníku, nebo je kategorie webu příliš hrubá.

    python3 check_taxonomy.py              # Aldi Suisse
    python3 check_taxonomy.py hofer-at     # Hofer
"""
import glob, json, os, sys
from collections import Counter, defaultdict

store = sys.argv[1] if len(sys.argv) > 1 else "aldi-ch"
os.environ["STORE"] = store.replace("-", "_")                    # před importem hofer_common
from hofer_common import categorize, outdir

latest = {}
for f in glob.glob(os.path.join(outdir(), f"2*_{store}_*.json")):
    if "_brands" in os.path.basename(f):
        continue
    try:
        j = json.load(open(f, encoding="utf-8")); m, ps = j["meta"], j["products"]
    except Exception:
        continue
    key = (m["source"], m["source_url"])
    if key not in latest or m["generated_at"] > latest[key][0]["generated_at"]:
        latest[key] = (m, ps)

total = agree = 0
diff = defaultdict(list)
for (src, url), (m, ps) in sorted(latest.items()):
    # jen výpisy stažené po podkategoriích (většina produktů má theme)
    if m["type"] != "listing" or not ps or sum(1 for p in ps if p["theme"]) < 0.8 * len(ps) or src == "marken":
        continue
    a = d = 0
    for p in ps:
        kw = categorize(p["brand"], p["name"], p["unit"], p["tags"], "food")
        total += 1
        if kw == p["category"]:
            a += 1; agree += 1
        else:
            d += 1
            diff[(p["category"], kw)].append(f"{p['brand'][:10]}: {p['name'][:26]}".strip(": "))
    print(f"{src:28} {len(ps):4} produktů, shoda se slovy {a * 100 // len(ps):3} %")

if not total:
    print("Žádný výpis po podkategoriích nenalezen (stáhni např. python3 aldi_ch.py nebo python3 hofer_sortiment.py).")
else:
    print(f"\nCelkem {total} produktů, shoda {agree * 100 // total} %, neshod {total - agree}")
    print("\nNejčastější neshody (kategorie webu → co řekla slova):")
    for (site, kw), items in sorted(diff.items(), key=lambda x: -len(x[1]))[:14]:
        print(f"  {site:16} → {kw:16} {len(items):3}×  např. {'; '.join(items[:3])}")
