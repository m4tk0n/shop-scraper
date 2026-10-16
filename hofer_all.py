"""Spustí všechny zdroje najednou. Každý zdroj = jeden JSON se stejnou strukturou.

Co existuje (dny, letáky, sekce jako Weihnachten/Ostern/Grillen, kategorie sortimentu), se zjišťuje z menu hofer.at.
Letáky (Tiefpreis, Bier) jdou až po zdrojích s dlaždicemi, aby se jejich produktům dalo doplnit skutečné ID.
Výsledky se nejdřív podrží v paměti, propojí (leták <-> dlaždice: ID jedním směrem, platnost druhým,
viz hofer_link.py) a teprve potom zapíšou.
Stránky značek řeší samostatný skript brands_scrape.py (Hofer i Aldi Suisse).

    python3 hofer_all.py                       # vše, co je v menu
    python3 hofer_all.py tiefpreis bier        # jen vybrané zdroje
    python3 hofer_all.py angebote dauerhaft sortiment
    python3 hofer_all.py --food --no-ocr
"""
import hofer_angebote
import hofer_flyer
import hofer_link
import hofer_listings
import hofer_sortiment
from hofer_common import run_batches
from hofer_discover import discover


def collect(session, opts):
    disc = discover(session)
    opts = dict(opts, discovery=disc)
    wanted = set(opts["args"])
    known = set(disc["flyers"]) | set(disc["sections"]) | {"angebote", "sortiment"}
    for w in wanted - known:
        print("Neznámý zdroj:", w, "| nalezené:", sorted(known))

    def want(n):
        return not wanted or n in wanted

    batches, errors = [], []

    def run(gen):
        """Sesbírá výsledky; chyba jednoho zdroje nesmí zahodit ostatní."""
        try:
            for b in gen:
                batches.append(b)
        except Exception as e:
            errors.append(e)
            print(f"CHYBA zdroje: {type(e).__name__}: {e}")

    if want("angebote"):
        run(hofer_angebote.collect(session, dict(opts, args=[])))
    sections = [n for n in disc["sections"] if want(n)]
    if sections:
        run(hofer_listings.collect(session, dict(opts, args=sections)))
    if want("sortiment"):
        run(hofer_sortiment.collect(session, dict(opts, args=[])))
    tiles = [p for b in batches for p in b["products"]]          # produkty s ID z tohoto běhu
    n_tile_batches = len(batches)
    flyers = [n for n in disc["flyers"] if want(n)]            # až po dlaždicích: ID se doplní z nich
    if flyers:
        run(hofer_flyer.collect(session, dict(opts, args=flyers, pool=tiles)))
    flyer_items = [p for b in batches[n_tile_batches:] for p in b["products"]]
    if flyer_items and tiles:
        print("\nPropojení leták <-> dlaždice:", hofer_link.link(flyer_items, tiles))

    yield from batches
    if errors:
        raise errors[0]


if __name__ == "__main__":
    run_batches(collect)
