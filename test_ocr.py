"""Ruční test OCR původní ceny na jednom obrázku letáku.

    python3 test_ocr.py obrazek.png 1.29        # cesta k obrázku a akční cena
Vypíše (původní cena, procento, zdroj) a použitou šablonu.
"""
import sys
import hofer_ocr as O

path, promo = sys.argv[1], float(sys.argv[2])
data = open(path, "rb").read()
im = O._load(data)
print("šablona:", O.pick_layout(im) or "žádný žlutý box (zkusí se A)")
print(O.original_price(data, promo))
