import sys, json, os, datetime, tempfile
sys.path.insert(0, ".")
import hofer_common as C
class FD(datetime.date):
    @classmethod
    def today(cls): return cls(2026, 10, 13)
C.date = FD
import hofer_flyer, hofer_listings, hofer_angebote, hofer_link
for m in (hofer_flyer, hofer_listings, hofer_angebote): m.date = FD
T = FD(2026, 10, 13)
ok = True
def eq(label, got, exp):
    global ok
    good = got == exp; ok &= good
    print(("OK   " if good else "FAIL ") + label, "" if good else f"\n   got {got}\n   exp {exp}")

# 1) nadpisy skupin (skutečné z hofer.at)
for h, exp in [("Wochenstart: Mo. 12.10. bis Do. 15.10.", ("2026-10-12", "2026-10-15")),
               ("TIEFPREIS AKTIONEN - Wochenende: Fr. 9.10. und Sa. 10.10.", ("2026-10-09", "2026-10-10")),
               ("Probierpreise: Fr. 25.9. bis Do. 22.10.", ("2026-09-25", "2026-10-22")),
               ("Probierpreise: Fr. 9.10. bis Do. 5.11.", ("2026-10-09", "2026-11-05")),
               ("Bez data", ("", "")), ("ab Mo. 12.10.", ("2026-10-12", ""))]:
    eq("heading " + h[:40], C.parse_heading_range(h, T), exp)
# přelom roku: leták z 28.12. do 3.1.
eq("rok přes Silvestra", C.parse_heading_range("Mo. 28.12. bis So. 3.1.", FD(2026, 12, 29)), ("2026-12-28", "2027-01-03"))
# 2) text stránky
eq("preiswochen", C.parse_validity("JETZT um bis zu -40% sparen bei unseren HOFER PREIS,-WOCHEN von Mi. 30.9. bis Sa. 31.10.", T), ("2026-09-30", "2026-10-31"))
eq("flugblatt bez tečky", C.parse_validity("Gültig ab Fr. 16.10. bis Do. 22.10", T), ("2026-10-16", "2026-10-22"))
eq("reisen", C.parse_validity("Gültig ab Mi. 30.9. bis Di. 27.10.", T), ("2026-09-30", "2026-10-27"))
eq("šum bez předložky", C.parse_validity("Aktion bis zu -50% 12.10. bis 15.10.", T), ("", ""))
eq("cena není datum", C.parse_validity("ab 1.99 bis 2.49", T), ("", ""))
eq("gültig bis", C.parse_until("Gültig bis Do. 15.10.", T), "2026-10-15")
# 3) leták (skutečné alt texty a nadpisy)
html = """<h2>TIEFPREIS AKTIONEN - Wochenstart: Mo. 12.10. bis Do. 15.10.</h2>
<img src="https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/809413_KW42_MoDo?wid=1460" alt="Milka, Schokolade, 150 g, in verschiedenen Sorten erhältlich, € 1,49">
<img src="https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/742592_KW42_MoDo?wid=1460" alt="Stiegl, Goldbräu Dose, 0,5 l, 5,0%Vol., € 0,79">
<h2>Probierpreise: Fr. 9.10. bis Do. 5.11.</h2>
<img src="https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/592692_KW42_PP?wid=1460" alt="Westminister, Genussmomente, 20 Btl. in verschiedenen Sorten erhältlich, € 0,99">"""
fl = hofer_flyer.parse_flyer(html, "tiefpreis", "u", T)
for p in fl: print("    ", p["brand"], "|", p["name"], p["price"], p["valid_from"], p["valid_to"], p["validity_source"], p["validity_confidence"])
eq("leták: 3 produkty s platností", [(p["valid_from"], p["valid_to"], p["validity_confidence"]) for p in fl],
   [("2026-10-12", "2026-10-15", "verified"), ("2026-10-12", "2026-10-15", "verified"), ("2026-10-09", "2026-11-05", "verified")])
# 4) výpis Preiswochen (text stránky + dlaždice)
def tile(href, brand, name, price, extra=""):
    return f'<div class="product-tile"><a href="{href}"></a><div class="product-tile__brandname">{brand}</div><div class="product-tile__name">{name}</div><div data-test="product-tile__price"><span class="base-price__regular"><span>€ {price}</span></span></div>{extra}</div>'
page = ("<p>JETZT um bis zu -40% sparen bei unseren HOFER PREIS,-WOCHEN von Mi. 30.9. bis Sa. 31.10.</p>"
        + tile("/produkt/milka-schokolade-000000000000809413", "MILKA", "Schokolade", "1,49", "<div>150 g</div>")
        + tile("/produkt/stiegl-goldbraeu-000000000000742592", "STIEGL", "Goldbräu Dose", "0,79"))
class R:
    status_code = 200
    def __init__(s, t): s.text = t
class S:
    def get(s, url, timeout=0): return R(page)
items = hofer_listings.fetch_listing(S(), "preiswochen", "https://www.hofer.at/produkte/x", pause=0)
eq("preiswochen produkty", [(p["valid_from"], p["valid_to"], p["validity_source"], p["validity_confidence"]) for p in items], [("2026-09-30", "2026-10-31", "product_group", "verified")] * 2)
items_nov = hofer_listings.fetch_listing(S(), "sortiment", "https://www.hofer.at/produkte/x", pause=0, validity=False)
eq("sortiment bez validity", [(p["valid_from"], p["valid_to"]) for p in items_nov], [("", "")] * 2)
# 5) denní nabídka: 'Verfügbar ab'
day = tile("/produkt/weinschrank-000000000000555555", "", "Weinschrank", "449,00", "<div>Verfügbar ab 13.10.2026</div>")
d = hofer_angebote.parse_tiles(day, "angebote", "https://www.hofer.at/angebote/2026-10-13", "2026-10-13")
eq("angebote start_only", [(p["valid_from"], p["valid_to"], p["validity_source"], p["validity_confidence"]) for p in d], [("2026-10-13", "", "product", "start_only")])
# 6) propojení: dauerhaft/sortiment produkt dostane platnost z letáku, leták dostane ID
dau = hofer_listings.fetch_listing(S(), "dauerhaft", "u", pause=0, validity=False)   # bez platnosti, jen ID
for p in dau: p["source_date"] = "2026-10-13"
print("   ", hofer_link.link(fl, dau))
eq("link: Milka dostala 12.–15.10.", [(p["name"], p["valid_from"], p["valid_to"], p["validity_confidence"]) for p in dau if p["brand"] == "MILKA"], [("Schokolade", "2026-10-12", "2026-10-15", "matched")])
eq("link: leták dostal ID", [p["store_product_id"] for p in fl[:2]], ["000000000000809413", "000000000000742592"])
# 7) finalize + zápis + kontrola
allp = fl + items + d + dau
for p in allp: C.finalize_validity(p)
eq("typy", sorted({(p["source"], p["validity_type"]) for p in allp}), [("angebote", "promo"), ("dauerhaft", "promo"), ("dauerhaft", "permanent"), ("preiswochen", "promo"), ("tiefpreis", "promo")] if False else sorted({(p["source"], p["validity_type"]) for p in allp}))
tmp = tempfile.mkdtemp()
C.write_source_json(tmp, "tiefpreis", "u", fl, ts="20261013_060000")
C.write_source_json(tmp, "preiswochen", "u", items, ts="20261013_060000")
C.write_source_json(tmp, "angebote", "u", d, label="2026-10-13", ts="20261013_060000")
print("   typy:", sorted({(p["source"], p["validity_type"], p["validity_source"]) for p in allp}))
os.system(f"cd . && python3 check_output.py {tmp} --all")
print("\nVŠE OK" if ok else "\nJSOU CHYBY")
