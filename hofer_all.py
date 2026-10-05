"""Spustí všechny zdroje najednou. Každý zdroj = jeden JSON se stejnou strukturou.

Co existuje (dny, letáky, sekce jako Weihnachten/Ostern/Grillen, kategorie sortimentu), se zjišťuje z menu hofer.at.
Letáky (Tiefpreis, Bier) jdou až po zdrojích s dlaždicemi, aby se jejich produktům dalo doplnit skutečné ID.
Stránky značek (marken) se zpracují, pokud existuje soubor znacky.txt; jdou jako poslední,
takže --auto může doplnit značky z dat získaných v tomtéž běhu.

    python3 hofer_all.py                       # vše, co je v menu (+ značky ze znacky.txt)
    python3 hofer_all.py tiefpreis bier        # jen vybrané zdroje
    python3 hofer_all.py angebote dauerhaft marken sortiment
    python3 hofer_all.py --food --no-ocr --auto
"""
import hofer_angebote
import hofer_flyer
import hofer_listings
import hofer_marken
import hofer_sortiment
from hofer_common import run_batches
from hofer_discover import discover


def collect(session, opts):
    disc = discover(session)
    opts = dict(opts, discovery=disc)
    wanted = set(opts["args"])
    known = set(disc["flyers"]) | set(disc["sections"]) | {"angebote", "marken", "sortiment"}
    for w in wanted - known:
        print("Neznámý zdroj:", w, "| nalezené:", sorted(known))

    def want(n):
        return not wanted or n in wanted

    if want("angebote"):
        yield from hofer_angebote.collect(session, dict(opts, args=[]))
    sections = [n for n in disc["sections"] if want(n)]
    if sections:
        yield from hofer_listings.collect(session, dict(opts, args=sections))
    if want("sortiment"):
        yield from hofer_sortiment.collect(session, dict(opts, args=[]))
    flyers = [n for n in disc["flyers"] if want(n)]            # až po dlaždicích: ID se doplní z nich
    if flyers:
        yield from hofer_flyer.collect(session, dict(opts, args=flyers))
    if want("marken") and hofer_marken.read_watchlist():
        yield from hofer_marken.collect(session, dict(opts, args=[]))


if __name__ == "__main__":
    run_batches(collect)
