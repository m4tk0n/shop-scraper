"""Spustí adaptér každého aktivního obchodu (stores.active=1) podle seznamu z databáze.

Seznam se stáhne z STORES_URL (PHP endpoint stores.php, token v BRANDS_TOKEN, hlavička X-Token).
Když stažení selže, použije se záložní seznam FALLBACK.
Každý obchod je zvláštní proces, protože hofer_common čte STORE při importu.

    python3 run_stores.py [--food] [--no-ocr]
    ONLY_STORES="hofer-si" python3 run_stores.py      # jen vybrané kódy (při testování)
"""
import os
import subprocess
import sys

from curl_cffi import requests

# kód obchodu (stores.code) -> skript, který ho umí stáhnout
ADAPTERS = {
    "hofer-at": ["hofer_all.py"],
    "aldi-ch": ["aldi_ch.py"],
    # "hofer-si": ["hofer_si.py"],       # přibude po sondě (probe_store.py)
}
FALLBACK = [
    {"code": "hofer-at", "url": "https://www.hofer.at", "country": "AT", "currency": "EUR"},
    {"code": "aldi-ch", "url": "https://www.aldi-suisse.ch", "country": "CH", "currency": "CHF"},
]


def load_stores():
    url = os.environ.get("STORES_URL", "").strip()
    if url:
        try:
            r = requests.get(url, headers={"X-Token": os.environ.get("BRANDS_TOKEN", "")}, timeout=60)
            if r.status_code == 200:
                stores = r.json().get("stores", [])
                if stores:
                    print(f"Obchody z databáze: {[s['code'] for s in stores]}")
                    return stores
                print("Server vrátil prázdný seznam aktivních obchodů.")
                return []
            print(f"Seznam obchodů: status {r.status_code}")
        except Exception as e:
            print(f"Seznam obchodů: chyba ({type(e).__name__})")
    print("Používám záložní seznam:", [s["code"] for s in FALLBACK])
    return FALLBACK


def main(argv):
    flags = [a for a in argv if a.startswith("--")]            # zdroje se nepředávají, každý obchod má jiné
    only = os.environ.get("ONLY_STORES", "").split()
    rc = ran = 0
    for s in load_stores():
        code = s["code"]
        if only and code not in only:
            continue
        cmd = ADAPTERS.get(code)
        if not cmd:
            print(f"\n!! {code}: aktivní v DB, ale bez adaptéru (ADAPTERS), přeskakuji")
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
