#!/usr/bin/env python3
"""Match a label ingredient name (US INCI as printed, or an FDA filed name) to the
CosIng record of the same ingredient."""
import gzip, json, os, re, functools

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
COSING = os.path.join(ROOT, "data/reference/cosing/cosing_ingredients.jsonl.gz")

# US label name -> EU INCI name (the US and EU INCI differ for these)
US_EU = {"WATER": "AQUA", "FRAGRANCE": "PARFUM", "MINERAL OIL": "PARAFFINUM LIQUIDUM", "BEESWAX": "CERA ALBA",
         "PURIFIED WATER": "AQUA", "DEIONIZED WATER": "AQUA", "DISTILLED WATER": "AQUA", "ALCOHOL": "ALCOHOL",
         "TITANIUM DIOXIDE": "CI 77891", "IRON OXIDES": "CI 77491", "MICA": "MICA", "FLAVOR": "AROMA",
         "CANDELILLA WAX": "EUPHORBIA CERIFERA CERA", "CARNAUBA WAX": "COPERNICIA CERIFERA CERA",
         "ALOE BARBADENSIS LEAF JUICE": "ALOE BARBADENSIS LEAF JUICE", "VITAMIN E": "TOCOPHEROL",
         "ULTRAMARINES": "CI 77007", "CHROMIUM OXIDE GREENS": "CI 77288", "YELLOW WAX": "CERA ALBA",
         "WHITE WAX": "CERA ALBA", "OZOKERITE": "OZOKERITE", "SILICA": "SILICA", "ETHANOL": "ALCOHOL",
         "PETROLATUM": "PETROLATUM", "PARAFFIN": "PARAFFIN", "LANOLIN": "LANOLIN", "TALC": "TALC",
         "CARMINE": "CI 75470", "BISMUTH OXYCHLORIDE": "CI 77163", "MANGANESE VIOLET": "CI 77742",
         "FERRIC FERROCYANIDE": "CI 77510", "ZINC OXIDE": "ZINC OXIDE", "CHROMIUM HYDROXIDE GREEN": "CI 77289",
         "SODIUM HYALURONATE": "SODIUM HYALURONATE", "CAPRYLIC/CAPRIC TRIGLYCERIDE": "CAPRYLIC/CAPRIC TRIGLYCERIDE"}
_IRON = re.compile(r"^IRON OXIDES?\s*\(?C\.?I\.?\s*(77491|77492|77499)\)?$")
_CI = re.compile(r"\bC\.?\s?I\.?\s*(\d{5})\b")
_FDC = {"RED 40": "CI 16035", "YELLOW 5": "CI 19140", "YELLOW 6": "CI 15985", "BLUE 1": "CI 42090", "RED 33": "CI 17200",
        "RED 28": "CI 45410", "RED 7": "CI 15850", "RED 6": "CI 15850", "RED 27": "CI 45410", "RED 30": "CI 73360",
        "RED 21": "CI 45380", "RED 22": "CI 45380", "ORANGE 5": "CI 45370", "GREEN 3": "CI 42053", "GREEN 5": "CI 61570",
        "VIOLET 2": "CI 60725", "YELLOW 10": "CI 47005", "YELLOW 11": "CI 47000", "BLUE 4": "CI 42090", "GREEN 6": "CI 61565"}
_NOISE = re.compile(r"\*+|†|‡|\bCERTIFIED\b|\bORGANIC\b|\bUSDA\b|\bNATURAL\b|\bNON-?GMO\b|\bCOLD[- ]PRESSED\b|\bVIRGIN\b|\bEXTRA\b", re.I)


def fold(s):
    s = (s or "").upper().replace("&AMP;", "&").replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s


def k(s):
    return re.sub(r"[^A-Z0-9]", "", fold(s))


@functools.lru_cache(maxsize=1)
def index():
    by = {}
    recs, raw = [], []
    for line in gzip.open(COSING, "rt", encoding="utf-8"):
        r = json.loads(line)
        if not r["inciName"]:
            continue
        rec = {"inci": r["inciName"][0], "functions": list(dict.fromkeys(r["functionName"])),
               "status": (r["status"] or [None])[0], "annex": r["annexNo"], "ref": r["refNo"], "cas": r["casNo"],
               "restriction": r["cosmeticRestriction"], "max": r["maximumConcentration"],
               "perfuming": (r["perfuming"] or [None])[0], "id": (r["substanceId"] or [None])[0]}
        recs.append(rec)
        raw.append(r)
    # exact names first; a bracket-stripped name only where no exact name has that key,
    # and never from a name that starts with a bracket ("(VETIVERIA ...) WATER" is not WATER)
    loose = {}
    for rec, r in zip(recs, raw):
        for n in set(r["inciName"]) | set(r["inciUsaName"]):
            key = k(n)
            if key and (key not in by or (by[key]["status"] != "Active" and rec["status"] == "Active")):
                by[key] = rec
            if not n.strip().startswith("("):
                sk = k(re.sub(r"\([^()]*\)", "", n))
                if sk and sk != key:
                    loose.setdefault(sk, []).append(rec)
    for sk, rs in loose.items():
        if sk not in by and len({x["inci"] for x in rs}) == 1:     # unambiguous only
            by[sk] = rs[0]
    return by


def candidates(name):
    """Readings of a label name, most literal first."""
    u = fold(_NOISE.sub(" ", name or ""))
    u = re.sub(r"\s+", " ", u).strip(" .,;:")
    out = [u]
    out.append(re.sub(r"\([^()]*\)|\[[^\[\]]*\]", " ", u))                      # "OLEA EUROPAEA (OLIVE) FRUIT OIL"
    out.append(re.sub(r"[()]", " ", u))                                         # "(SHEA) BUTTER" -> SHEA BUTTER
    for m in re.findall(r"\(([^()]*)\)", u):                                      # "WATER (AQUA)" -> AQUA
        out.append(m)
    for part in re.split(r"\s*/\s*|\s*\\\s*", u):                                 # "WATER/AQUA/EAU"
        out.append(part)
    out.append(re.sub(r"^(FD&C|D&C|EXT\.? D&C)\s+", "", u).replace("NO. ", "").replace("NO.", ""))
    res = []
    GENERIC1 = {"BUTTER", "OIL", "EXTRACT", "WATER", "WAX", "POWDER", "JUICE", "SEED", "LEAF", "FLOWER", "ROOT",
                "FRUIT", "COLOR", "COLOUR", "STARCH", "PROTEIN", "FLOUR", "MILK", "GUM", "RESIN", "ACID", "ALCOHOL"}
    for c in out:
        c = re.sub(r"\s+", " ", c).strip(" .,;:-")
        if not c or (c != u and c in GENERIC1 and c not in ("WATER",)):
            continue
        res.append(c)
        if c in US_EU:
            res.append(US_EU[c])
        if c in _FDC:
            res.append(_FDC[c])
        m = _CI.search(c)
        if m:
            res.append("CI " + m.group(1))
        if _IRON.match(c):
            res.append("CI " + _IRON.match(c).group(1))
        # FDA filed names: ".ALPHA.-TOCOPHEROL, DL-" / "GLYCERYL MONOSTEARATE"
        f = re.sub(r"\.(ALPHA|BETA|GAMMA|DELTA)\.-?", "", c)
        f = re.sub(r",\s*(DL|D|L|\(\+/?-?\))-?$|,\s*[A-Z ]*TYPE$|,\s*UNSPECIFIED.*$|,\s*\(.*\)-?$", "", f).strip(" ,")
        if f != c:
            res.append(f)
    return list(dict.fromkeys(res))


# FDA filed (USAN / UNII preferred-term) wording -> INCI wording, applied word-wise
FDA_RX = [
    (r"^EDETATE (DISODIUM|TRISODIUM|TETRASODIUM|CALCIUM DISODIUM|SODIUM)( ANHYDROUS| DIHYDRATE)?$", lambda m: {"DISODIUM": "DISODIUM EDTA", "TRISODIUM": "TRISODIUM EDTA", "TETRASODIUM": "TETRASODIUM EDTA", "CALCIUM DISODIUM": "CALCIUM DISODIUM EDTA", "SODIUM": "DISODIUM EDTA"}[m.group(1)]),
    (r"^EDETIC ACID$", "EDTA"),
    (r"^(?:\.?ALPHA\.?-?)?TOCOPHEROL ACETATE(?:, ?DL-|, ?D-)?$|^(?:DL-|D-)?ALPHA-TOCOPHERYL ACETATE$", "TOCOPHERYL ACETATE"),
    (r"^(?:\.?ALPHA\.?-?)?TOCOPHEROL(?:, ?DL-|, ?D-)?$|^VITAMIN E$", "TOCOPHEROL"),
    (r"^FERRIC OXIDE (RED|YELLOW)$|^FERROSOFERRIC OXIDE$|^FERROUS OXIDE$|^IRON OXIDE( BLACK| RED| YELLOW)?$", None),
    (r"^SILICON DIOXIDE$|^COLLOIDAL SILICON DIOXIDE$", "SILICA"),
    (r"^CETOSTEARYL ALCOHOL$", "CETEARYL ALCOHOL"),
    (r"^MEDIUM[- ]CHAIN TRIGLYCERIDES$|^CAPRIC/CAPRYLIC TRIGLYCERIDES?$", "CAPRYLIC/CAPRIC TRIGLYCERIDE"),
    (r"^GLYCERYL MONOSTEARATE$", "GLYCERYL STEARATE"),
    (r"^SORBITAN MONO(LAURATE|OLEATE|STEARATE|PALMITATE|ISOSTEARATE)$", lambda m: "SORBITAN " + m.group(1)),
    (r"^SORBITAN SESQUIOLEATE$", "SORBITAN SESQUIOLEATE"),
    (r"^HYALURONATE SODIUM$", "SODIUM HYALURONATE"),
    (r"^BUTYLATED HYDROXYTOLUENE$", "BHT"), (r"^BUTYLATED HYDROXYANISOLE$", "BHA"),
    (r"^ALKYL \(C12-15\) BENZOATE$|^C12-15 ALKYL BENZOATES?$", "C12-15 ALKYL BENZOATE"),
    (r"^CITRIC ACID MONOHYDRATE$|^ANHYDROUS CITRIC ACID$|^CITRIC ACID ANHYDROUS$", "CITRIC ACID"),
    (r"^ANHYDROUS DEXTROSE$|^DEXTROSE MONOHYDRATE$", "GLUCOSE"),
    (r"^HYDROGREN DIMETHICONE$", "HYDROGEN DIMETHICONE"),
    (r"^CYCLOMETHICONE ?[456]$", "CYCLOMETHICONE"),
    (r"^VITAMIN A PALMITATE$", "RETINYL PALMITATE"),
    (r"^STANNIC OXIDE$", "TIN OXIDE"),
    (r"^DIHEXADECYL PHOSPHATE$", "DICETYL PHOSPHATE"),
    (r"^(?:\.ALPHA\.-)?HEXYLCINNAMALDEHYDE$", "HEXYL CINNAMAL"), (r"^(?:\.ALPHA\.-)?AMYLCINNAMALDEHYDE$", "AMYL CINNAMAL"),
    (r"^LECITHIN, SOYBEAN$|^SOYBEAN LECITHIN$", "LECITHIN"),
    (r"^EGG PHOSPHOLIPIDS$", "EGG PHOSPHOLIPIDS"),
    (r"^ZEMEA \(CORN\) PROPANEDIOL$|^ZEA MAYS \(CORN\) PROPANEDIOL$", "PROPANEDIOL"),
    (r"^OCTISALATE$", "ETHYLHEXYL SALICYLATE"), (r"^OCTINOXATE$", "ETHYLHEXYL METHOXYCINNAMATE"),
    (r"^AVOBENZONE$", "BUTYL METHOXYDIBENZOYLMETHANE"), (r"^ENSULIZOLE$", "PHENYLBENZIMIDAZOLE SULFONIC ACID"),
    (r"^OXYBENZONE$", "BENZOPHENONE-3"), (r"^BEMOTRIZINOL$", "BIS-ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE"),
    (r"^BISOCTRIZOLE$", "METHYLENE BIS-BENZOTRIAZOLYL TETRAMETHYLBUTYLPHENOL"),
    (r"^ZINC PIDOLATE$", "ZINC PCA"), (r"^SODIUM PIDOLATE$", "SODIUM PCA"),
    (r"^CARBOMER (?:HOMOPOLYMER|COPOLYMER|INTERPOLYMER)\b.*$|^CARBOMER \d+.*$", "CARBOMER"),
    (r"^POLYETHYLENE GLYCOL (\d+)$", lambda m: "PEG-" + {"200": "4", "300": "6", "400": "8", "600": "12", "1000": "20", "1500": "32", "4000": "75", "8000": "180"}.get(m.group(1), "X")),
    (r"^POLYOXYL (\d+) STEARATE$", lambda m: "PEG-" + m.group(1) + " STEARATE"),
    (r"^POLYSORBATE (\d+)$", lambda m: "POLYSORBATE " + m.group(1)),
    (r"^AMMONIUM ACRYLOY?DIMETHYLTAURATE/VP COPOLYMER$", "AMMONIUM ACRYLOYLDIMETHYLTAURATE/VP COPOLYMER"),
]
# common (non-INCI) plant names printed or filed -> INCI; only names that mean one plant part
COMMON = {"SUNFLOWER OIL": "HELIANTHUS ANNUUS SEED OIL", "SUNFLOWER SEED OIL": "HELIANTHUS ANNUUS SEED OIL",
          "HELIANTHUS ANNUUS OIL": "HELIANTHUS ANNUUS SEED OIL", "JOJOBA OIL": "SIMMONDSIA CHINENSIS SEED OIL",
          "JOJOBA SEED OIL": "SIMMONDSIA CHINENSIS SEED OIL", "ARGAN OIL": "ARGANIA SPINOSA KERNEL OIL",
          "SHEA BUTTER": "BUTYROSPERMUM PARKII BUTTER", "COCONUT OIL": "COCOS NUCIFERA OIL",
          "KUKUI NUT OIL": "ALEURITES MOLUCCANUS SEED OIL", "KARUM SEED OIL": "PONGAMIA GLABRA SEED OIL",
          "ALOE VERA LEAF": "ALOE BARBADENSIS LEAF", "ALOE VERA": "ALOE BARBADENSIS LEAF", "AVOCADO OIL": "PERSEA GRATISSIMA OIL",
          "OLIVE OIL": "OLEA EUROPAEA FRUIT OIL", "CASTOR OIL": "RICINUS COMMUNIS SEED OIL", "SWEET ALMOND OIL": "PRUNUS AMYGDALUS DULCIS OIL",
          "ALMOND OIL": "PRUNUS AMYGDALUS DULCIS OIL", "COCOA BUTTER": "THEOBROMA CACAO SEED BUTTER", "MANGO BUTTER": "MANGIFERA INDICA SEED BUTTER",
          "GRAPE SEED OIL": "VITIS VINIFERA SEED OIL", "ROSEHIP OIL": "ROSA CANINA FRUIT OIL", "SAFFLOWER OIL": "CARTHAMUS TINCTORIUS SEED OIL",
          "SESAME OIL": "SESAMUM INDICUM SEED OIL", "SOYBEAN OIL": "GLYCINE SOJA OIL", "RASPBERRY SEED OIL": "RUBUS IDAEUS SEED OIL",
          "GREEN TEA LEAF": "CAMELLIA SINENSIS LEAF", "GREEN TEA EXTRACT": "CAMELLIA SINENSIS LEAF EXTRACT", "TEA TREE OIL": "MELALEUCA ALTERNIFOLIA LEAF OIL",
          "LAVENDER OIL": "LAVANDULA ANGUSTIFOLIA OIL", "CHAMOMILE FLOWER OIL": "CHAMOMILLA RECUTITA FLOWER OIL",
          "MEADOWFOAM SEED OIL": "LIMNANTHES ALBA SEED OIL", "HEMP SEED OIL": "CANNABIS SATIVA SEED OIL", "TAMANU OIL": "CALOPHYLLUM INOPHYLLUM SEED OIL",
          "MACADAMIA OIL": "MACADAMIA INTEGRIFOLIA SEED OIL", "CARNAUBA WAX": "COPERNICIA CERIFERA CERA", "CANDELILLA WAX": "EUPHORBIA CERIFERA CERA",
          "RICE BRAN OIL": "ORYZA SATIVA BRAN OIL", "WHEAT GERM OIL": "TRITICUM VULGARE GERM OIL", "EVENING PRIMROSE OIL": "OENOTHERA BIENNIS OIL"}


def fda_inci(c):
    for rx, rep in FDA_RX:
        m = re.match(rx, c)
        if m:
            if rep is None:
                return None
            return rep(m) if callable(rep) else rep
    if c in COMMON:
        return COMMON[c]
    m = re.match(r"^(.*)\(([A-Z ]+)\) (SEED |KERNEL |FRUIT |NUT )?OIL$", c)     # "HELIANTHUS ANNUUS (SUNFLOWER) OIL"
    if m:
        return m.group(1).strip() + " SEED OIL"
    return None


IRON = {"FERRIC OXIDE RED": "CI 77491", "FERRIC OXIDE YELLOW": "CI 77492", "FERROSOFERRIC OXIDE": "CI 77499",
        "FERROUS OXIDE": "CI 77499", "IRON OXIDE BLACK": "CI 77499", "IRON OXIDE RED": "CI 77491", "IRON OXIDE YELLOW": "CI 77492"}


def lookup(name):
    """(record, how) or (None, None). how: 'name' (the INCI or US INCI name itself),
    'reading' (a bracketed or slash-separated part of the printed name),
    'fda_name' (an FDA/USAN wording mapped to INCI), 'iron_oxides' (a colour group)."""
    by = index()
    cands = candidates(name)
    for i, c in enumerate(cands):
        r = by.get(k(c))
        if r:
            return r, ("name" if i <= 1 else "reading")
    for c in cands:
        if c in IRON:
            return by.get(k(IRON[c])), "fda_name"
        if re.match(r"^IRON OXIDES?$", c):
            return {"inci": "IRON OXIDES (CI 77491, CI 77492, CI 77499)", "functions": ["COLORANT"], "status": "Active",
                    "annex": [], "ref": [], "cas": [], "restriction": [], "max": [], "perfuming": None, "id": None}, "iron_oxides"
        t = fda_inci(c)
        if t and by.get(k(t)):
            return by[k(t)], "fda_name"
    return None, None
