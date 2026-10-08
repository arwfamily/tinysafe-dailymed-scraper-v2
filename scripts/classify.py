"""
classify.py — product classification for the US DailyMed sunscreen corpus.

Classifier version 2 (2026-10-08). Replaces the title-substring rules that
lived in dailymed_scraper.enrich()/categorize().

WHY THIS EXISTS
  The v1 rules decided "is this a sunscreen / a baby product / 100% mineral"
  from substrings of the title. An audit on 2026-10-08 measured the damage:
    - 842 sunscreens filed as makeup because the title says TINTED
    - "SETTING" matched SUNSETTER, "RASH" matched HYDRASHEER, "KID" matched KIDNEY
    - baby flag fired on labeler names (BABYFACE LLC) and missed SPF-30 style titles
    - the hidden-UV-absorber list had 3 entries; the corpus contains 20+
  Every rule below was checked against the 13,326-row corpus before shipping.

DESIGN
  1. Identity comes from the ACTIVE ingredients (UNII first, name second).
     A product is a sunscreen if an active is a UV filter AND the label
     presents it as sun protection (SPF / sunscreen wording / an organic
     filter, which has no other OTC use).
  2. Title words only decide the PRODUCT TYPE among sunscreens
     (tinted, colour cosmetic, lip, skin protectant), always with word
     boundaries, never the labeler bracket.
  3. "Mineral" is decided by the full ingredient list: actives must be only
     ZnO/TiO2, and no inactive may be a UV filter or a UV-absorbing booster.
  4. Pure functions, no network. Same input -> same output.
"""
import re

CLASSIFIER_VERSION = "2.0.1"

# ---------------------------------------------------------------------------
# UV filters as ACTIVE ingredients. Keyed by UNII (from the corpus itself,
# 2026-10-08); names are the fallback for rows whose UNII is missing.
# us_status: "M020" = in the FDA OTC sunscreen monograph (bemotrizinol added
# by final order OTC000039, effective 2026-08-09); "not_us" = permitted
# elsewhere (EU/AU/KR/JP) but not in M020.
# ---------------------------------------------------------------------------
MINERAL_UNII = {"SOI2LOH54Z": "zinc oxide", "15FIX9V2JP": "titanium dioxide"}

ORGANIC_FILTER_UNII = {
    "4X49Y0596W": ("octisalate", "M020"),
    "G63QQF2NOX": ("avobenzone", "M020"),
    "5A68WGF6WM": ("octocrylene", "M020"),
    "4Y5P7MUD51": ("octinoxate", "M020"),
    "V06SV4M95S": ("homosalate", "M020"),
    "95OOS7VE0Y": ("oxybenzone", "M020"),
    "9YQ9DI1W42": ("ensulizole", "M020"),
    "Z11006CMUZ": ("padimate O", "M020"),
    "J9QGD60OUZ": ("meradimate", "M020"),
    "1W6L629B4K": ("sulisobenzone", "M020"),
    "TL2TJE8QTX": ("aminobenzoic acid", "M020"),
    "PWZ1720CBH": ("bemotrizinol", "M020"),
    "M94R1PM439": ("ecamsule", "NDA"),
    "HC22845I1X": ("drometrizole trisiloxane", "not_us"),
    "ANQ870JD20": ("diethylamino hydroxybenzoyl hexyl benzoate", "not_us"),
    "XQN8R9SAK4": ("ethylhexyl triazone", "not_us"),
    "8I3XWY40L9": ("enzacamene", "not_us"),
    "376KTP06K8": ("amiloxate", "not_us"),
    "8NT850T0YS": ("bisoctrizole", "not_us"),
    "2UTZ0QC864": ("iscotrizinol", "not_us"),
    "SD418S06XD": ("ethyl methoxycinnamate", "not_us"),
    "77FU10423X": ("padimate A", "not_us"),
}

ORGANIC_FILTER_NAME = [
    (r"\bOCTISALATE\b|\bETHYLHEXYL SALICYLATE\b|\bOCTYL SALICYLATE\b", "octisalate"),
    (r"\bAVOBENZONE\b|BUTYL METHOXYDIBENZOYLMETHANE", "avobenzone"),
    (r"\bOCTOCRYLENE\b", "octocrylene"),
    (r"\bOCTINOXATE\b|ETHYLHEXYL METHOXYCINNAMATE|OCTYL METHOXYCINNAMATE", "octinoxate"),
    (r"\bHOMOSALATE\b", "homosalate"),
    (r"\bOXYBENZONE\b|\bBENZOPHENONE-3\b", "oxybenzone"),
    (r"\bENSULIZOLE\b|PHENYLBENZIMIDAZOLE SULFONIC ACID", "ensulizole"),
    (r"\bPADIMATE O\b|ETHYLHEXYL DIMETHYL PABA", "padimate O"),
    (r"\bMERADIMATE\b", "meradimate"),
    (r"\bSULISOBENZONE\b|\bBENZOPHENONE-4\b", "sulisobenzone"),
    (r"\bDIOXYBENZONE\b|\bBENZOPHENONE-8\b", "dioxybenzone"),
    (r"\bCINOXATE\b", "cinoxate"),
    (r"\bTROLAMINE SALICYLATE\b", "trolamine salicylate"),
    (r"\bAMINOBENZOIC ACID\b|^PABA$", "aminobenzoic acid"),
    (r"\bBEMOTRIZINOL\b|BIS-ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE", "bemotrizinol"),
    (r"\bECAMSULE\b|TEREPHTHALYLIDENE DICAMPHOR", "ecamsule"),
    (r"DROMETRIZOLE TRISILOXANE", "drometrizole trisiloxane"),
    (r"DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE", "diethylamino hydroxybenzoyl hexyl benzoate"),
    (r"ETHYLHEXYL TRIAZONE|OCTYL TRIAZONE", "ethylhexyl triazone"),
    (r"\bENZACAMENE\b|4-METHYLBENZYLIDENE CAMPHOR", "enzacamene"),
    (r"\bAMILOXATE\b|ISOAMYL P-METHOXYCINNAMATE", "amiloxate"),
    (r"\bBISOCTRIZOLE\b|METHYLENE BIS-BENZOTRIAZOLYL", "bisoctrizole"),
    (r"\bISCOTRIZINOL\b|DIETHYLHEXYL BUTAMIDO TRIAZONE", "iscotrizinol"),
    (r"TRIS-BIPHENYL TRIAZINE", "tris-biphenyl triazine"),
    (r"BISDISULIZOLE|DISODIUM PHENYL DIBENZIMIDAZOLE TETRASULFONATE", "bisdisulizole disodium"),
    (r"\bPOLYSILICONE-15\b", "polysilicone-15"),
]
MINERAL_NAME = [(r"\bZINC OXIDE\b", "zinc oxide"), (r"\bTITANIUM DIOXIDE\b", "titanium dioxide")]

# ---------------------------------------------------------------------------
# UV absorbers appearing among INACTIVE ingredients.
# tier 1: a substance registered as a UV filter by at least one major
#         regulator (FDA M020, EU Annex VI, TGA, MFDS, MHLW).
# tier 2: SPF boosters / photostabilisers that are not registered filters
#         anywhere. NOT all of them absorb UV (e.g. ethylhexyl methoxycrylene
#         works without absorbing sunlight, per DrugBank DB11226), so the field
#         name is historical: never publish "absorbs UV" from this list.
#         Public wording needs a per-ingredient source (SITE_DATA_CONTRACT.md).
# Deliberately NOT included (verified in corpus, they are fragrance or
# antioxidant ingredients, not UV absorbers in practice): benzyl / methyl /
# hexyl / amyl salicylate, camphor (natural/synthetic), pentaerythrityl
# tetra-di-t-butyl hydroxyhydrocinnamate.
# ---------------------------------------------------------------------------
INACTIVE_TIER1 = ORGANIC_FILTER_NAME  # same names; any registered filter listed as inactive

INACTIVE_TIER2 = [
    (r"\bBUTYLOCTYL SALICYLATE\b", "butyloctyl salicylate"),
    (r"\bTRIDECYL SALICYLATE\b", "tridecyl salicylate"),
    (r"\bETHYLHEXYL METHOXYCRYLENE\b", "ethylhexyl methoxycrylene"),
    (r"\bPOLYESTER-8\b", "polyester-8"),
    (r"DIETHYLHEXYL SYRINGYLIDENE ?MALONATE", "diethylhexyl syringylidenemalonate"),
    (r"BENZOTRIAZOLYL DODECYL P-CRESOL", "benzotriazolyl dodecyl p-cresol"),
    (r"BENZYLIDENE DIMETHOXYDIMETHYLINDANONE", "benzylidene dimethoxydimethylindanone"),
    (r"TRIMETHOXYBENZYLIDENE PENTANEDIONE", "trimethoxybenzylidene pentanedione"),
    (r"UNDECYLCRYLENE DIMETHICONE", "undecylcrylene dimethicone"),
    (r"\bETHYL FERULATE\b", "ethyl ferulate"),
    (r"\bBENZOPHENONE-2\b", "benzophenone-2"),
    (r"SODIUM BENZOTRIAZOLYL BUTYLPHENOL SULFONATE", "sodium benzotriazolyl butylphenol sulfonate"),
]

# ---------------------------------------------------------------------------
# Title rules. Always applied to the PRODUCT part of the title (labeler
# bracket removed) and always with word boundaries.
# ---------------------------------------------------------------------------
SPF_RE = re.compile(r"\b(?:SPF|FPS)\s*[-#:]?\s*(\d{1,3})\b", re.I)
SUN_WORDS = re.compile(r"\bSUN\b|\bSUN\s?C?REAMS?\b|\bSUN\s?(?:MILK|SERUM|GEL|ESSENCE|FLUID|LOTION|STICK|SPRAY|BALM|CUSHION|BLOCK)\b|\bSUNCREEN\b|\bSUN\s?SCREENS?\b|\bSUN\s?BLOCKS?\b|\bSUNCARE\b|\bSUNSTICK\b|\bBROAD[- ]SPECTRUM\b|\bUV[AB]?\b|\bUVA/UVB\b|\bSPF\b|\bPHYSICAL DEFEN[CS]E\b|\bSUN PROTECT|\w*SCREEN\b|\bSOLAR\b|\bSHADE\b|\bTINT(?:ED)?\b|\bUV PROTECTION\b", re.I)
COLOR_COSMETIC = re.compile(r"\b(?:FOUNDATIONS?|CONCEALERS?|BB\s?CREAM|CC\s?CREAM|CUSHION COMPACT|BLUSH(?:ER)?|BRONZER|HIGHLIGHTER|EYESHADOW|EYE SHADOW|MASCARA|LIPSTICK|LIP\s?COLOU?R|LIP\s?TINT|LIP\s?PEN|LIP\s?GLOSS|LIP\s?STYLO|\bPACT|CONCEAL\w*|MAKE[- ]?UP|SETTING POWDER|SETTING SPRAY|CUSHION COMPACT)\b", re.I)
TINTED = re.compile(r"\bTINT(?:ED)?\b|\bSHEER TINT\b|\bCOLOU?R CORRECT", re.I)
LIP = re.compile(r"\bLIPS?\b|\bLIP\s?BALM\b|\bCHAPSTICK\b", re.I)
FACE_BODY = re.compile(r"\bFACE\b|\bBODY\b|\bSKIN\b", re.I)
SKIN_PROTECTANT = re.compile(r"\bDIAPER\b|\bRASH\b|\bBUTTS?\b|\bBOTTOMS?\b|\bBUMS?\b|\bWOUND\b|\bOINTMENT\b|\bPASTE\b|\bCALAMINE\b|\bHEALING\b|\bPROTECTANT\b|\bCHAF\w*|\bANTI-?ITCH\b|\bPERI\b|\bPERINEAL\b|\bINCONTINENCE\b|\bBARRIER CREAM\b|\bMOISTURE BARRIER\b|\bBEDSORE|\bPRESSURE\b", re.I)
# Actives that only appear alongside ZnO in skin-protectant (M016) products.
SKIN_PROTECTANT_COACTIVE = re.compile(r"PETROLATUM|DIMETHICONE|LANOLIN|ALLANTOIN|COD LIVER OIL|COCOA BUTTER|MINERAL OIL|KAOLIN|ZINC ACETATE|CALAMINE|GLYCERIN|MENTHOL|PRAMOXINE|HYDROCORTISONE|STARCH|SHARK LIVER OIL", re.I)
# Non-sunscreen products that list ZnO/TiO2 as an active: oral vitamins
# (zinc source), homeopathic pellets, sanitizers, suppositories.
ORAL = re.compile(r"\bTABLETS?\b|\bCAPSULES?\b|\bSOFTGELS?\b|\bCAPLETS?\b|\bCHEWABLE\b|\bGUMMIES\b|\bPRENATAL\b|\bPRENATOL\b|\bMULTIVITAMIN\b|\bVITAFOL\b|\bORAL\b|\bPELLETS?\b|\bGRANULES?\b|\bSUPPOSITOR\w*|\bSANITI[SZ]ER\b|\bDEODORANT\b|\bCOMBO PACK\b|\bDHA\b|\bCITRANATAL\b|\bZINCUM\b|\bHEMORRHOID\w*", re.I)
# Leave-on cosmetic formats. ZnO as a skin-protectant active is for diaper
# rash / minor irritation; a ZnO-only face cream, serum or foundation is in
# practice a sunscreen. Recorded with its own basis so it can be audited.
COSMETIC_FORMAT = re.compile(r"\bFACE\b|\bFACIAL\b|\bMOISTURI[SZ]\w*|\bSERUM\b|\bFOUNDATION\b|\bPRIMER\b|\bDAILY\b|\bLIPS?\b|\bANTI-?AGING\b|\bBEAUTY\b|\bGLOW\b|\bCOMPLEXION\b|\bPROTECTION\b", re.I)
# An explicit sunscreen word outranks weak protectant cues (2026-10-08: "BUM"
# in the brands Sun Bum / Baby Bum made 47 zinc sunscreens "skin protectant").
STRONG_SUN = re.compile(r"\bSUN\s?SCREENS?\b|\bSUN\s?BLOCKS?\b|\bSUNCREEN\b", re.I)
STRONG_PROTECTANT = re.compile(r"\bDIAPER\b|\bRASH\b|\bWOUND\b|\bCALAMINE\b|\bINCONTINENCE\b|\bPERINEAL\b|\bBEDSORE|\bANTI-?ITCH\b|\bBARRIER CREAM\b", re.I)
MONOGRAPH_SUNSCREEN = "M020"
MONOGRAPH_SKIN_PROTECTANT = "M016"
CALAMINE = re.compile(r"\bCALAMINE\b", re.I)

# Baby/kids words. Compound brand words are real on-pack text (THINKBABY,
# WATERBABIES, KIDSTICK, BABYGANICS), so these match inside words; known
# false positives are removed by BABY_FALSE_POSITIVE before matching.
BABY_RE = re.compile(r"BAB(?:Y|IES|YS)|KID(?:S|Z|DO|DOS)?|INFANTS?|NEWBORNS?|TODDLERS?|PEDIATRIC|PAEDIATRIC|CHILDREN|\bCHILD\b|\bJUNIOR\b|LITTLE ONES?|\bLIL ONES?\b|\bTOTS?\b|\bBEBE\b|\bBÉBÉ\b", re.I)
# Phrases containing a baby word that do not mean "for babies" (verified in corpus).
BABY_FALSE_POSITIVE = re.compile(r"KIDNEY|NOT YOUR BABY'?S?|BACK TO BABY|NEW KID ON THE BLOCK|BABY ?LIPS|BABY ?SKIN PRIMER|BABY ?DOLL|BABY ?BLUE|BABY ?PINK|BABY ?OIL(?! FREE)|BABYLON|SKIDS?\b", re.I)
# Labelers whose NAME contains a baby word but who sell adult products.
BABY_LABELER_BLOCK = re.compile(r"BABYFACE LLC|BABYLIST|WILD CHILD", re.I)
# Baby/kids brands whose labeler name has no baby word. REVIEW signal only.
BABY_BRAND_LABELERS = re.compile(r"MUSTELA|LABORATOIRES EXPANSCIENCE|PIPETTE|EVEREDEN|CALIFORNIA BABY|BABY BUM|HELLO BELLO|COTZ|BEBE BOTTOMS|TINY TILLIA", re.I)

LABELER_BRACKET = re.compile(r"\s*\[([^\]]*)\]\s*$")


def split_title(title):
    """('PRODUCT PART', 'LABELER') — the labeler bracket never feeds a rule."""
    t = title or ""
    m = LABELER_BRACKET.search(t)
    if not m:
        return t.strip(), ""
    return t[:m.start()].strip(), m.group(1).strip()


def _match_name(name, table):
    for pat, canon in table:
        if re.search(pat, name, re.I):
            return canon
    return None


def classify_actives(actives):
    """Return (minerals:set, organics:list[(canon, us_status)], other_actives:list)."""
    minerals, organics, other = set(), [], []
    for a in actives or []:
        unii = (a.get("unii") or "").upper()
        name = (a.get("name") or "").upper()
        if unii in MINERAL_UNII:
            minerals.add(MINERAL_UNII[unii]); continue
        if unii in ORGANIC_FILTER_UNII:
            organics.append(ORGANIC_FILTER_UNII[unii]); continue
        m = _match_name(name, MINERAL_NAME)
        if m:
            minerals.add(m); continue
        o = _match_name(name, ORGANIC_FILTER_NAME)
        if o:
            status = next((s for c, s in ORGANIC_FILTER_UNII.values() if c == o), "not_us")
            organics.append((o, status)); continue
        other.append(a.get("name"))
    return minerals, organics, other


def uv_absorbers_in_inactives(inactives):
    """List of {name, canonical, tier} for UV absorbers found among inactives."""
    out, seen = [], set()
    for i in inactives or []:
        n = (i.get("name") if isinstance(i, dict) else str(i)) or ""
        nu = n.upper()
        c = _match_name(nu, INACTIVE_TIER2)
        tier = 2
        if not c:
            c = _match_name(nu, INACTIVE_TIER1)
            tier = 1
        if c and c not in seen:
            seen.add(c)
            out.append({"name": n, "canonical": c, "tier": tier})
    return out


def parse_spf(product_part):
    for m in SPF_RE.finditer(product_part or ""):
        v = int(m.group(1))
        if 2 <= v <= 110:
            return v
    return None


def classify(rec):
    """Return a dict of v2 fields for one canonical record."""
    product, labeler = split_title(rec.get("title") or rec.get("product_name") or "")
    minerals, organics, other_actives = classify_actives(rec.get("active_ingredients"))
    absorbers = uv_absorbers_in_inactives(rec.get("inactive_ingredients"))
    spf = parse_spf(product)
    has_filter = bool(minerals or organics)

    # --- is it a sunscreen at all? ------------------------------------------
    # Order of evidence:
    #   1. FDA monograph id recorded from the SPL (M020 sunscreen / M016 skin
    #      protectant) — decisive when present.
    #   2. Titanium dioxide or any organic filter as active — these have no
    #      OTC use other than sunscreen, so the product is a sunscreen drug.
    #   3. Zinc oxide alone is ALSO a skin-protectant active (diaper cream,
    #      calamine). Decide from skin-protectant co-actives / wording vs sun
    #      wording; if neither, leave it UNRESOLVED instead of guessing.
    monograph = (rec.get("monograph_id") or "").upper()
    zinc_only = minerals == {"zinc oxide"} and not organics
    sp_cue = bool(SKIN_PROTECTANT.search(product)) or any(
        SKIN_PROTECTANT_COACTIVE.search(a or "") for a in other_actives)
    sun_cue = bool(spf or SUN_WORDS.search(product))
    if not has_filter:
        verdict, basis = "no_uv_filter", "actives"
    elif ORAL.search(product) and not (spf or SUN_WORDS.search(product)):
        # oral / homeopathic / sanitizer products that list ZnO or TiO2;
        # never applied when the title states an SPF or sunscreen wording
        verdict, basis = "no_uv_filter", "not_a_topical_sunscreen"
    elif monograph == MONOGRAPH_SUNSCREEN:
        verdict, basis = "sunscreen", "monograph_M020"
    elif monograph == MONOGRAPH_SKIN_PROTECTANT:
        verdict, basis = "skin_protectant", "monograph_M016"
    elif not zinc_only:
        verdict, basis = "sunscreen", "tio2_or_organic_active"
    elif STRONG_SUN.search(product) and not STRONG_PROTECTANT.search(product):
        verdict, basis = "sunscreen", "zinc_with_sunscreen_word"
    elif sun_cue and not (sp_cue and not spf):
        verdict, basis = "sunscreen", "zinc_with_sun_wording"
    elif sp_cue:
        verdict, basis = "skin_protectant", "zinc_with_protectant_cue"
    elif COSMETIC_FORMAT.search(product):
        verdict, basis = "sunscreen", "zinc_cosmetic_format_inferred"
    else:
        verdict, basis = "unresolved", "zinc_no_signal"

    if verdict == "sunscreen":
        is_sunscreen = True
        if COLOR_COSMETIC.search(product):
            product_type = "color_cosmetic_spf"
        elif LIP.search(product) and not FACE_BODY.search(product):
            product_type = "lip_spf"
        else:
            product_type = "sunscreen"
    elif verdict == "skin_protectant":
        is_sunscreen = False
        product_type = "calamine" if CALAMINE.search(product) else "skin_protectant"
    elif verdict == "unresolved":
        is_sunscreen, product_type = None, "unresolved_zinc"
    else:
        is_sunscreen, product_type = False, "no_uv_filter"

    tinted = bool(TINTED.search(product))

    # --- legacy category vocabulary, kept for downstream consumers ----------
    legacy_category = {
        "sunscreen": "sunscreen",
        "color_cosmetic_spf": "makeup",
        "lip_spf": "lip_balm",
        "skin_protectant": "diaper_cream" if re.search(r"DIAPER|RASH|BUTT|BOTTOM", product, re.I) else "other",
        "unresolved_zinc": "other",
        "calamine": "calamine",
        "no_uv_filter": "other",
    }[product_type]

    # --- mineral --------------------------------------------------------------
    mineral_only_actives = bool(minerals) and not organics
    non_uv_actives = [a for a in other_actives if a]
    # "100% mineral" = all UV protection comes from ZnO/TiO2: only mineral
    # UV actives, and no UV filter or UV-absorbing booster hidden among the
    # inactives. Non-UV actives (niacinamide, menthol) do not change that.
    # Only defined for products classified as sunscreens.
    hundred_pct_mineral = bool(is_sunscreen) and mineral_only_actives and not absorbers

    # --- baby -----------------------------------------------------------------
    def _baby(text):
        return bool(BABY_RE.search(BABY_FALSE_POSITIVE.sub(" ", text or "")))
    if _baby(product):
        baby_signal = "product_name"
    elif labeler and _baby(labeler) and not BABY_LABELER_BLOCK.search(labeler):
        baby_signal = "brand_name"
    elif BABY_BRAND_LABELERS.search(labeler) or BABY_BRAND_LABELERS.search(product):
        baby_signal = "brand_list_review"
    elif (rec.get("label_flags") or {}).get("front_panel_baby_words"):
        baby_signal = "front_panel"
    elif BABY_FALSE_POSITIVE.search(product):
        baby_signal = "false_positive_phrase"
    else:
        baby_signal = "none"
    name_hit = baby_signal in ("product_name", "brand_name")

    mineral_type = ("zinc_titanium" if minerals == {"zinc oxide", "titanium dioxide"}
                    else "zinc" if minerals == {"zinc oxide"}
                    else "titanium" if minerals == {"titanium dioxide"} else "none")

    return {
        "classifier_version": CLASSIFIER_VERSION,
        "labeler_from_title": labeler,
        "spf": spf,
        "is_sunscreen": is_sunscreen,
        "sunscreen_basis": basis,
        "product_type": product_type,
        "is_tinted": tinted,
        "category": legacy_category,
        "uv_filters_mineral": sorted(minerals),
        "uv_filters_organic": sorted({o for o, _ in organics}),
        "non_us_filter_active": sorted({o for o, s in organics if s == "not_us"}),
        "non_uv_actives": non_uv_actives,
        "uv_absorbers_in_inactives": absorbers,
        "contains_zinc_oxide": "zinc oxide" in minerals,
        "contains_titanium_dioxide": "titanium dioxide" in minerals,
        "contains_chemical_filter": bool(organics),
        "has_hidden_chemical_filter": bool(absorbers) and mineral_only_actives,
        "mineral_type": mineral_type,
        "is_mineral_only_actives": mineral_only_actives,
        "is_hundred_percent_mineral": hundred_pct_mineral,
        "baby_signal": baby_signal,
        "baby_labeled": name_hit,
    }
