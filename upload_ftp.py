"""Nahraje změněné výstupy na server přes FTP/FTPS.

Co už je na serveru, se pozná podle souboru manifest.json ve cílové složce: nahrává se jen zdroj,
jehož content_hash se od posledního nahrání změnil. Když nahrání jednou selže, příští běh ho doplní.
Soubory se nahrávají pod dočasným názvem *.part a teprve hotové se přejmenují, takže je
čtenář (DB) nikdy neuvidí rozepsané.

Přihlašovací údaje jen z proměnných prostředí (GitHub Secrets):
    FTP_HOST, FTP_USER, FTP_PASSWORD            povinné
    FTP_DIR        cílová složka, výchozí shop-scraper/json-data
    FTP_TLS        1 = FTPS (šifrovaně), výchozí běžné FTP
    FTP_PORT       výchozí 21
    FTP_KEEP_DAYS  smaže na serveru soubory starší než N dní (0 = nemazat, výchozí)

    python upload_ftp.py [složka_s_výstupy]       # výchozí hofer_data
    python upload_ftp.py --test                   # jen zkontroluje spojení a složku
"""
import ftplib
import glob
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

NAME = re.compile(r"^(\d{8})_(\d{6})_(hofer-at|aldi-ch)_(?!brands)([a-z0-9_\-]+)\.json$")
MANIFEST = "manifest.json"
DAY = re.compile(r"_(\d{4}-\d{2}-\d{2})$")        # denní zdroje: angebote_2026-10-12


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def connect():
    host, user, pw = env("FTP_HOST"), env("FTP_USER"), env("FTP_PASSWORD")
    if not (host and user and pw):
        sys.exit("Chybí FTP_HOST, FTP_USER nebo FTP_PASSWORD (GitHub Secrets).")
    tls = env("FTP_TLS") == "1"
    ftp = ftplib.FTP_TLS(timeout=60) if tls else ftplib.FTP(timeout=60)
    ftp.connect(host, int(env("FTP_PORT", "21")))
    ftp.login(user, pw)
    if tls:
        ftp.prot_p()
    ftp.set_pasv(True)
    ftp.voidcmd("TYPE I")
    return ftp


def goto_dir(ftp, path):
    """Přejde do složky a vytvoří chybějící části cesty."""
    if path.startswith("/"):
        ftp.cwd("/")
    for part in [p for p in path.split("/") if p]:
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def remote_size(ftp, name):
    try:
        return ftp.size(name)
    except ftplib.all_errors:
        return None


def put(ftp, local_bytes, name, overwrite=False):
    """Nahraje pod dočasným názvem a po kontrole velikosti přejmenuje."""
    tmp = name + ".part"
    ftp.storbinary(f"STOR {tmp}", io.BytesIO(local_bytes))
    if remote_size(ftp, tmp) != len(local_bytes):
        raise IOError(f"{name}: velikost na serveru nesouhlasí")
    if overwrite and remote_size(ftp, name) is not None:
        ftp.delete(name)
    ftp.rename(tmp, name)


def with_retry(fn, reconnect, tries=3):
    last = None
    for i in range(tries):
        try:
            return fn()
        except ftplib.all_errors + (OSError,) as e:
            last = e
            print(f"  ! pokus {i + 1}/{tries} selhal: {type(e).__name__}: {e}")
            time.sleep(2 * (i + 1))
            if i < tries - 1:
                reconnect()
    raise last


def read_manifest(ftp):
    buf = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {MANIFEST}", buf.write)
        return json.loads(buf.getvalue().decode("utf-8"))
    except ftplib.all_errors + (ValueError,):
        return {"files": {}}


def newest_local(folder):
    best = {}
    for f in glob.glob(os.path.join(folder, "*.json")):
        m = NAME.match(os.path.basename(f))
        if not m:
            continue
        key = f"{m.group(3)}/{m.group(4)}"
        stamp = m.group(1) + m.group(2)
        if key not in best or stamp > best[key][0]:
            best[key] = (stamp, f)
    return best


def prune(ftp, keep_days):
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d")
    removed = 0
    for n in ftp.nlst():
        m = re.match(r"^(\d{8})_\d{6}_", os.path.basename(n))
        if m and m.group(1) < cutoff:
            ftp.delete(os.path.basename(n))
            removed += 1
    return removed


def main(argv):
    target = env("FTP_DIR", "shop-scraper/json-data")
    ftp = connect()
    state = {"ftp": ftp}

    def reconnect():
        try:
            state["ftp"].close()
        except Exception:
            pass
        state["ftp"] = connect()
        goto_dir(state["ftp"], target)

    goto_dir(ftp, target)
    if "--test" in argv:
        print(f"Spojení v pořádku, složka {target}, obsah: {ftp.nlst()[:10]}")
        ftp.quit()
        return 0

    folder = next((a for a in argv if not a.startswith("--")), "hofer_data")
    local = newest_local(folder)
    if not local:
        sys.exit(f"Ve složce {folder} nejsou žádné výstupy.")
    manifest = read_manifest(ftp)
    files = manifest.get("files", {})

    uploaded = skipped = 0
    for key in sorted(local):
        stamp, path = local[key]
        dm = DAY.search(key)
        if dm and dm.group(1) < datetime.now().strftime("%Y-%m-%d") and key in files:
            skipped += 1                                 # minulý den už na serveru je, nepřepisuje se
            continue
        raw = open(path, "rb").read()
        meta = json.loads(raw)["meta"]
        if files.get(key, {}).get("content_hash") == meta.get("content_hash") and meta.get("content_hash"):
            skipped += 1
            continue
        name = os.path.basename(path)
        with_retry(lambda: put(state["ftp"], raw, name, overwrite=True), reconnect)
        files[key] = {"file": name, "source": meta["source"], "source_url": meta["source_url"],
                      "product_count": meta["product_count"], "content_hash": meta["content_hash"],
                      "file_id": meta.get("file_id", ""), "generated_at": meta["generated_at"],
                      "uploaded_at": datetime.now().isoformat(timespec="seconds")}
        uploaded += 1
        print(f"  nahráno: {name} ({meta['product_count']} produktů)")

    # společné soubory (přepisují se)
    cat = os.path.join(folder, "categories.json")
    if os.path.exists(cat):
        with_retry(lambda: put(state["ftp"], open(cat, "rb").read(), "categories.json", overwrite=True), reconnect)
    manifest = {"generated_at": datetime.now().isoformat(timespec="seconds"), "files": files}
    blob = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    with_retry(lambda: put(state["ftp"], blob, MANIFEST, overwrite=True), reconnect)

    removed = 0
    keep = int(env("FTP_KEEP_DAYS", "0") or 0)
    if keep > 0:
        removed = prune(state["ftp"], keep)
    print(f"Server {env('FTP_HOST')}/{target}: nahráno {uploaded}, beze změny {skipped}, smazáno starých {removed}")
    try:
        state["ftp"].quit()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
