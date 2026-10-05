"""Z nejnovějších výstupů vytvoří složku latest/<obchod>/ (bez časových razítek) a manifest.json.

Soubor se přepíše jen když se změnil content_hash, takže commit obsahuje jen skutečné změny dat.

    python3 publish_latest.py [složka_s_výstupy] [cílová_složka] [--prune]
      --prune   smaže v cílové složce soubory, které už v posledním běhu obchodu nejsou (např. den, který zmizel z menu)
"""
import glob, json, os, re, shutil, sys
from datetime import datetime
from hofer_common import outdir

NAME = re.compile(r"^(\d{8}_\d{6})_(hofer-at|aldi-ch)_(?!brands)([a-z0-9_\-]+)\.json$")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
src_dir = args[0] if args else outdir()
dst_dir = args[1] if len(args) > 1 else "latest"
prune = "--prune" in sys.argv

newest = {}                                           # (obchod, zbytek názvu) -> (časové razítko, cesta, meta)
for f in glob.glob(os.path.join(src_dir, "*.json")):
    m = NAME.match(os.path.basename(f))
    if not m:
        continue
    try:
        meta = json.load(open(f, encoding="utf-8"))["meta"]
    except Exception:
        continue
    key = (m.group(2), m.group(3))
    if key not in newest or m.group(1) > newest[key][0]:
        newest[key] = (m.group(1), f, meta)

changed, same, removed = [], 0, []
manifest = {"generated_at": datetime.now().isoformat(timespec="seconds"), "stores": {}}
for store in sorted({k[0] for k in newest}):
    sdir = os.path.join(dst_dir, store)
    os.makedirs(sdir, exist_ok=True)
    items = {k: v for k, v in newest.items() if k[0] == store}
    last_run = max(v[2].get("run_id", "") for v in items.values())        # poslední běh obchodu
    keep = {}
    for (st, rest), (ts, f, meta) in sorted(items.items()):
        if prune and meta.get("run_id", "") != last_run:
            continue                                                       # zdroj, který v posledním běhu nebyl
        keep[rest] = (f, meta)
        target = os.path.join(sdir, f"{rest}.json")
        old_hash = None
        if os.path.exists(target):
            try:
                old_hash = json.load(open(target, encoding="utf-8"))["meta"].get("content_hash")
            except Exception:
                pass
        if old_hash and old_hash == meta.get("content_hash"):
            same += 1
        else:
            shutil.copyfile(f, target)
            changed.append(f"{store}/{rest}.json ({meta['product_count']} produktů)")
        manifest["stores"].setdefault(store, []).append({
            "file": f"{store}/{rest}.json", "source": meta["source"], "source_url": meta["source_url"],
            "product_count": meta["product_count"], "content_hash": meta.get("content_hash", ""),
            "file_id": meta.get("file_id", ""), "generated_at": meta["generated_at"]})
    if prune:
        for old in glob.glob(os.path.join(sdir, "*.json")):
            if os.path.basename(old)[:-5] not in keep:
                os.remove(old); removed.append(os.path.relpath(old, dst_dir))

os.makedirs(dst_dir, exist_ok=True)
mpath = os.path.join(dst_dir, "manifest.json")
old_files = None
if os.path.exists(mpath):
    try:
        old_files = {(s, e["file"]): e["content_hash"] for s, es in json.load(open(mpath))["stores"].items() for e in es}
    except Exception:
        pass
new_files = {(s, e["file"]): e["content_hash"] for s, es in manifest["stores"].items() for e in es}
if old_files != new_files:                              # manifest se přepíše jen při změně obsahu
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"latest: změněno {len(changed)}, beze změny {same}, smazáno {len(removed)}")
for c in changed:
    print("  změněno:", c)
for r in removed:
    print("  smazáno:", r)
