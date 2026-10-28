"""Kategorie obchodu uložené v DB (tabulka store_categories).

Adaptér při každém běhu pošle serveru kategorie, které našel v menu webu. Server nové přidá jako
aktivní, známé nechá být (nikdy nemaže) a vrátí příznak active. Stahují se jen aktivní kategorie;
kategorie je aktivní, jen když jsou aktivní i všichni její předci. Příznak se přepíná v administraci.

Proměnné prostředí:
    CATEGORIES_URL   adresa store_categories.php (bez ní se nic neposílá a active() je vždy True,
                     tedy stahuje se vše, jako dřív)
    BRANDS_TOKEN     token pro hlavičku X-Token
    STORE            kód obchodu (stores.code, např. aldi_gb)
    STORE_URL        adresa obchodu; z adres kategorií se uloží jen cesta

Cesty (path) jsou stabilní klíč kategorie v rámci obchodu: 'fresh-food', 'fresh-food/poultry'.
Zvláštní zdroje (denní nabídky, letáky) mají cestu začínající '@': '@angebote', '@flyer:tiefpreis'.
"""
import os
import sys

BATCH = 400                      # kategorií v jednom požadavku
NAME_MAX, PATH_MAX, URL_MAX = 150, 190, 255


class Selector:
    def __init__(self, session, store=None, base=None):
        self.session = session
        self.url = os.environ.get("CATEGORIES_URL", "").strip()
        self.token = os.environ.get("BRANDS_TOKEN", "")
        self.store = store or os.environ.get("STORE", "")
        self.base = (base or os.environ.get("STORE_URL", "")).rstrip("/")
        self.rows = {}           # path -> {"parent": path | "", "active": bool}

    @classmethod
    def disabled(cls, session):
        """Selector, který nic neposílá a nic nevypíná (výslovně zadané kategorie se stahují vždy)."""
        s = cls(session)
        s.url = ""
        return s

    @property
    def enabled(self):
        return bool(self.url)

    def _rel(self, url):
        url = url or ""
        return url[len(self.base):] if self.base and url.startswith(self.base) else url

    def sync(self, nodes):
        """nodes: [{'path', 'parent', 'name', 'url'}]. Pošle je serveru a načte příznaky active."""
        if not self.enabled:
            print("Kategorie z DB: CATEGORIES_URL není nastavená, stahuje se vše.")
            return
        by_path = {}
        for n in nodes:
            p = (n.get("path") or "").strip()
            if p and len(p) <= PATH_MAX:
                by_path[p] = {"path": p, "parent": n.get("parent") or "", "name": (n.get("name") or p)[:NAME_MAX],
                              "url": self._rel(n.get("url"))[:URL_MAX]}

        def depth(p, seen=()):
            par = by_path[p]["parent"]
            return 0 if (not par or par not in by_path or par in seen) else 1 + depth(par, seen + (p,))

        ordered = sorted(by_path.values(), key=lambda n: depth(n["path"]))      # rodiče před potomky
        added = updated = 0
        for i in range(0, max(len(ordered), 1), BATCH):
            r = self.session.post(self.url, json={"store": self.store, "categories": ordered[i:i + BATCH]},
                                  headers={"X-Token": self.token}, timeout=120)
            if r.status_code != 200:
                sys.exit(f"CHYBA: kategorie z DB ({self.store}): status {r.status_code} {r.text[:120]!r}")
            data = r.json()
            added += int(data.get("added", 0))
            updated += int(data.get("updated", 0))
            self.rows = {c["path"]: {"parent": c.get("parent") or "", "active": bool(int(c["active"]))}
                         for c in data.get("categories", [])}
        off = sorted(p for p in by_path if not self.active(p))
        print(f"Kategorie z DB ({self.store}): objeveno {len(by_path)}, nových {added}, upraveno {updated}, "
              f"vypnutých {len(off)}")
        if off:
            print("  vypnuté:", off[:40], "..." if len(off) > 40 else "")

    def active(self, path):
        """Aktivní, jen když jsou aktivní i všichni předci. Neznámá cesta nebo vypnutý Selector = True."""
        seen = set()
        while path and path not in seen and path in self.rows:
            row = self.rows[path]
            if not row["active"]:
                return False
            seen.add(path)
            path = row["parent"]
        return True


def nearest_parent(path, known):
    """Nejbližší existující předek cesty 'a/b/c' mezi známými cestami ('a/b', jinak 'a', jinak '')."""
    parts = path.split("/")
    for n in range(len(parts) - 1, 0, -1):
        cand = "/".join(parts[:n])
        if cand in known:
            return cand
    return ""
