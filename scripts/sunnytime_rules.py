"""Ingredient flag rules for the Sunnytime / TinySafe sunscreen DB (rules v3.2).

History: rules v3.1 (2026-09-28) were applied by a build script that was not
kept in any repository. v3.2 rebuilds them so they can be rerun:

  1. Every ingredient name v3.1 saw keeps exactly the flags v3.1 gave it
     (V31_NAME_FLAGS, recovered from the published db.json evidence; on the
     v3.1 inputs this reproduces every v3.1 flag on all 6,544 products).
  2. Names v3.1 never saw (mostly INCI spellings read from the printed Drug
     Facts list, e.g. "Centella Asiatica Extract", "Cera Alba (Beeswax)") are
     flagged by the patterns below. The patterns were checked against the
     v3.1 decisions on the 4,384 names it saw (scripts/sunnytime_db.py
     --check-rules prints precision/recall per flag).
  3. V32_NOT is a short list of v3.1 decisions that are plainly wrong
     (a hair-dye intermediate counted as phenoxyethanol, a liquid PEG counted
     as a microplastic, ...). Each removal is reported by the build.
"""
import re

# ---- patterns for names v3.1 never saw -------------------------------------
# Applied to the upper-cased name. Order inside a flag does not matter.
P = {
    "hidden_uv_booster": r"METHOXYCRYLENE|SYRINGYLIDENEMALONATE|POLYESTER-8\b|\bBUT[YL]{2} ?OC?T?Y[LI] ?SA[LI]{1,2}CYLATE|BUTLOCTYL|BUTLY ?OCTYL|TRIDECYL SALICYLATE|"
                         r"BEMOTRIZINOL|BIS-?ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE|DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE|"
                         r"ETHYL FERULATE|ETHYLHEXYL TRIAZONE|METHYLENE BIS-?BENZOTRIAZOLYL|BISOCTRIZOLE|ISCOTRIZINOL|"
                         r"DIETHYLHEXYL BUTAMIDO TRIAZONE|TRIS-BIPHENYL TRIAZINE|DROMETRIZOLE TRISILOXANE|POLYSILICONE-15|"
                         r"TEREPHTHALYLIDENE DICAMPHOR",
    "chemical_filter_in_inactives": r"\bOCTISALATE\b|\bOCTOCRYLENE\b|\bOCTINOXATE\b|\bENSULIZOLE\b|\bAVOBENZONE\b|"
                                    r"ETHYLHEXYL METHOXYCINNAMATE|\bBENZOPHENONE(-3)?\b|\bHOMOSALATE\b|ETHYLHEXYL SALICYLATE|"
                                    r"\bOXYBENZONE\b|BUTYL METHOXYDIBENZOYLMETHANE|OCTYL METHOXYCINNAMATE|(?<![A-Z])(?<!BUT\w{2} )(?<!BUT\w{3} )OCTYL SALICYLATE",
    "mi_mci": r"METHYL ?ISOTHIAZOLINONE|METHYLCHLORO ?ISOTHIAZOLINONE",
    "formaldehyde_releaser": r"DMDM HYDANTOIN|DIAZOLIDINYL UREA|IMIDAZOLIDINYL UREA|QUATERNIUM-15|SODIUM HYDROXYMETHYLGLYCINATE|"
                             r"BRONOPOL|2-BROMO-2-NITROPROPANE|METHENAMINE",
    "ipbc": r"IODOPROPYNYL BUTYLCARBAMATE",
    "retinoid": r"\bRETIN(OL|YL|AL|OIC)|VITAMIN A\b",
    "adult_active": r"SALICYLIC ACID|BAKUCHIOL|GLYCOLIC ACID|TRANEXAMIC|\bARBUTIN|(?<!BUTYL)HYDROQUINONE|DIHYDROXYACETONE|\bKOJIC",
    "d4": r"CYCLOTETRASILOXANE|CYCLOMETHICONE 4\b",
    "triclosan": r"TRICLOSAN|TRICLOCARBAN",
    "formaldehyde": r"^FORMALDEHYDE$|^FORMALIN$",
    "phthalate": r"(?<!TERE)(?<!NA)(?<!PROTEIN )PHTHALATE\b(?!.*POLY)",
    "fragrance": r"(?:FRAGRANCE|FRAGANCE|TRAGRANCE|FRAGRENCE)(?![- ]?FREE)|\bPARFUM|\bPERFUME",
    "eu_fragrance_allergen": r"BENZYL ALCOHOL|FARNESOL|HYDROXYCITRONELLAL|BENZYL SALICYLATE|BENZYL BENZOATE|BENZYL CINNAMATE|"
                             r"\bLIMONENE|\bLINALOOL|\bLINALYL ACETATE|GERANIOL|CITRONELLOL|\bCITRAL\b|\bEUGENOL|ISOEUGENOL|COUMARIN|"
                             r"CINNAMAL|CINNAMYL ALCOHOL|AMYLCINNAM|HEXYL ?CINNAMAL|ANISE ALCOHOL|ANISYL ALCOHOL|"
                             r"BUTYLPHENYL METHYLPROPIONAL|ALPHA-ISOMETHYL IONONE|ISOMETHYL IONONE|HYDROXYISOHEXYL 3-CYCLOHEXENE|"
                             r"OAKMOSS|EVERNIA|TREEMOSS|METHYL 2-OCTYNOATE|ROSA .*FLOWER OIL|(?<!PRIM)\bROSE (FLOWER )?OIL|"
                             r"PELARGONIUM GRAVEOLENS|LAVANDULA ANGUSTIFOLIA",
    "essential_oil": None,  # see is_essential_oil()
    "asteraceae": r"CALENDULA|CHAMOMIL|MATRICARIA|ANTHEMIS|ECHINACEA|ARNICA|FEVERFEW|TANACETUM|TARAXACUM|DANDELION|"
                  r"ACHILLEA|YARROW|ARCTIUM|BURDOCK|HELICHRYSUM|IMMORTELLE|CENTAUREA|CORNFLOWER|SILYBUM|MILK THISTLE|"
                  r"ARTEMISIA|MUGWORT|WORMWOOD|BIDENS|SPILANTHES|ACMELLA|STEVIA|CYNARA|ARTICHOKE|CHICORY|CICHORIUM|"
                  r"BELLIS|DAISY|SANTOLINA|TAGETES|MARIGOLD|INULA|SAUSSUREA|ATRACTYLODES|SIEGESBECKIA|ECLIPTA|"
                  r"LACTUCA|CHRYSANTHEMUM|DENDRANTHEMA|SOLIDAGO|EUPATORIUM|"
                  r"GRINDELIA|CARDUUS|ASTER\b",
    "oat": r"\bAVENA|\bOAT\b|OATMEAL|\bOATS\b",
    "peanut": r"PEANUT|ARACHIS",
    "tree_nut": r"ARGAN|MACADAMIA|ALMOND|AMYGDALUS|HAZELNUT|CORYLUS|WALNUT|JUGLANS|CASHEW|ANACARDIUM|PECAN|CARYA|"
                r"PISTACH|BRAZIL NUT|BERTHOLLETIA|PINE NUT",
    "soy": r"\bSOY|SOYBEAN|GLYCINE SOJA|GLYCINE MAX",
    "wheat": r"WHEAT|TRITICUM|HORDEUM|BARLEY|\bRYE\b|SECALE|GLUTEN",
    "milk": r"\bMILK\b(?! THISTLE)|\bLAC\b|WHEY|CASEIN|COLOSTRUM|LACTOSE|YOGURT|BUTTERMILK",
    "egg": r"\bEGG\b|\bOVUM\b|OVALBUMIN|EGG YOLK",
    "sesame": r"SESAM",
    "fish_shellfish": r"FISH|CHITOSAN|SHELLFISH|OYSTER|SHRIMP|CRAB|LOBSTER|SQUALENE \(SHARK|SHARK",
    "lanolin": r"LANOLIN|ADEPS LANAE|WOOL WAX|WOOL FAT",
    "propolis_beeswax": r"\bHONEY\b|\bMEL\b|BEESWAX|CERA ALBA|CERA FLAVA|PROPOLIS|ROYAL JELLY|BEE VENOM|APIS MELLIFERA",
    "capb": r"COCAMIDOPROPYL BETAINE",
    "propylene_glycol": r"(?<![A-Z])PROPYLENE GLYCOL",
    "drying_alcohol": r"^ALCOHOL$|^ALCOHOL DENAT|^SD ALCOHOL|\bALCOHOL DENAT|\bSD ALCOHOL|^ETHANOL$|^ETHYL ALCOHOL$|"
                      r"^DENATURED ALCOHOL|^ISOPROPYL ALCOHOL$|^ALCOHOL \(",
    "propyl_butyl_paraben": r"PROPYL ?PARABEN|BUTYL ?PARABEN|ISOBUTYL ?PARABEN|ISOPROPYL ?PARABEN",
    "latex": r"LATEX|HEVEA BRASILIENSIS",
    "citrus_photosensitizer": r"BERGAMOT|BERGAMIA.*OIL",
    "phenoxyethanol": r"(?<!DIAMINO)PHENOXYETHANOL",
    "methyl_ethyl_paraben": r"(?<![A-Z])METHYL ?PARABEN|(?<![A-Z])ETHYL ?PARABEN",
    "ethoxylated": r"\bPEG[- ]|\bPEG\d|POLYSORBATE|-ETH-|ETH-\d|\bPPG[- ]|\bPOLYETHYLENE GLYCOL|POLYOXYL|LAURETH|STEARETH|"
                   r"CETEARETH|CETETH|OLETH|CETEARETH|TRIDECETH|PARETH|BEHENETH|CEteth|SORBETH|ISOSTEARETH|STEARETH|"
                   r"OCTOXYNOL|NONOXYNOL|POLOXAMER|LAURETH SULFATE|\bETHOXYLATED|GLYCERETH|CETETH|POLYGLYCERYL-\d+ ?PEG",
    "ethanolamines": r"TRIETHANOLAMINE|DIETHANOLAMINE|MONOETHANOLAMINE|\b(TEA|DEA|MEA)-|\b(DEA|MEA)$|\bTROLAMINE",
    "bht_bha": r"BUTYLATED HYDROXY|(?<!TRIS-)\bBHT\b|\bBHA\b",
    "petrolatum_mineral_oil": r"PETROLATUM|MINERAL OIL|PARAFFINUM LIQUIDUM|PARAFFIN OIL|LIQUID PARAFFIN|PETROLEUM JELLY",
    "silicone": r"(?<!CYCLO)METHICONE|DIMETHICON|SILOXANE(?!.*CYCLO)|SILSESQUIOXANE|SILICONE|TRIMETHYLSILOXYSILICATE|"
                r"\bMETHICONE|TRISILOXANE|POLYSILICONE",
    "iron_oxide_tint": r"IRON OXIDE|FERRIC OXIDE|FERROSOFERRIC|CI 7749\d|CI 77499|CI 77491|CI 77492|CI 77400|FERRIC IRON",
    "synthetic_dye": r"\bCI (?!77)\d{5}\b|\b(RED|BLUE|YELLOW|GREEN|ORANGE|VIOLET) (NO\. )?\d+\b|FD&C|D&C|PIGMENT (RED|BLUE|YELLOW|GREEN)",
    "sls_sles": r"SODIUM LAURYL SULFATE|SODIUM LAURETH SULFATE",
    "sodium_benzoate": r"SODIUM BENZOATE|^BENZOIC ACID$|POTASSIUM BENZOATE",
    "microplastic_polymer": r"POLYMETHYLSILSESQUIOXANE|POLYETHYLENE(?! GLYCOL)(?! TEREPHTHALATE)|NYLON|POLYURETHANE|STYRENE/? ?ACRYLATES|"
                            r"POLYMETHYL METHACRYLATE|METHYL METHACRYLATE CROSSPOLYMER|POLYPROPYLENE(?! GLYCOL)|"
                            r"POLYSTYRENE(?! SULFONATE)|POLYBUTYLENE TEREPHTHALATE",
    "animal_derived": r"COLLAGEN|ELASTIN|TALLOW|\bSILK\b|SERICIN|BOVINE|\bBOS TAURUS|SNAIL|MUCIN|KERATIN|PLACENTA|"
                      r"CARMINE|SQUALENE \(SHARK|SHARK|CHOLESTEROL \(ANIMAL|LARD|EMU OIL|MINK OIL",
    "shea": r"\bSHEA|BUTYROSPERMUM|VITELLARIA",
    "coconut": r"\bCOCO(?!A)|COCONUT|COCOS NUCIFERA|COCAMIDE|COCOATE|COCOYL|COCAMIDOPROPYL",
    "d5_d6": r"CYCLOPENTASILOXANE|CYCLOHEXASILOXANE|CYCLOMETHICONE",
    "talc": r"^TALC\b|\bTALC$|\bTALC\b",
    "botanical_count": None,  # see is_botanical()
}
RX = {k: re.compile(v) for k, v in P.items() if v}

# Plants whose non-fixed oils are essential oils (genus, or common name).
EO_GENERA = {"LAVANDULA", "ROSMARINUS", "SALVIA", "MENTHA", "EUCALYPTUS", "MELALEUCA", "LEPTOSPERMUM", "CYMBOPOGON",
             "PELARGONIUM", "SANTALUM", "CEDRUS", "JUNIPERUS", "CUPRESSUS", "ABIES", "PICEA", "PINUS", "BOSWELLIA",
             "COMMIPHORA", "POGOSTEMON", "VETIVERIA", "CHRYSOPOGON", "THYMUS", "ORIGANUM", "OCIMUM", "ANTHEMIS",
             "CHAMAEMELUM", "MATRICARIA", "CHAMOMILLA", "JASMINUM", "ROSA", "CANANGA", "CINNAMOMUM", "EUGENIA",
             "SYZYGIUM", "ZINGIBER", "ELETTARIA", "FOENICULUM", "PIMPINELLA", "LITSEA", "MYRTUS", "HELICHRYSUM",
             "CORIANDRUM", "DAUCUS", "CITRUS", "ANIBA", "AQUILARIA", "DRYOBALANOPS", "CISTUS", "TANACETUM",
             "ARTEMISIA", "LAURUS", "AMYRIS", "MICHELIA", "POLIANTHES", "IRIS", "VALERIANA", "NARDOSTACHYS"}
EO_COMMON = re.compile(r"\b(LAVENDER|LAVANDIN|ROSEMARY|PEPPERMINT|SPEARMINT|MINT|EUCALYPTUS|TEA TREE|LEMONGRASS|CITRONELLA|"
                       r"ORANGE|LEMON|LIME|GRAPEFRUIT|MANDARIN|TANGERINE|BERGAMOT|NEROLI|PETITGRAIN|YLANG(-YLANG)?|"
                       r"GERANIUM|SANDALWOOD|CEDARWOOD|CEDAR LEAF|FRANKINCENSE|PATCHOULI|VETIVER|CLARY SAGE|SAGE|THYME|"
                       r"CHAMOMILE|JASMINE|ROSE|PALMAROSA|CAJEPUT|NIAOULI|CYPRESS|JUNIPER|JUNIPERBERRY|FIR|SPRUCE|PINE|"
                       r"BASIL|MYRRH|CINNAMON|CLOVE|GINGER|CARDAMOM|FENNEL|ANISE|OREGANO|MARJORAM|LITSEA|MAY CHANG|"
                       r"HELICHRYSUM|IMMORTELLE|CORIANDER|CARROT SEED|ROSEWOOD|BAY|TUBEROSE|MANUKA|KANUKA)\b")


def is_essential_oil(name):
    """A volatile plant oil: a non-fixed oil of a plant that yields essential oils.
    Seed/kernel/nut/fruit 'oils' are fixed oils (sunflower, jojoba, olive) and do not count,
    except carrot seed and coriander, whose seed oils are essential oils."""
    u = re.sub(r"\(.*?\)", " ", (name or "").upper())
    if not re.search(r"\bOIL\b", u) or re.search(r"HYDROGENATED|UNSAPONIFIABLE|\bPEG\b|GLYCERIDE|ESTER", u):
        return False
    w = re.findall(r"[A-Z]+", u)
    fixed = re.search(r"\b(SEED|KERNEL|NUT|BRAN|GERM)\b.*\bOIL\b", u) and not re.search(r"CARROT|DAUCUS|CORIAND", u)
    if fixed or re.search(r"\bFRUIT OIL\b", u) and not (w and w[0] == "CITRUS"):
        return False
    return bool((w and w[0] in EO_GENERA) or EO_COMMON.search(re.sub(r"\(.*?\)", " ", (name or "").upper()))
                or EO_COMMON.search((name or "").upper()))

# Plant parts and plant-derived product words; a name with one of these and a
# Latin binomial or a known plant word counts as a plant extract.
_PART = re.compile(r"\b(EXTRACT|LEAF|LEAVES|ROOT|FLOWER|FLOWERS|SEED|SEEDS|FRUIT|BARK|STEM|STALK|PEEL|RIND|KERNEL|"
                   r"SPROUT|SHOOT|BUD|BULB|RHIZOME|TUBER|NEEDLE|TWIG|WOOD|RESIN|GUM|SAP|JUICE|HERB|WHOLE|THALLUS|"
                   r"CALLUS|MERISTEM|CELL CULTURE|CELL EXTRACT|FLOWERING TOP|BERRY|FRUITING BODY|POD|HULL|HUSK|BRAN|"
                   r"GERM|NUT|TOP|AERIAL PARTS|LEAF/STEM|WATER)\b")
_NOT_BOTANICAL = re.compile(r"\b(GLYCERYL|PEG|PPG|POLYGLYCERYL|HYDROGENATED|SODIUM|POTASSIUM|ETHYL|METHYL|CETYL|"
                            r"STEARYL|ISOPROPYL|SORBITAN|DIMETHICONE|ACID|ATE|YL)\b")


def is_botanical(name, botanical_genera):
    """A plant extract or plant oil: the name's first word is a plant genus v3.1
    counted (botanical_genera), or a common plant name followed by a plant part
    (e.g. 'GREEN TEA LEAF EXTRACT')."""
    u = name.upper()
    u = re.sub(r"\(.*?\)", " ", u)
    words = re.findall(r"[A-Z]+", u)
    if not words:
        return False
    if words[0] in botanical_genera and _PART.search(u):
        return True
    if words[0] in botanical_genera and len(words) >= 2 and re.search(r"\bOIL\b|BUTTER|EXTRACT|WATER", u):
        return True
    return False


# v3.1 decisions that are plainly wrong; removed in v3.2 and reported.
# Source flags (bee, animal, wool) never apply to a synthetic version of the substance
SYNTHETIC = re.compile(r"\bSYNTHETIC\b")
SOURCE_FLAGS = {"propolis_beeswax", "animal_derived", "lanolin"}

V32_NOT = {
    ("2,4-DIAMINOPHENOXYETHANOL HCL", "phenoxyethanol"): "a hair-dye intermediate, not the preservative phenoxyethanol",
    ("N-LACTOYL ETHANOLAMINE", "drying_alcohol"): "an amide humectant, not a drying alcohol",
    ("PHENYLETHYL ALCOHOL", "drying_alcohol"): "an aromatic alcohol used as a fragrance/preservative, not an evaporating alcohol",
    ("HYDROXYPHENYL PROPAMIDOBENZOIC ACID", "sodium_benzoate"): "an anti-itch active, not a benzoate preservative",
    ("4-(AMINOMETHYL)BENZOIC ACID HYDROCHLORIDE", "sodium_benzoate"): "not a benzoate preservative",
    ("2-(4-(DIETHYLAMINO)-2-HYDROXYBENZOYL)BENZOIC ACID", "sodium_benzoate"): "a UV-filter intermediate, not a benzoate preservative",
    ("4-HYDROXYBENZOIC ACID", "sodium_benzoate"): "not sodium benzoate or benzoic acid",
    ("AMINO ACIDS, CORN GLUTEN", "wheat"): "corn gluten is not wheat gluten",
    ("4-METHYLBENZYLIDENE CAMPHOR", "eu_fragrance_allergen"): "a UV filter, not a listed fragrance allergen",
}
for _n in ("POLYETHYLENE GLYCOL 200", "POLYETHYLENE GLYCOL 300", "POLYETHYLENE GLYCOL 400", "POLYETHYLENE GLYCOL 500",
           "POLYETHYLENE GLYCOL 1000", "POLYETHYLENE GLYCOL 1600"):
    V32_NOT[(_n, "microplastic_polymer")] = "polyethylene glycol is a water-soluble liquid/wax, not a polymer microparticle"

# Preservatives for no_preservative_water_base (a product with water and none
# of these). Recovered from the 315 v3.1 decisions; see sunnytime_db.py --check-rules.
PRESERVATIVE = re.compile(
    r"PHENOXYETHANOL|PARABEN|HYDROXYBENZOATE|SODIUM BENZOATE|BENZOIC ACID|POTASSIUM SORBATE|SORBIC ACID|"
    r"BENZYL ALCOHOL|DEHYDROACETIC|CHLORPHENESIN|ETHYLHEXYLGLYCERIN|CAPRYLYL GLYCOL|1,2-HEXANEDIOL|HEXANEDIOL|"
    r"PENTYLENE GLYCOL|CAPRYLHYDROXAMIC|GLYCERYL CAPRYLATE|HYDROXYACETOPHENONE|METHYLISOTHIAZOLINONE|"
    r"ISOTHIAZOLINONE|DMDM HYDANTOIN|DIAZOLIDINYL|IMIDAZOLIDINYL|QUATERNIUM-15|IODOPROPYNYL|"
    r"SODIUM HYDROXYMETHYLGLYCINATE|CHLOROXYLENOL|TRICLOSAN|BENZETHONIUM|BENZALKONIUM|LEVULINIC|ANISIC ACID|"
    r"GLUCONOLACTONE|SODIUM ANISATE|SODIUM LEVULINATE|PHENETHYL ALCOHOL|PHENYLETHYL ALCOHOL|PHENYLPROPANOL|"
    r"POLYAMINOPROPYL BIGUANIDE|CHLORHEXIDINE|BRONOPOL|METHYLPROPANEDIOL|ETHYL LAUROYL ARGINATE|"
    r"LEUCONOSTOC/RADISH|LACTOBACILLUS FERMENT|HINOKITIOL|ALCOHOL DENAT|SD ALCOHOL|^ALCOHOL$")
WATER = re.compile(r"^(PURIFIED |DEIONIZED |DISTILLED )?WATER\b|^AQUA\b|^EAU\b|WATER/AQUA|AQUA/WATER|^WATER/EAU")


def pattern_flags(name, botanical_genera):
    """Flags for a name v3.1 never saw."""
    u = (name or "").upper().replace("&AMP;", "&")
    out = {f for f, rx in RX.items() if rx.search(u)}
    if "silicone" in out and "CYCLO" in u and not re.search(r"DIMETHICON|METHICONE|SILSESQUIOXANE", u):
        out.discard("silicone")     # cyclic only: D4/D5/D6 have their own flags
    if is_botanical(name, botanical_genera):
        out.add("botanical_count")
    if is_essential_oil(name):
        out.add("essential_oil")
    return out


# ---- plant identity: inherit from names v3.1 saw ---------------------------
# A plant name v3.1 never saw ("Calendula Officinalis Flower Extract") takes the
# plant flags v3.1 gave the same plant ("CALENDULA OFFICINALIS FLOWER"):
#   - family/botanical flags by genus (first Latin word),
#   - oil-type flags (essential oil, plant fragrance allergen) only between two
#     oils of the same binomial, so a seed extract never inherits "essential oil".
GENUS_FLAGS = {"botanical_count", "asteraceae"}
BINOMIAL_FLAGS = {"tree_nut", "oat", "soy", "wheat", "sesame", "shea", "coconut", "peanut"}
OIL_FLAGS = {"eu_fragrance_allergen"}
_FIXED_OIL = re.compile(r"\b(SEED|KERNEL|NUT|FRUIT|BRAN|GERM)\b.*\bOIL\b|\bBUTTER\b|HYDROGENATED|UNSAPONIFIABLE")


def _words(name):
    return re.findall(r"[A-Z]+", re.sub(r"\(.*?\)", " ", (name or "").upper()))


def _is_oil(name):
    u = (name or "").upper()
    return bool(re.search(r"\bOIL\b", u)) and not _FIXED_OIL.search(u)


class PlantIndex:
    def __init__(self, name_flags):
        self.genus, self.binom, self.oil = {}, {}, {}
        for n, fs in name_flags.items():
            if " OR " in n.upper() or "/" in n:      # "SUNFLOWER OIL OR SOYBEAN OIL": two plants
                continue
            w = _words(n)
            if not w:
                continue
            g = w[0]
            b = " ".join(w[:2]) if len(w) > 1 else None
            for f in fs & GENUS_FLAGS:
                self.genus.setdefault(g, set()).add(f)
            if b:
                for f in fs & BINOMIAL_FLAGS:
                    self.binom.setdefault(b, set()).add(f)
                if _is_oil(n):
                    for f in fs & OIL_FLAGS:
                        self.oil.setdefault(b, set()).add(f)

    def flags(self, name):
        w = _words(name)
        if len(w) < 2:
            return set()
        g, b = w[0], " ".join(w[:2])
        out = set(self.genus.get(g, set()))
        if "botanical_count" in out and not (_PART.search(" ".join(w)) or re.search(r"\bOIL\b|BUTTER|WATER", " ".join(w))):
            out.discard("botanical_count")
        out |= self.binom.get(b, set())
        if _is_oil(name):
            out |= self.oil.get(b, set())
        return out


# Flags where v3.1's name decisions are incomplete (evidence was capped at 4 names
# per flag, so an unflagged name is not a decision): the patterns add to v3.1.
ADDITIVE = {"essential_oil", "ethoxylated", "hidden_uv_booster", "microplastic_polymer", "fragrance"}
