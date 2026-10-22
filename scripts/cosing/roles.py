#!/usr/bin/env python3
"""What an ingredient does, for the Sunscreen Check's ingredient list.

Source: the functions the EU CosIng register lists for the ingredient. CosIng lists
every function an ingredient MAY serve in any cosmetic (olive oil: "fragrance,
perfuming, skin conditioning"), so one main job is chosen by a fixed rule:

  1. sunscreen context first: a UV-absorbing ingredient that is not a declared active
     (the site's hidden-booster rule) is "absorbs UV, not listed as an active";
  2. otherwise the most specific CosIng function, in the order of PRIORITY below;
  3. "perfuming"/"fragrance" and "antimicrobial" count only when CosIng lists nothing
     more specific, or the name itself is a fragrance (Parfum, an EU-listed allergen);
  4. the generic "skin conditioning" only when nothing else is listed.

The job is a function, never an origin: "plant- or animal-derived" is not a job.
Origin is a separate fact (origin()), given only when the INCI name states it.
"""
import re

# CosIng function -> job key. Earlier = more specific = wins.
PRIORITY = [
    ("UV FILTER", "uv_filter"), ("UV ABSORBER", "uv_filter"),
    ("PRESERVATIVE", "preservative"),
    ("CHELATING", "chelating"),
    ("COLORANT", "colorant"), ("HAIR DYEING", "colorant"),
    ("ANTIOXIDANT", "antioxidant"),
    ("SURFACTANT - EMULSIFYING", "emulsifier"), ("EMULSION STABILISING", "emulsion_stabiliser"),
    ("SKIN CONDITIONING - EMOLLIENT", "emollient"), ("SKIN CONDITIONING - OCCLUSIVE", "occlusive"),
    ("REFATTING", "emollient"),
    ("HUMECTANT", "humectant"), ("SKIN CONDITIONING - HUMECTANT", "humectant"), ("MOISTURISING", "humectant"),
    ("FILM FORMING", "film_former"),
    ("VISCOSITY CONTROLLING", "thickener"), ("GEL FORMING", "thickener"),
    ("OPACIFYING", "opacifier"), ("ABSORBENT", "absorbent"), ("BULKING", "bulking"), ("ANTICAKING", "anticaking"),
    ("BINDING", "binder"),
    ("SLIP MODIFIER", "slip"), ("SMOOTHING", "slip"), ("SURFACE MODIFIER", "slip"),
    ("DISPERSING NON-SURFACTANT", "dispersing"), ("SURFACTANT - DISPERSING", "dispersing"),
    ("SURFACTANT - SOLUBILIZING", "solubiliser"), ("SURFACTANT - CLEANSING", "cleansing"), ("CLEANSING", "cleansing"),
    ("SURFACTANT", "surfactant"),
    ("BUFFERING", "ph"), ("PH ADJUSTERS", "ph"),
    ("SOOTHING", "soothing"), ("SKIN PROTECTING", "skin_protecting"),
    ("SOLVENT", "solvent"), ("PLASTICISER", "plasticiser"), ("LIGHT STABILIZER", "light_stabiliser"),
    ("ANTIFOAMING", "antifoaming"), ("PROPELLANT", "propellant"), ("DENATURANT", "denaturant"),
    ("ASTRINGENT", "astringent"), ("ABRASIVE", "abrasive"), ("EXFOLIATING", "exfoliant"), ("KERATOLYTIC", "exfoliant"),
    ("REFRESHING", "refreshing"), ("TONIC", "tonic"), ("ANTISTATIC", "antistatic"),
    ("SKIN CONDITIONING - MISCELLANEOUS", "skin_conditioning"), ("SKIN CONDITIONING", "skin_conditioning"),
    ("HAIR CONDITIONING", "skin_conditioning"),
]
WEAK = {"PERFUMING": "fragrance", "FRAGRANCE": "fragrance", "ANTIMICROBIAL": "antimicrobial", "FLAVOURING": "flavour",
        "MASKING": "fragrance", "DEODORANT": "deodorant", "ORAL CARE": "other", "NOT REPORTED": None}
RANK = {f: i for i, (f, _) in enumerate(PRIORITY)}
JOB = dict(PRIORITY)

FRAG_NAME = re.compile(r"\bPARFUM\b|\bFRAGRANCE\b|\bPERFUME\b|\bAROMA\b|\bFLAVOR\b|\bESSENTIAL OIL\b", re.I)
WATER = re.compile(r"^(AQUA|WATER)$", re.I)


def job(functions, name, inci=None, booster=False, eu_allergen=False):
    """(job key, CosIng function it came from). None when CosIng gives nothing usable."""
    if booster:
        return "uv_booster", None
    if WATER.match((inci or "").strip()) or WATER.match((name or "").strip()):
        return "base", "SOLVENT"
    fs = [f.upper() for f in functions or []]
    if FRAG_NAME.search(name or "") or FRAG_NAME.search(inci or "") or eu_allergen and "PERFUMING" in fs:
        return "fragrance", "PERFUMING"
    strong = sorted((f for f in fs if f in RANK), key=RANK.get)
    # UV filter/absorber from CosIng only counts as the job for a declared active; for an
    # inactive the site's booster rule decides, so skip it here
    u0 = (inci or name or "").upper()
    if "FRAGRANCE" in fs and (not BINOMIAL.match(u0) and not FIXED_OIL.search(u0) and not re.search(r"\bEXTRACT\b", u0)
                              or ESSENTIAL_OIL.search(u0)):
        return "fragrance", "FRAGRANCE"
    if "UV FILTER" in fs:                       # an EU-listed UV filter (Annex VI), e.g. TEA-salicylate
        return "uv_filter", "UV FILTER"
    strong = [f for f in strong if JOB[f] != "uv_filter"]
    if strong:
        return JOB[strong[0]], strong[0]
    weak = [f for f in fs if f in WEAK and WEAK[f]]
    if weak:
        w = WEAK[weak[0]]
        u = (inci or name or "").upper()
        # CosIng lists "perfuming" for many plant materials; only an essential oil is fragrance
        if w == "fragrance" and FIXED_OIL.search(u):
            return "emollient", weak[0]
        if w == "fragrance" and BINOMIAL.match(u) and not re.search(r"\bOIL\b", u):
            return "skin_conditioning", weak[0]
        return w, weak[0]
    return None, None


ESSENTIAL_OIL = re.compile(r"\b(FLOWER|LEAF|PEEL|HERB|BARK|WOOD|ROOT|RHIZOME|NEEDLE|TWIG|RESIN|GUM)\b.*\bOIL\b")
FIXED_OIL = re.compile(r"\b(SEED|KERNEL|NUT|FRUIT|GERM|BRAN)\b.*\bOIL\b|\bBUTTER\b|\bCERA\b")


# ---- origin, only when the INCI name states it ------------------------------
PLANT_PART = re.compile(r"\b(SEED|LEAF|LEAVES|FLOWER|ROOT|FRUIT|BARK|PEEL|KERNEL|STEM|RHIZOME|BUD|CALLUS|"
                        r"MERISTEM|SPROUT|WOOD|NUT|BERRY|HERB|SHOOT|TWIG|BULB|TUBER|POLLEN|SAP|GUM|CERA|BRAN|GERM|"
                        r"HUSK|JUICE|WATER|OIL|BUTTER|EXTRACT|POWDER|FLOUR)\b")
BINOMIAL = re.compile(r"^[A-Z][A-Z]+ [A-Z]+[A-Z]\b")
ANIMAL = re.compile(r"\b(CERA ALBA|BEESWAX|LANOLIN|HONEY|MEL\b|PROPOLIS|ROYAL JELLY|COLLAGEN|ELASTIN|KERATIN|SILK|"
                    r"SERICIN|SNAIL|MILK|LAC\b|WHEY|CASEIN|EGG|OVUM|TALLOW|SQUALANE \(SHARK|FISH|PLACENTA|CARMINE|CI 75470)")


def origin(inci, plant_genera=()):
    """'plant' | 'animal' | None (unknown or synthetic: no claim)."""
    u = (inci or "").upper()
    if re.search(r"\bSYNTHETIC\b", u):
        return None
    if ANIMAL.search(u):
        return "animal"
    first = u.split(" ")[0] if u else ""
    if BINOMIAL.match(u) and PLANT_PART.search(u) and (not plant_genera or first in plant_genera):
        return "plant"
    return None
