"""Společné funkce: jednotné schéma, kategorie, zápis JSON.

Každý výstupní soubor má stejnou strukturu:
    {"meta": {generated_at, store, source, type, source_url, product_count},
     "products": [ {store_product_id, brand, name, ... , source, type}, ... ]}
"""
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import date, datetime

STORES = {"hofer_at": ("AT", "EUR"), "aldi_ch": ("CH", "CHF")}      # obchod -> (země ISO 3166-1, měna ISO 4217)
STORE = os.environ.get("STORE", "hofer_at")
COUNTRY, CURRENCY = STORES[STORE]

# source -> type (offer = akce, listing = katalog/sekce)
SOURCE_TYPES = {
    "angebote": "offer",
    "tiefpreis": "offer",
    "bier": "offer",
    "preiswochen": "offer",
    "dauerhaft": "listing",
    "weihnachten": "listing",
}


def register_source(name, type_):
    """Zaregistruje zdroj zjištěný za běhu (nová sezónní sekce, nový leták)."""
    SOURCE_TYPES.setdefault(name, type_)


# přesné pořadí a výchozí hodnoty (typ hodnoty určuje výchozí)
PRODUCT_FIELDS = {
    "store_product_id": "", "brand": "", "name": "", "amount": "", "unit": "",
    "product_url": "", "image_url": "", "category": "",
    "price": "", "original_price": "", "comparison_price": "", "comparison_per": "",
    "valid_from": "", "valid_to": "", "source_date": "", "theme": "", "tags": [],
    "deposit": "", "deposit_type": "", "approx_amount": False, "drained_weight": False,
    "variants": False, "source": "", "type": "",
}

# slug -> (český název, skupina)
CATEGORIES = {
    # potraviny
    "potraviny": ("Potraviny (ostatní)", "potraviny"),
    "maso": ("Maso", "potraviny"),
    "uzeniny": ("Uzeniny a lahůdky", "potraviny"),
    "ryby": ("Ryby a mořské plody", "potraviny"),
    "mlecne_vyrobky": ("Mléčné výrobky a vejce", "potraviny"),
    "ovoce": ("Ovoce", "potraviny"),
    "zelenina": ("Zelenina", "potraviny"),
    "orisky": ("Ořechy a sušené ovoce", "sladkosti"),
    "pecivo": ("Pečivo", "potraviny"),
    "snidane": ("Snídaně, müsli, džemy", "potraviny"),
    "testoviny_ryze": ("Těstoviny a rýže", "potraviny"),
    "koreni_omacky": ("Koření, omáčky, oleje", "potraviny"),
    "hotova_jidla": ("Hotová jídla, polévky, pizza", "potraviny"),
    "zakladni_potraviny": ("Základní potraviny (mouka, cukr, konzervy)", "potraviny"),
    # nápoje
    "napoje": ("Nealkoholické nápoje", "napoje"),
    "alkohol": ("Alkohol", "napoje"),
    "kava_caj": ("Káva a čaj", "napoje"),
    # sladké a slané
    "sladkosti": ("Sladkosti (ostatní)", "sladkosti"),
    "cokolady": ("Čokolády", "sladkosti"),
    "bonbony": ("Bonbony a gumové", "sladkosti"),
    "susenky": ("Sušenky a cukroví", "sladkosti"),
    "zmrzlina": ("Zmrzlina", "sladkosti"),
    "chipsy": ("Chipsy a slané snacky", "sladkosti"),
    # ne-potraviny
    "prani": ("Prací prostředky", "nonfood"),
    "uklid": ("Úklid a čisticí prostředky", "nonfood"),
    "hygiena": ("Hygiena a drogerie", "nonfood"),
    "domacnost": ("Domácnost", "nonfood"),
    "zahrada": ("Zahrada a rostliny", "nonfood"),
    "technika": ("Technika a elektro", "nonfood"),
    "textil": ("Textil a oblečení", "nonfood"),
    "nabytek": ("Nábytek, matrace, bydlení", "nonfood"),
    "nastroje": ("Nářadí a dílna", "nonfood"),
    "auto": ("Auto", "nonfood"),
    "zvirata": ("Zvířata", "nonfood"),
    "hracky": ("Hračky a hry", "nonfood"),
    "sport": ("Sport a volný čas", "nonfood"),
    "nonfood": ("Ostatní zboží", "nonfood"),
}
NONFOOD_CATEGORIES = {k for k, (_, g) in CATEGORIES.items() if g == "nonfood"}

# --- pravidla kategorií: (slug, slova). První shoda vyhrává. ---
# Slova do 3 znaků se musí shodovat celá, delší jako začátek slova (nebo konec, pokud ≥4 znaky).
NONFOOD_RULES = [
    ("zvirata", ("katzenfutter", "hundefutter", "tierfutter", "vogelfutter", "katzenstreu", "tiernahrung", "trockenfutter", "nassfutter", "hundesnack", "katzensnack", "leckerli")),
    ("prani", ("waschmittel", "waschpulver", "waschgel", "waschkraft", "weichspüler", "tandil", "fleckentferner", "wäscheduft")),
    ("uklid", ("reiniger", "spülmittel", "geschirrspül", "entkalker", "müllsäcke", "müllbeutel", "putzmittel", "schwamm",
               "schwämme", "wischtuch", "wc", "rohrfrei", "lufterfrischer", "spülmaschinentabs", "putztuch",
               "reinigung", "klarspüler")),
    ("hygiena", ("duschgel", "shampoo", "seife", "zahnpasta", "zahnbürste", "deo", "deodorant", "gesichtscreme", "handcreme",
                 "bodylotion", "lotion", "rasier", "windeln", "tampons", "toilettenpapier", "taschentücher", "haarspülung",
                 "mundspülung", "watte", "feuchttücher", "sonnencreme", "damenbinden", "slipeinlagen", "haargel", "haarspray", "kosmetiktücher", "wickelunterlagen", "lacura", "mamia",
                 "binden", "zahnpaste", "duschcrème", "duschcreme", "haarmaske", "pflegespülung", "deospray")),
    ("auto", ("adblue", "motoröl", "scheibenwischer", "autoreifen", "fußmatte", "frostschutz", "scheibenreiniger", "autositz")),
    ("technika", ("klimagerät", "saugroboter", "staubsauger", "fernseher", "kamera", "laptop", "tablet", "smartphone", "handy",
                  "kopfhörer", "lautsprecher", "radio", "akku", "ladegerät", "drucker", "monitor", "router", "beamer", "e-bike",
                  "balkonkraftwerk", "pv-anlage", "mini-pv", "inverter", "heizlüfter", "ventilator", "küchenmaschine", "toaster",
                  "wasserkocher", "kaffeemaschine", "fritteuse", "airfryer", "luftbefeuchter", "entfeuchter", "wecker", "lampe",
                  "leuchte", "lichterkette", "led", "kabel", "batterie", "batterien", "glühbirne", "leuchtmittel", "powerbank")),
    ("textil", ("jacke", "hose", "jeans", "pullover", "sweat", "shirt", "socken", "strumpf", "unterwäsche", "pyjama",
                "schlafanzug", "kleid", "mütze", "schal", "handschuh", "bluse", "mantel", "schuhe", "stiefel", "sandalen",
                "bettwäsche", "spannleintuch", "handtuch", "handtücher")),
    ("nabytek", ("matratze", "kaltschaum", "lattenrost", "bett", "schrank", "regal", "esstisch", "couchtisch", "schreibtisch",
                 "gartentisch", "klapptisch", "stuhl", "sofa", "liege", "sauna", "hocker", "kommode", "teppich", "vorhang",
                 "rollo", "lamelle", "pergola", "kissen", "decke", "polster")),
    ("nastroje", ("akkuschrauber", "bohrmaschine", "schraubendreher", "werkzeug", "säge", "hammer", "leiter", "schrauben",
                  "dübel", "pinsel", "winkelschleifer", "werkbank", "kabeltrommel", "lack", "buntlack", "kleber", "montagekleber")),
    ("zahrada", ("garten", "pflanze", "pflanzen", "blumen", "blumenerde", "dünger", "rasen", "hochbeet", "zaun", "gießkanne",
                 "blumentopf", "samen", "saatgut", "rasenmäher", "heckenschere")),
    ("hracky", ("spielzeug", "puzzle", "lego", "puppe", "brettspiel", "plüsch", "bausteine", "playmobil", "spielkarten", "karten", "gefühlekarten")),
    ("sport", ("fitness", "hantel", "yoga", "laufband", "crosstrainer", "fahrrad", "helm", "ski", "trampolin", "zelt",
               "schlafsack", "camping", "hometrainer", "schwimm", "velohelm", "velo", "töff")),
    ("domacnost", ("küchenrolle", "alufolie", "backpapier", "frischhaltefolie", "gefrierbeutel", "folie", "kerze", "geschirr",
                   "kochtopf", "pfanne", "besteck", "spray", "sprüh", "staub", "falle", "papier", "tischdecke", "servietten", "grillkohle", "holzkohle", "anzünder", "briketts", "grillrost", "grillzange",
                   "aluschale", "dekoration", "girlande", "fadenspray")),
]
FOOD_RULES = [
    ("zakladni_potraviny", ("kokosmilch", "kokosnussmilch", "kokoscreme", "coconut")),
    ("cokolady", ("schoko", "schokolade", "praline", "pralinen", "nougat", "mozartkugel", "bueno", "snickers", "twix", "bounty", "kitkat", "kägi", "bake", "changer", "chocolatier", "yogurette", "flachtafel", "grosstafel", "grosstafeln",
                 "rocher", "raffaello", "giotto", "duplo", "hanuta", "choceur", "moser")),
    ("bonbony", ("bonbon", "gummi", "fruchtgummi", "lachgummi", "lolli", "lutscher", "zuckerl", "kaugummi", "karamell",
                 "toffee", "haribo", "nimm2", "dragee", "smarties", "marshmallow", "lakritz", "zuckerwatte")),
    ("susenky", ("keks", "kekse", "cookie", "cookies", "waffel", "waffeln", "lebkuchen", "spekulatius", "stollen", "oblate", "printen",
                 "zimtstern", "kipferl", "makronen", "plätzchen", "guetzli", "guetzlis", "biberli", "läckerli", "brezeli","biskuits", "biskuit", "oreo", "spitzbuben", "amaretti", "biber", "bärli", "mandelblätter", "biscuit", "biscoff", "löffelbiskuit", "manner", "schnitten", "lebzelt", "magenbrot")),
    ("zmrzlina", ("eis", "eiscreme", "speiseeis", "eisbecher", "sorbet", "magnum", "cornetto", "eistorte", "glace", "glacé")),
    ("sladkosti", ("riegel", "pudding", "torte", "kuchen", "gugelhupf", "muffin", "brownie", "donut", "krapfen", "konfekt",
                   "baumkuchen", "panettone", "dessert", "marzipan", "nikolo", "krampus", "adventkalender", "punschkrapfen",
                   "fruchtschnitte", "kompott", "dominostein", "dominosteine", "kuppeln", "strudel", "meringues", "meringue", "puffs", "eclairs", "éclairs", "knoppers", "toffifee", "rumpflaume",
                   "kokoswürfel", "kokoskuppeln")),
    ("chipsy", ("chips", "chipsi", "pufuleti", "flips", "erdnussflips", "nachos", "popcorn", "knabber", "snack", "cracker",
                "salzstangen", "kartoffelsticks", "doritos", "pringles", "zweifel", "tyrrells", "grissotti", "grissini")),
    ("alkohol", ("bier", "radler", "wein", "zweigelt", "veltliner", "riesling", "rosé", "sekt", "prosecco", "spritzer", "likör",
                 "schnaps", "vodka", "wodka", "whisky", "gin", "rum", "cognac", "brandy", "glühwein", "aperol", "spirituose",
                 "märzen", "pils", "helles", "weizen", "stout", "lager", "most", "cider", "grappa", "tequila", "champagner", "bowle",
                 "rotwein", "weißwein", "weisswein", "schaumwein", "weinbrand", "gösser", "puntigamer", "ottakringer",
                 "wieselburger", "zipfer", "stiegl", "hirter", "schwechater", "egger", "corona", "heineken", "budweiser",
                 "paulaner", "erdinger", "franziskaner", "warsteiner", "krombacher", "desperados", "guinness", "kozel",
                 "pilsner", "stella", "asahi", "schladminger", "villacher", "kaiser", "edelweiss", "freistädter",
                 "feldschlösschen", "eichhof", "calanda", "cardinal", "hürlimann", "aoc", "aop", "vdp", "doc", "docg", "igt",
                 "cuvée", "fendant", "dézaley", "féchy", "saphorin", "chasselas", "pinot", "merlot", "gamay", "chardonnay",
                 "cabernet", "primitivo", "chianti", "vino", "dôle", "crémant", "sauvignon", "syrah",
                 "tempranillo", "malbec", "barolo")),
    ("kava_caj", ("kaffee", "coffee", "espresso", "cappuccino", "caffè", "caffe", "kaffeekapseln", "kaffeepads", "kaffeesticks",
                  "tee", "teebeutel", "kakao")),
    ("napoje", ("cola", "limonade", "limo", "fanta", "sprite", "saft", "nektar", "smoothie", "wasser", "sprudel", "sirup",
                "eistee", "energy", "drink", "getränk", "latte", "tonic", "ginger", "kombucha", "hafermilch", "sojadrink", "rivella", "schorle")),
    ("koreni_omacky", ("gewürz", "spices", "gewürzmischung", "pfeffer", "paprikapulver", "curry", "zimt", "senf", "ketchup",
                       "mayonnaise", "mayo", "sauce", "soße", "dressing", "essig", "sugo", "pesto", "brühe", "fond", "salz",
                       "meersalz", "olivenöl", "speiseöl", "bratöl", "salatöl", "kürbiskernöl", "traubenkernöl", "kokosöl", "sonnenblumenöl", "rapsöl", "kokosfett", "bratfett", "margarine", "schmalz", "vanilleschoten", "vanille", "mohn", "balsamico", "aromat")),
    ("uzeniny", ("wurst", "würstel", "schinken", "speck", "salami", "aufschnitt", "leberkäse", "landjäger", "bratwurst",
                 "selchfleisch", "mortadella", "kaminwurzen", "extrawurst", "debreziner", "knacker", "pastete", "prosciutto", "prociutto", "selch", "bratwürstel", "würstchen", "bresaola", "pancetta", "coppa", "lyoner", "cotto", "bratwürste", "bratwürstchen")),
    ("ryby", ("fisch", "lachs", "räucherlachs", "thunfisch", "hering", "garnelen", "forelle", "makrele", "scampi", "meeresfrüchte",
              "sardinen", "kabeljau", "pangasius", "surimi", "fischstäbchen", "matjes", "anchovis", "seafood", "frutti")),
    ("maso", ("fleisch", "schwein", "schweins", "rind", "kalb", "hendl", "huhn", "hühner", "pute", "puten", "chicken", "schnitzel",
              "faschiert", "faschiertes", "steak", "filet", "hack", "karree", "braten", "haxe", "lamm", "ente", "gans",
              "gulasch", "rippen", "beiried", "tafelspitz", "spieß", "burger", "knusperbauch", "bbq", "bauch",
              "poulet", "geschnetzeltes", "entrecôte", "geflügel", "truten", "weiderind", "plätzli", "minutenplätzli", "pork")),
    ("mlecne_vyrobky", ("milch", "käse", "joghurt", "topfen", "butter", "obers", "sahne", "mascarpone", "mozzarella", "gouda",
                        "quark", "schlagobers", "frischkäse", "ei", "eier", "emmentaler", "camembert", "parmesan", "skyr",
                        "buttermilch", "kefir", "rahm", "feta", "ricotta", "schmelzkäse", "tilsiter", "fraicho", "padano", "parmigiano", "pecorino", "gorgonzola", "brie", "halloumi", "raclette", "babybel", "jogurt", "jogurts", "cheddar", "cottage", "epi", "kiri", "dippi", "bergkäse", "hartkäse", "osterei", "ostereier")),
    ("ovoce", ("obst", "apfel", "äpfel", "birne", "birnen", "banane", "bananen", "trauben", "beeren", "erdbeer", "orange",
               "orangen", "zitrone", "zitronen", "mandarine", "mandarinen", "kiwi", "ananas", "melone", "marille", "marillen",
               "zwetschke", "zwetschken", "pfirsich", "kirsche", "kirschen", "himbeer", "heidelbeer", "heidelbeeren", "mango",
               "avocado", "grapefruit", "satsuma", "satsumas", "clementine", "clementinen", "granatapfel", "litschi", "physalis",
               "papaya", "früchte", "früchtemischung", "nektarine", "pflaume", "pflaumen", "cranberr", "preiselbeer", "berggolden", "obstkorb")),
    ("zelenina", ("gemüse", "karotte", "karotten", "kartoffel", "kartoffeln", "erdäpfel", "zwiebel", "zwiebeln", "tomate",
                  "tomaten", "gurke", "gurken", "paprika", "salat", "kohl", "kraut", "kürbis", "brokkoli", "spinat", "sellerie",
                  "lauch", "pilze", "champignon", "kohlrabi", "radieschen", "rübe", "rüben", "mais", "knoblauch", "zucchini",
                  "melanzani", "fenchel", "spargel", "rotkraut", "weißkraut", "ingwer", "petersilie", "schnittlauch", "käferbohnen", "chicoree", "kimchi", "antipasti", "cornichons", "essiggurken")),
    ("orisky", ("nuss", "nüsse", "mandel", "mandeln", "walnuss", "walnüsse", "haselnuss", "haselnüsse", "pistazie", "pistazien",
                "cashew", "erdnuss", "erdnüsse", "kerne", "sonnenblumenkerne", "kürbiskerne", "studentenfutter", "rosinen",
                "datteln", "feigen", "trockenfrüchte", "trockenobst", "kokosraspeln", "leinsamen", "chiasamen", "marroni", "maroni", "kastanien", "pekan")),
    ("pecivo", ("brot", "semmel", "semmeln", "gebäck", "brötchen", "bagel", "brioche", "toast", "laugen", "laugenstangerl",
                "laugenbrezel", "croissant", "baguette", "backbox", "stangerl", "weckerl", "kornspitz", "brezel", "bun", "wraps",
                "fladenbrot", "knäckebrot", "zwieback", "osterbrot", "osterpinze", "osterkranz", "osterlamm", "knuspi")),
    ("testoviny_ryze", ("nudel", "nudeln", "pasta", "spaghetti", "penne", "fusilli", "tagliatelle", "reis", "couscous", "polenta",
                        "gnocchi", "bulgur", "quinoa", "tortellini", "teigwaren", "hörnli", "spätzli", "spaetzli", "spiralen")),
    ("snidane", ("müsli", "cornflakes", "cereal", "cerealien", "haferflocken", "marmelade", "konfitüre", "aufstrich", "honig",
                 "nutella", "porridge", "frühstück", "nusscreme", "schokocreme", "nutoka", "duo", "brunch", "müesli")),
    ("hotova_jidla", ("pizza", "lasagne", "fertiggericht", "gericht", "suppe", "suppen", "eintopf", "knödel", "fertig", "burrito",
                      "falafel", "sushi", "salatschüssel", "teigtaschen", "ravioli", "kroketten", "pommes", "fritten", "nuggets", "dog", "spizzico", "sandwich", "sandwiches", "pulled")),
    ("zakladni_potraviny", ("mehl", "zucker", "backmischung", "backpulver", "hefe", "konserve", "bohnen", "linsen", "erbsen",
                            "kichererbsen", "tomatenmark", "passata", "puddingpulver", "stärke", "gelatine", "tofu", "seitan", "protein", "whey", "hülsenfrüchte", "dicksaft", "agavendicksaft", "mohn", "backtrennspray")),
]
DRINK_FIRST = ("schokomilch", "trinkschoko", "kakaogetränk", "alkoholfrei", "alkoholfreies", "alkoholfreie")
COFFEE_EXCLUDE = ("spices", "gewürz")      # "Coffee Spices" je koření, ne káva
BRAND_CATEGORY = {
    "mulino": "susenky", "milsani": "mlecne_vyrobky", "knorr": "hotova_jidla",
    "schweppes": "napoje", "incarom": "koreni_omacky",
    "dove": "hygiena", "pantene": "hygiena", "rexona": "hygiena", "colgate": "hygiena", "always": "hygiena",
    "dettol": "hygiena", "cif": "uklid", "finish": "uklid", "pattex": "nastroje",
    "purina": "zvirata", "whiskas": "zvirata", "sheba": "zvirata", "pedigree": "zvirata",
}
# značky sladkostí: platí po slovech jako "kekse", ale dřív než obecná slova jako "riegel" a "milch"
SWEET_BRANDS = {"kinder": "cokolady", "milka": "cokolady", "lindt": "cokolady",
                "toblerone": "cokolady", "ritter": "cokolady", "haribo": "bonbony", "mingles": "bonbony"}

TAG_BADGES = {"kühlung": "kuehlung", "tiefkühlung": "tiefkuehlung", "vegan": "vegan", "onlineshop": "onlineshop",
              "tiefpreisaktion": "tiefpreisaktion", "gekühlt": "kuehlung", "tiefgekühlt": "tiefkuehlung",
              "vegetarisch": "vegetarisch", "tiefpreis": "tiefpreis"}


# ---------- text a čísla ----------
def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def tokens_of(*parts):
    return re.findall(r"[a-zäöüßéèàç0-9]+", " ".join(parts).lower())


# slova, která smí odpovídat i na konci složeného slova (Orangensaft, Hendlbrustfilet, Kartoffelchips)
SUFFIX_OK = {
    "saft", "wasser", "bier", "radler", "wurst", "schinken", "käse", "fleisch", "filet", "steak", "schnitzel", "braten",
    "hendl", "suppe", "brot", "kuchen", "torte", "riegel", "schokolade", "keks", "salat", "nudeln", "reiniger",
    "waschmittel", "spülmittel", "kaffee", "tee", "creme", "gebäck", "öl", "essig", "sauce", "soße", "mehl", "zucker",
    "joghurt", "butter", "milch", "limonade", "drink", "folie", "papier", "chips", "beeren", "kraut", "nuss", "kerne",
    "likör", "gummi", "bonbons", "aufstrich", "marmelade", "wasserflasche", "tabs", "tuch", "schwamm", "kabel",
    "tomaten", "tomate", "gurken", "würstel", "kerze", "leuchte", "karten", "marzipan", "fett", "schoten", "makronen",
    "apfel", "topfen", "rahm", "gemüse", "spritzer", "trockenfutter", "nassfutter", "matjesfilet", "bresaola", "strudel", "quark", "shampoo", "schorle", "müesli", "müsli", "suppen", "ketchup", "brötchen", "kekse", "jogurt", "kleber", "waffeln",
}
INFIX_OK = {"marzipan"}                     # smí být kdekoli ve slově (Edelmarzipantaler)
EXACT = {"schal", "kinder", "led", "ei", "eis", "gin", "rum", "wc", "deo", "ski", "most", "bun", "hose", "bake", "epi"}


def _hit(tokens, words):
    for t in tokens:
        for w in words:
            if w in EXACT or len(w) <= 3:
                if t == w:
                    return True
            elif t.startswith(w) or (w in SUFFIX_OK and t.endswith(w)) or (w in INFIX_OK and w in t):
                return True
    return False


PRICE_RE = re.compile(r"(\d{1,3}(?:[.'’]\d{3})+|\d+)[,.](\d{2})(?!\d)")
SIZE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?)\s*(kg|g|ml|cl|l|stk|m|cm)?\s*(/\s*atg)?\s*$", re.I)


def price(s):
    m = PRICE_RE.search(s or "")
    if not m:
        return ""
    return str(int(re.sub(r"[.'’]", "", m.group(1)))) + "." + m.group(2)


def parse_size(s):
    """-> (amount, unit, drained_weight, approx)"""
    s = clean(s)
    if not s:
        return "", "", False, False
    s = re.sub(r"(?<=\d)[’'](?=\d{3}\b)", "", s)                 # švýcarské tisíce: 1’000 g
    approx = bool(re.search(r"ungef|\bca\b", s, re.I))
    m = SIZE_RE.match(s.replace("KG/ATG", "kg /atg").replace("G/ATG", "g /atg"))
    if m:
        return m.group(1).replace(",", ".").replace(" ", ""), (m.group(2) or "").lower(), bool(m.group(3)), approx
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|l)\b", s, re.I)
    if m:
        return m.group(1).replace(",", "."), m.group(2).lower(), "atg" in s.lower(), approx
    return "", "", False, approx


def amount_key(amount, unit):
    """Množství v základních jednotkách (g, ml): 0.5 kg -> 500g, 12x0.5 l -> 12x500ml. Pro párování stejných produktů."""
    if not amount or not unit:
        return ""
    mult, base = {"kg": (1000, "g"), "g": (1, "g"), "l": (1000, "ml"), "ml": (1, "ml"), "cl": (10, "ml")}.get(unit, (1, unit))
    try:
        parts = [float(x) for x in str(amount).split("x")]
    except ValueError:
        return f"{amount}{unit}"
    count = [f"{v:g}" for v in parts[:-1]]               # počet kusů se jednotkou nenásobí
    return "x".join(count + [f"{parts[-1] * mult:g}"]) + base


def match_key(brand, name, amount, unit):
    """Klíč pro párování stejného produktu mezi zdroji a časem: značka + jméno + množství, vše normalizované."""
    def n(s):
        return re.sub(r"[^a-zäöüß0-9]+", " ", (s or "").lower()).strip()
    return (n(brand), n(name), amount_key(amount, unit))


def slug(s):
    s = clean(s).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("à", "a")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9+]+", "_", s).strip("_")


# ---------- kategorie a tagy ----------
def categorize(brand, name, unit="", tags=(), default_group=None):
    """default_group='food' pro stránky, které jsou jistě potraviny (fallback 'potraviny')."""
    tk = tokens_of(brand, name)
    for slug_, words in NONFOOD_RULES:
        if _hit(tk, words):
            return slug_
    if _hit(tk, DRINK_FIRST):
        return "napoje"
    for slug_, words in FOOD_RULES:
        if slug_ == "kava_caj" and _hit(tk, COFFEE_EXCLUDE):
            continue
        if slug_ == "napoje" and "dicksaft" in " ".join(tk):
            continue
        if _hit(tk, words):
            return slug_
        if slug_ == "zmrzlina":
            for t in tokens_of(brand):
                if t in SWEET_BRANDS:
                    return SWEET_BRANDS[t]
    for t in tokens_of(brand):
        if t in BRAND_CATEGORY:
            return BRAND_CATEGORY[t]
    if default_group == "food" or unit in ("g", "kg", "l", "ml") or any(t in ("kuehlung", "tiefkuehlung") for t in tags):
        return "potraviny"
    return "nonfood"


def derive_tags(brand, name, badges=()):
    out = []

    def add(t):
        if t and t not in out:
            out.append(t)
    for b in badges:
        add(TAG_BADGES.get(clean(b).lower(), slug(b)))
    tk = tokens_of(brand, name)
    if "bio" in tk or "organic" in tk or "ursprung" in tk:
        add("bio")
    if any(t.startswith("vegan") or t in ("pflanzlich", "pflanzliche") for t in tk):
        add("vegan")
    for w in ("laktosefrei", "glutenfrei", "zuckerfrei", "alkoholfrei", "alkoholfreies"):
        if w in tk:
            add("alkoholfrei" if w.startswith("alkoholfrei") else w)
    return out


# ---------- schéma a zápis ----------
def make_product(source, **kw):
    """Vrátí záznam přesně podle PRODUCT_FIELDS (správné typy, správné pořadí)."""
    kw.setdefault("source", source)
    kw.setdefault("type", SOURCE_TYPES.get(source, "listing"))
    out = {}
    for k, default in PRODUCT_FIELDS.items():
        v = kw.get(k, default)
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, list):
            v = list(v or [])
        else:
            v = "" if v is None else str(v)
        out[k] = v
    return out


def outdir():
    p = "/sdcard/Download/hofer_data"
    if os.path.exists("/sdcard") and os.access("/sdcard", os.W_OK):
        os.makedirs(p, exist_ok=True)
        return p
    os.makedirs("hofer_data", exist_ok=True)
    return "hofer_data"


def content_hash(products):
    """SHA-256 obsahu produktů. Nezahrnuje source_date (mění se každý den), takže stejná data = stejný otisk."""
    rows = [{k: v for k, v in p.items() if k != "source_date"} for p in products]
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_source_json(out_dir, source, source_url, products, label="", ts=None, run_id=None):
    ts = ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{ts}_{STORE.replace('_', '-')}_{source}{'_' + label if label else ''}.json"
    path = os.path.join(out_dir, name)
    data = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "store": STORE,
            "country": COUNTRY,
            "currency": CURRENCY,
            "source": source,
            "type": SOURCE_TYPES.get(source, "listing"),
            "source_url": source_url,
            "product_count": len(products),
            "content_hash": content_hash(products),
            "file_id": str(uuid.uuid4()),
            "run_id": run_id or str(uuid.uuid4()),
        },
        "products": products,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return path


def write_categories(out_dir):
    path = os.path.join(out_dir, "categories.json")
    data = {k: {"name_cs": n, "group": g} for k, (n, g) in CATEGORIES.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return path


def run_batches(collect, argv=None, session=None):
    """Společný běh: collect(session, opts) -> [{'source','source_url','label','products'}] ; zapíše soubory."""
    from curl_cffi import requests
    argv = sys.argv[1:] if argv is None else argv
    opts = {"food": "--food" in argv, "no_ocr": "--no-ocr" in argv,
            "args": [a for a in argv if not a.startswith("--")]}
    session = session or requests.Session(impersonate="chrome")
    out = outdir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{ts}-{uuid.uuid4().hex[:8]}"
    total, files = 0, []
    for b in collect(session, opts):
        products = b["products"]
        if opts["food"]:
            products = [p for p in products if p["category"] not in NONFOOD_CATEGORIES]
        if not products:
            print(f"  -> {b['source']} {b.get('label', '')}: 0 produktů, soubor se nevytváří")
            continue
        path = write_source_json(out, b["source"], b["source_url"], products, b.get("label", ""), ts, run_id)
        files.append((path, len(products)))
        total += len(products)
        cats = {}
        for p in products:
            cats[p["category"]] = cats.get(p["category"], 0) + 1
        print(f"  -> {os.path.basename(path)}: {len(products)} produktů | {dict(sorted(cats.items(), key=lambda x: -x[1]))}")
    write_categories(out)
    print(f"\nHotovo: {total} produktů v {len(files)} souborech, složka: {out}")
    if not files:
        print("CHYBA: žádný výstup (web blokuje požadavky nebo se změnila struktura stránky).")
        sys.exit(2)
    return files
