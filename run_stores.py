"""Spustí adaptér každého aktivního obchodu (stores.active=1) podle seznamu z databáze.

Seznam se stáhne z STORES_URL (PHP endpoint stores.php, token v BRANDS_TOKEN, hlavička X-Token).
Když stažení selže, nespustí se nic (v kódu nejsou žádné záložní adresy).
Každý obchod je zvláštní proces, protože hofer_common čte STORE při importu.

    python3 run_stores.py [--food] [--no-ocr]              # akce a sortiment všech aktivních obchodů
    python3 run_stores.py --brands [HARIBO "KÄGI" ...]     # značky (jen obchody v BRANDS)
    ONLY_STORES="hofer_si" python3 run_stores.py           # jen vybrané kódy (při testování)
"""
import os
import subprocess
import sys

from curl_cffi import requests

# kód obchodu (stores.code) -> skript, který ho umí stáhnout
ADAPTERS = {
    "hofer_at": ["hofer_all.py"],
    "aldi_ch": ["aldi_ch.py"],
    "hofer_si": ["hofer_si.py"],
}
# kód obchodu -> skript pro stránky značek (režim --brands)
BRANDS = {
    "hofer_at": ["brands_scrape.py"],
    "aldi_ch": ["brands_scrape.py"],
}


def load_stores():
    url = os.environ.get("STORES_URL", "").strip()
    if not url:
        print("CHYBA: chybí STORES_URL (adresa stores.php).")
        return []
    try:
        r = requests.get(url, headers={"X-Token": os.environ.get("BRANDS_TOKEN", "")}, timeout=60)
    except Exception as e:
        print(f"CHYBA: seznam obchodů z DB se nepodařilo stáhnout ({type(e).__name__}).")
        return []
    if r.status_code != 200:
        print(f"CHYBA: seznam obchodů, status {r.status_code}.")
        return []
    stores = r.json().get("stores", [])
    if not stores:
        print("Server vrátil prázdný seznam aktivních obchodů.")
        return []
    print(f"Obchody z databáze: {[s['code'] for s in stores]}")
    return stores


def main(argv):
    brands = "--brands" in argv
    argv = [a for a in argv if a != "--brands"]
    # u značek se předávají i jména značek, jinak jen přepínače (zdroje má každý obchod jiné)
    flags = argv if brands else [a for a in argv if a.startswith("--")]
    only = os.environ.get("ONLY_STORES", "").split()
    rc = ran = 0
    for s in load_stores():
        code = s["code"]
        if only and code not in only:
            continue
        cmd = (BRANDS if brands else ADAPTERS).get(code)
        if not cmd:
            print(f"\n!! {code}: aktivní v DB, ale bez adaptéru, přeskakuji")
            continue
        print(f"\n######## {code} ({s['url']}) ########", flush=True)
        env = dict(os.environ, STORE=code.replace("-", "_"), STORE_URL=(s.get("url") or "").rstrip("/"),
                   STORE_COUNTRY=s.get("country", ""), STORE_CURRENCY=s.get("currency", ""))
        rc |= 1 if subprocess.call([sys.executable, *cmd, *flags], env=env) else 0
        ran += 1
    if not ran:
        print("CHYBA: žádný obchod se nespustil.")
        return 2
    return 1 if rc else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
