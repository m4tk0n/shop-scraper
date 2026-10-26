"""Spustí adaptér každého aktivního obchodu (stores.active=1) podle seznamu z databáze.

Seznam se stáhne z STORES_URL (PHP endpoint stores.php, token v BRANDS_TOKEN, hlavička X-Token).
Každý obchod je zvláštní proces, protože hofer_common čte STORE při importu.

    python3 run_stores.py [--food] [--no-ocr]                  # všechny aktivní obchody
    ONLY_STORES="aldi_gb" python3 run_stores.py                # jen vybraný obchod
    python3 run_stores.py --brands [HARIBO "KÄGI" ...]         # značky
"""
import os
import subprocess
import sys

from curl_cffi import requests

ADAPTERS = {
    "hofer_at": ["hofer_all.py"],
    "aldi_ch": ["aldi_ch.py"],
    "hofer_si": ["hofer_si.py"],
    "aldi_gb": ["aldi_gb.py"],  # Zde je nově zaregistrované Aldi UK
    "aldi_us": ["aldi_us.py"],
    "aldi_hu": ["aldi_hu.py"],
    "aldi_it": ["aldi_it.py"],
    "aldi_de_sud": ["aldi_de_sud.py"],
    "aldi_au": ["aldi_au.py"],
}
BRANDS = {
    "hofer_at": ["brands_scrape.py"],
    "aldi_ch": ["brands_scrape.py"],
    "aldi_gb": ["brands_scrape.py"],
}

def load_stores():
    url = os.environ.get("STORES_URL", "").strip()
    if not url:
        print("CHYBA: chybí STORES_URL.")
        return []
    try:
        r = requests.get(url, headers={"X-Token": os.environ.get("BRANDS_TOKEN", "")}, timeout=60)
        if r.status_code == 200:
            stores = r.json().get("stores", [])
            if stores:
                return stores
    except Exception:
        pass
    return []

def main(argv):
    brands = "--brands" in argv
    argv = [a for a in argv if a != "--brands"]
    
    flags = argv if brands else [a for a in argv if a.startswith("--")]
    only = os.environ.get("ONLY_STORES", "").split()
    rc = ran = 0
    
    stores = load_stores()
    if not stores:
        print("CHYBA: Žádné obchody se nepodařilo načíst z DB.")
        return 2

    for s in stores:
        code = s["code"]
        if only and code not in only:
            continue
        cmd = (BRANDS if brands else ADAPTERS).get(code)
        if not cmd:
            print(f"\n!! {code}: aktivní v DB, ale bez registrovaného adaptéru v ADAPTERS, přeskakuji")
            continue
        print(f"\n######## {code} ({s['url']}) ########", flush=True)
        env = dict(os.environ, STORE=code.replace("-", "_"), STORE_URL=(s.get("url") or "").rstrip("/"),
                   STORE_COUNTRY=s.get("country", ""), STORE_CURRENCY=s.get("currency", ""))
        rc |= 1 if subprocess.call([sys.executable, *cmd, *flags], env=env) else 0
        ran += 1
    if not ran:
        print("CHYBA: žádný obchod se nespustil (zkontroluj ONLY_STORES nebo tabulku stores).")
        return 2
    return 1 if rc else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
