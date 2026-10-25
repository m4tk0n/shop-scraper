"""Zkontroluje výstupní JSON: stejná struktura meta i produktů u všech souborů nové verze
a pravidlo, že ID produktu je vyplněné jen spolu s odkazem na stránku produktu.

    python3 check_output.py                 # souhrn + jen problematické soubory
    python3 check_output.py --all           # vypíše i soubory v pořádku
    python3 check_output.py --latest        # jen nejnovější soubor z každého zdroje
    python3 check_output.py --move-old      # soubory starší verze přesune do podsložky old/
    python3 check_output.py /cesta/složka   # jiná složka s výstupy
"""
import glob, json, os, re, shutil, sys
from collections import defaultdict
from hofer_common import PRODUCT_FIELDS, VALIDITY_CONFIDENCE, VALIDITY_SOURCES, outdir

META = ["generated_at", "store", "country", "currency", "source", "type", "source_url",
        "product_count", "content_hash", "file_id", "run_id"]
ADDED_LATER = {"country", "currency", "content_hash", "file_id", "run_id"}      # pole, která přibyla v pozdějších verzích
OLD_FIELDS = [k for k in PRODUCT_FIELDS if not k.startswith("validity_")]      # schéma před přidáním validity_*
MUST_HAVE_TO = {"tiefpreis", "bier", "preiswochen"}                              # tyto akce musí mít konec platnosti
warns = []
NAME = re.compile(r"^(\d{8}_\d{6})_([a-z]+(?:-[a-z]+)*)_(?!brands)([a-z0-9_\-]+)\.json$")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
folder = args[0] if args else outdir()
show_all, latest, move_old = "--all" in sys.argv, "--latest" in sys.argv, "--move-old" in sys.argv

files = []
for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
    m = NAME.match(os.path.basename(f))
    if m:
        files.append((f, m.group(1), m.group(2), m.group(3)))
if latest:                                   # nejnovější soubor z každého (obchod, zdroj)
    best = {}
    for f, ts, store, src in files:
        key = (store, src)
        if key not in best or ts > best[key][1]:
            best[key] = (f, ts, store, src)
    files = sorted(best.values())

ok, old, errors, skipped = [], [], [], []
for f, ts, store, src in files:
    base = os.path.basename(f)
    try:
        j = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        skipped.append((base, f"nejde přečíst ({type(e).__name__})")); continue
    if not (isinstance(j, dict) and "meta" in j and "products" in j):
        skipped.append((base, "není ve formátu {meta, products}")); continue
    m, ps = j["meta"], j["products"]
    prod_ok = all(list(p) == list(PRODUCT_FIELDS) and all(type(p[k]) == type(v) for k, v in PRODUCT_FIELDS.items()) for p in ps)
    prod_old = not prod_ok and bool(ps) and all(list(p) == OLD_FIELDS for p in ps)
    bad_val = sum(1 for p in ps if p.get("validity_source", "unknown") not in VALIDITY_SOURCES
                  or p.get("validity_confidence", "unknown") not in VALIDITY_CONFIDENCE
                  or (p.get("valid_from") and p.get("valid_to") and p["valid_from"] > p["valid_to"]))
    if m.get("source") in MUST_HAVE_TO:
        no_to = sum(1 for p in ps if not p.get("valid_to"))
        if no_to:
            warns.append((base, no_to, len(ps)))
    id_no_link = sum(1 for p in ps if p["store_product_id"] and p["store_product_id"].lstrip("0") not in p["product_url"])
    missing = [k for k in META if k not in m]
    extra = [k for k in m if k not in META]
    if list(m) == META and m["product_count"] == len(ps) and prod_ok and not id_no_link and not bad_val:
        ok.append((f, base, m, len(ps)))
    elif (prod_ok or prod_old) and not id_no_link and not bad_val and not extra and set(missing) <= ADDED_LATER and m.get("product_count") == len(ps):
        old.append((f, base, "starší schéma produktů (bez validity_*)" if prod_old else f"starší verze meta, chybí: {', '.join(missing)}"))
    else:
        why = []
        if extra or (missing and not set(missing) <= ADDED_LATER):
            why.append(f"meta: chybí {missing}, navíc {extra}")
        elif list(m) != META:
            why.append("meta: jiné pořadí polí")
        if m.get("product_count") != len(ps):
            why.append(f"product_count {m.get('product_count')} ≠ {len(ps)}")
        if not (prod_ok or prod_old):
            why.append("produkty mají jinou strukturu")
        if bad_val:
            why.append(f"{bad_val}× neplatná nebo nekonzistentní platnost (validity_*, valid_from > valid_to)")
        if id_no_link:
            why.append(f"{id_no_link}× ID bez odkazu na stránku produktu")
        errors.append((f, base, "; ".join(why)))

if show_all:
    for f, base, m, n in ok:
        print(f"OK     {base[:60]:60} {m['store']}/{m['currency']} {n:4}")
for f, base, why in old:
    print(f"STARÉ  {base[:60]:60} {why}")
for f, base, why in errors:
    print(f"CHYBA  {base[:60]:60} {why}")

for base, n, k in warns:
    print(f"VAROVÁNÍ {base[:60]:60} {n} z {k} akčních produktů bez valid_to (změnil se formát stránky?)")
print(f"\nV pořádku: {len(ok)} | starší verze: {len(old)} | skutečná chyba: {len(errors)} | přeskočeno: {len(skipped) + 0}")
by = defaultdict(int)
for f, base, m, n in ok:
    by[(m["store"], m["currency"])] += 1
if by:
    print("  v pořádku podle obchodu:", {f"{s}/{c}": n for (s, c), n in by.items()})
for b, why in skipped:
    print(f"  přeskočeno: {b[:60]:60} {why}")
if move_old and old:
    dest = os.path.join(folder, "old")
    os.makedirs(dest, exist_ok=True)
    for f, base, why in old:
        shutil.move(f, os.path.join(dest, base))
    print(f"\nPřesunuto {len(old)} souborů starší verze do {dest}")
elif old:
    print("\nSoubory starší verze přesuneš do podsložky old/ příkazem: python3 check_output.py --move-old")
sys.exit(1 if errors else 0)
