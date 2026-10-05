"""Rychlá kontrola, že weby odpovídají (z GitHubu se IP adresy datacenter někdy blokují)."""
import sys
from curl_cffi import requests

SITES = {"hofer": "https://www.hofer.at/flugblatt", "aldi_ch": "https://www.aldi-suisse.ch/de/"}
s = requests.Session(impersonate="chrome")
bad = []
for name, url in SITES.items():
    try:
        r = s.get(url, timeout=60)
        ok = r.status_code == 200 and len(r.text) > 20000          # blokace vrací krátkou chybovou stránku
        print(f"{name:8} status {r.status_code} | {len(r.text):>7} znaků | {'OK' if ok else 'PROBLÉM'}")
        if not ok:
            bad.append(name)
    except Exception as e:
        print(f"{name:8} CHYBA {type(e).__name__}: {e}")
        bad.append(name)
if bad:
    print("\nNedostupné:", ", ".join(bad), "- blokování IP adresy? Zkus self-hosted runner nebo spouštění z jiné sítě.")
    sys.exit(1)
