"""Sloučí nejnovější soubory jednoho běhu do jednoho souboru na obchod: <timestamp>_<obchod>_merged.json

Databáze porovnává nabídku jen s posledním uloženým záznamem produktu (cena, původní cena, platnost).
Když je stejný produkt ve více souborech s různou platností nebo cenou, každý import by přidal
nové řádky. Proto vznikne jeden řádek na produkt:

  * klíč produktu = ID zboží, jinak značka | název | množství (jako match_key v databázi);
  * nabídka (cena, původní cena, platnost) = ta, která platí v den běhu:
        platná akce s datem od-do (nejnižší cena, pak nejkratší období)
      > akce se začátkem v minulosti (nejnovější začátek)
      > běžná cena bez platnosti
      > budoucí akce > skončená akce;
  * ostatní pole (ID, odkaz, název, značka, množství, obrázek, kategorie) z nejspolehlivějšího zdroje:
    dlaždice s odkazem na stránku produktu, kategorie z webu (sortiment) před odhadem podle slov.

    python3 merge_latest.py [složka_s_výstupy]
      --window=N   zdroje do N hodin od nejnovějšího běhu obchodu (výchozí 3)
      --today=RRRR-MM-DD   den, ke kterému se vybírá platná nabídka (výchozí dnes)
"""
import glob
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from hofer_common import PRODUCT_FIELDS, STORES, content_hash, match_key, outdir

NAME = re.compile(r"^(\d{8}_\d{6})_([a-z]+(?:-[a-z]+)*)_(?!brands)([a-z0-9_\-]+)\.json$")
FALLBACK_CATEGORIES = {"", "potraviny", "nonfood"}           # záložní kategorie podle slov
LISTS = ("tags",)


def run_time(meta):
    """Čas běhu z run_id ('20261015_043012-ab12cd34'); starší soubory bez run_id -> None."""
    try:
        return datetime.strptime(meta.get("run_id", "")[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def load_latest(folder, window):
    """-> {obchod: [(zdroj, meta, produkty)]} nejnovější soubor každého zdroje z posledního běhu obchodu."""
    newest = {}
    for f in glob.glob(os.path.join(folder, "*.json")):
        m = NAME.match(os.path.basename(f))
        if not m or m.group(3) == "merged":
            continue
        try:
            j = json.load(open(f, encoding="utf-8"))
            meta, ps = j["meta"], j["products"]
        except Exception:
            continue
        key = (m.group(2), m.group(3))
        if key not in newest or m.group(1) > newest[key][0]:
            newest[key] = (m.group(1), meta, ps)
    out = defaultdict(list)
    for store in {k[0] for k in newest}:
        items = {k: v for k, v in newest.items() if k[0] == store}
        times = [t for t in (run_time(v[1]) for v in items.values()) if t]
        last = max(times, default=None)
        for (st, rest), (_, meta, ps) in sorted(items.items()):
            t = run_time(meta)
            if last and (t is None or last - t > window):
                continue                                       # zdroj, který v posledním běhu nebyl
            out[store].append((rest, meta, ps))
    return out


# ---------- výběr nabídky ----------
def is_promo(p):
    return p["type"] == "offer" or p["validity_type"] == "promo"


def offer_rank(p, today):
    """Menší = lepší. (skupina, ...): 0 platná akce s obdobím, 1 akce od data v minulosti, 2 běžná cena,
    4 budoucí akce, 5 skončená akce."""
    vf, vt = p["valid_from"], p["valid_to"]
    price = float(p["price"]) if p["price"] else 1e9
    promo = is_promo(p)
    if vf and vt:
        if vf <= today <= vt:
            return (0, price, (date.fromisoformat(vt) - date.fromisoformat(vf)).days)
        if vf > today:
            return (4, vf, price)
        return (5, -int(vt.replace("-", "")), price)                           # nedávno skončená dřív
    if vf and promo:                                           # 'od data' u akce (denní nabídky)
        return (1, -int(vf.replace("-", "")), price) if vf <= today else (4, vf, price)
    return (2, 0, 0)                                           # běžná cena (i s 'Verfügbar ab' u katalogu)


def tie_break(p, src_order):
    """Mezi stejně dobrými řádky: s původní cenou, s odkazem na produkt, pak podle pořadí zdroje."""
    return (not p["original_price"], not p["product_url"], src_order)


# ---------- slučování ----------
def sid(p):
    return p["store_product_id"].lstrip("0")


def mk(p):
    return "|".join(match_key(p["brand"], p["name"], p["amount"], p["unit"]))


def authoritative_sources(files):
    """Zdroje s kategoriemi přímo z webu: výpisy po podkategoriích (většina produktů má theme), mimo značky."""
    out = set()
    for src, meta, ps in files:
        if meta.get("type") == "listing" and src != "marken" and ps and sum(1 for p in ps if p["theme"]) >= 0.8 * len(ps):
            out.add(src)
    return out


def merge_store(files, today):
    auth = authoritative_sources(files)
    rows = []                                                  # (zdroj, pořadí, produkt)
    for order, (src, meta, ps) in enumerate(files):
        for p in ps:
            rows.append((src, order, dict(p)))

    id_mk, id_name = defaultdict(set), defaultdict(set)
    for _, _, p in rows:
        if sid(p):
            id_mk[mk(p)].add(sid(p))
            id_name[(match_key("", p["name"], p["amount"], p["unit"]))].add(sid(p))

    groups = defaultdict(list)
    attached = 0
    for src, order, p in rows:
        key = ("id", sid(p)) if sid(p) else None
        if not key:                                            # bez ID: shoda podle značky|názvu|množství s jediným ID
            ids = id_mk.get(mk(p), set())
            if len(ids) != 1 and not p["brand"]:
                ids = id_name.get(match_key("", p["name"], p["amount"], p["unit"]), set())
            if len(ids) == 1:
                key, attached = ("id", next(iter(ids))), attached + 1
            else:
                key = ("mk", mk(p))
        groups[key].append((src, order, p))

    out, stats = [], Counter(attached=attached, rows=len(rows))
    for key, g in groups.items():
        best = min(g, key=lambda r: (offer_rank(r[2], today), tie_break(r[2], r[1])))
        base = dict(best[2])
        rank0 = offer_rank(base, today)[0]
        offers = {(r[2]["price"], r[2]["original_price"], r[2]["valid_from"], r[2]["valid_to"]) for r in g}
        if len(offers) > 1:
            stats["multi_offer"] += 1
        stats[f"offer_rank{rank0}"] += 1

        site = [r for r in g if r[2]["product_url"] and r[2]["store_product_id"]]
        site.sort(key=lambda r: (r[0] not in auth, r[1]))      # nejdřív zdroje s kategoriemi z webu
        if site and not (base["store_product_id"] and base["product_url"]):
            base["store_product_id"], base["product_url"] = site[0][2]["store_product_id"], site[0][2]["product_url"]
        if site:                                               # název, značka, množství z dlaždice (stránka produktu)
            s = site[0][2]
            for f in ("brand", "name", "amount", "unit", "approx_amount", "drained_weight"):
                base[f] = s[f]
            for f in ("deposit", "deposit_type", "image_url"):
                if s[f]:
                    base[f] = s[f]
            if base["variants"] and not s["variants"]:
                base["variants"] = False
        elif not base["brand"]:                                # bez dlaždice: značka z řádku, který ji má
            base["brand"] = next((r[2]["brand"] for r in g if r[2]["brand"] and r[2]["name"] == base["name"]), "")

        # kategorie: z webu, jinak první konkrétní odhad, jinak záložní
        cats = [r[2]["category"] for r in sorted(g, key=lambda r: (r[0] not in auth, r[2]["product_url"] == "", r[1]))]
        base["category"] = next((c for c in cats if c not in FALLBACK_CATEGORIES), base["category"])
        # původní cena a srovnávací cena z řádku se stejnou cenou
        for f in ("original_price", "comparison_price", "comparison_per"):
            if not base[f]:
                base[f] = next((r[2][f] for r in g if r[2]["price"] == base["price"] and r[2][f]), "")
        base["tags"] = list(dict.fromkeys(t for r in sorted(g, key=lambda r: r[2] is not best[2]) for t in r[2]["tags"]))
        # běžný produkt: 'Verfügbar ab' jako stabilní datum (nejstarší ze zdrojů)
        if rank0 == 2 and not base["valid_from"]:
            vf = min((r[2]["valid_from"] for r in g if r[2]["valid_from"] and not r[2]["valid_to"]), default="")
            if vf:
                base["valid_from"], base["validity_source"], base["validity_confidence"] = vf, "product", "start_only"
        out.append({k: base[k] for k in PRODUCT_FIELDS})
    stats["products"] = len(out)
    return out, stats


def write_merged(folder, store, products, run_id, ts):
    country, currency = STORES[store.replace("-", "_")]
    path = os.path.join(folder, f"{ts}_{store}_merged.json")
    data = {"meta": {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "store": store.replace("-", "_"), "country": country, "currency": currency,
        "source": "merged", "type": "listing", "source_url": "merged",
        "product_count": len(products), "content_hash": content_hash(products),
        "file_id": str(uuid.uuid4()), "run_id": run_id,
    }, "products": products}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return path


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    folder = args[0] if args else outdir()
    window = timedelta(hours=next((float(a.split("=", 1)[1]) for a in argv if a.startswith("--window=")), 3))
    today = next((a.split("=", 1)[1] for a in argv if a.startswith("--today=")), date.today().isoformat())
    latest = load_latest(folder, window)
    if not latest:
        print("Ve složce nejsou žádné výstupy ke sloučení:", folder)
        return 1
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for store, files in sorted(latest.items()):
        products, st = merge_store(files, today)
        run_ids = [m.get("run_id", "") for _, m, _ in files]
        path = write_merged(folder, store, products, max(run_ids) or f"{ts}-{uuid.uuid4().hex[:8]}", ts)
        print(f"{store}: {st['rows']} řádků z {len(files)} souborů -> {st['products']} produktů "
              f"| s víc nabídkami: {st['multi_offer']} | bez ID přiřazeno k ID: {st['attached']} "
              f"| nabídka: platná akce {st['offer_rank0']}, akce od data {st['offer_rank1']}, běžná {st['offer_rank2']}, "
              f"budoucí {st['offer_rank4']}, skončená {st['offer_rank5']}")
        print("  ->", os.path.basename(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
