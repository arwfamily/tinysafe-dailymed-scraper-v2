#!/usr/bin/env python3
"""Inactive ingredients = structured SPL table  ∪  printed Drug Facts list.

Many labelers fill the SPL "INGREDIENTS AND APPEARANCE" table (UNII rows) with
only a few inactives while the Drug Facts "Inactive ingredients" text prints
the full list. Reading only the table under-detects flags (fragrance,
botanicals, ethoxylates, oils...). This view joins both.

For every label in data/canonical/us_sunscreens.jsonl it writes one
row to data/views/inactive_union.jsonl:

  setid, i_union (label order: printed list first, then table-only items),
  i_src ('structured' | 'text' | 'both'), i_struct_n, i_text_n, i_union_n,
  category, thin (True when even the union has <= THIN_MAX items: the label itself is
  incomplete, e.g. Isa Knox lists only "Water").

Matching across the two sources uses a loose key (upper case, bracketed
detail dropped, punctuation removed, Aqua/Eau -> Water), so
"COCO-CAPRYLATE/CAPRATE" and "Coco-Caprylate/Caprate" count once and
"POLYESTER-8 (1400 MW, ...)" matches "Polyester-8".

Usage: python3 scripts/inactive_union.py [canonical.jsonl] [out.jsonl]
"""
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spl_parse import split_ingredient_list  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIN_MAX = 7
# FDA SRS names in the structured table vs INCI names on the printed label,
# for the pairs that account for most mismatches (2026-10-19 measurement).
_SYN = {
    "AQUA": "WATER", "EAU": "WATER", "PURIFIEDWATER": "WATER", "DEIONIZEDWATER": "WATER",
    "DISTILLEDWATER": "WATER", "PARFUM": "FRAGRANCE", "PERFUME": "FRAGRANCE",
    "GLYCEROL": "GLYCERIN",
    "ALPHATOCOPHEROLACETATE": "TOCOPHERYLACETATE", "DLALPHATOCOPHERYLACETATE": "TOCOPHERYLACETATE",
    "ALPHATOCOPHERYLACETATE": "TOCOPHERYLACETATE", "VITAMINEACETATE": "TOCOPHERYLACETATE",
    "ALPHATOCOPHEROL": "TOCOPHEROL", "DLALPHATOCOPHEROL": "TOCOPHEROL", "VITAMINE": "TOCOPHEROL",
    "EDETATEDISODIUM": "EDTA", "EDETATEDISODIUMANHYDROUS": "EDTA", "EDETATESODIUM": "EDTA",
    "DISODIUMEDTA": "EDTA", "TETRASODIUMEDTA": "EDTA", "TRISODIUMEDTA": "EDTA", "EDETICACID": "EDTA",
    "MEDIUMCHAINTRIGLYCERIDES": "CAPRYLICCAPRICTRIGLYCERIDE", "CAPRYLICCAPRICTRIGLYCERIDES": "CAPRYLICCAPRICTRIGLYCERIDE",
    "SILICONDIOXIDE": "SILICA", "HYDRATEDSILICA": "SILICA", "COLLOIDALSILICONDIOXIDE": "SILICA",
    "GLYCERYLMONOSTEARATE": "GLYCERYLSTEARATE", "CETOSTEARYLALCOHOL": "CETEARYLALCOHOL",
    "CYCLOMETHICONE5": "CYCLOPENTASILOXANE", "TROLAMINE": "TRIETHANOLAMINE",
    "FERRICOXIDERED": "IRONOXIDES", "FERRICOXIDEYELLOW": "IRONOXIDES", "FERROSOFERRICOXIDE": "IRONOXIDES",
    "IRONOXIDE": "IRONOXIDES", "BLACKIRONOXIDE": "IRONOXIDES", "REDIRONOXIDE": "IRONOXIDES", "YELLOWIRONOXIDE": "IRONOXIDES",
    "DOCOSANOL": "BEHENYLALCOHOL", "BUTYLATEDHYDROXYTOLUENE": "BHT", "LEVOMENOL": "BISABOLOL",
    "ALUMINUMOXIDE": "ALUMINA", "ALUMINUMHYDROXIDE": "ALUMINUMHYDROXIDE",
    "ALOEVERALEAF": "ALOEBARBADENSISLEAFJUICE", "ALOEBARBADENSISLEAF": "ALOEBARBADENSISLEAFJUICE",
    "GREENTEALEAF": "CAMELLIASINENSISLEAFEXTRACT", "SODIUMHYDROXIDE": "SODIUMHYDROXIDE",
    "POTASSIUMCETYLPHOSPHATE": "POTASSIUMCETYLPHOSPHATE", "CARBOMERHOMOPOLYMERTYPEC": "CARBOMER",
    "CARBOMER940": "CARBOMER", "CARBOMER980": "CARBOMER", "CARBOMERHOMOPOLYMERTYPEA": "CARBOMER",
    "CARBOMERHOMOPOLYMERTYPEB": "CARBOMER", "CARBOMERINTERPOLYMERTYPEA": "CARBOMER",
    "CARBOXYPOLYMETHYLENE": "CARBOMER", "CAPRYLYLTRISILOXANE": "CAPRYLYLMETHICONE",
    "SORBITANMONOOLEATE": "SORBITANOLEATE", "SORBITANMONOSTEARATE": "SORBITANSTEARATE",
    "POLYOXYL20CETOSTEARYLETHER": "CETEARETH20", "CYCLOMETHICONE6": "CYCLOHEXASILOXANE",
    "SODIUMPYRROLIDONECARBOXYLATE": "SODIUMPCA", "GLYCYRRHIZINATEDIPOTASSIUM": "DIPOTASSIUMGLYCYRRHIZATE",
    "HYPROMELLOSES": "HYDROXYPROPYLMETHYLCELLULOSE", "HYPROMELLOSE": "HYDROXYPROPYLMETHYLCELLULOSE",
    "GLYCERYLMONOCAPRYLATE": "GLYCERYLCAPRYLATE", "POLYSORBATE80": "POLYSORBATE80",
    "PENTAERYTHRITOLTETRAKIS335DITERTBUTYL4HYDROXYPHENYLPROPIONATE": "PENTAERYTHRITYLTETRADITBUTYLHYDROXYHYDROCINNAMATE",
    "PENTAERYTHRITOLTETRAKIS": "PENTAERYTHRITYLTETRADITBUTYLHYDROXYHYDROCINNAMATE",
}
_WATERWORDS = {"WATER", "AQUA", "EAU", "PURIFIED", "DEIONIZED", "DISTILLED", "USP", "DEMINERALIZED"}
_JUNK_ITEM = re.compile(r"^\s*(?:inactive(?:\s+ingredients?)?|ingredients?|other\s+ingredients?|organic(?:\s+ingredients?)?|"
                        r"certified organic(?: ingredients?)?)\s*[:.]?\s*$|\b(?:contains|distributed by|manufactured (?:for|by)|"
                        r"made in|www\.|\.com\b|questions\?|call\s+\d)", re.I)


def key(name):
    n = (name or "").upper()
    prev = None
    while prev != n:                               # bracketed detail / synonyms, nested too
        prev, n = n, re.sub(r"\([^()]*\)|\[[^\[\]]*\]", "", n)
    words = set(re.sub(r"[^A-Z0-9]+", " ", n).split())
    if words and words <= _WATERWORDS:
        return "WATER"
    n = re.sub(r"[^A-Z0-9]", "", n)
    return _SYN.get(n, n)


_STOP = {"OIL", "SEED", "LEAF", "EXTRACT", "FRUIT", "PEEL", "ROOT", "FLOWER", "BARK", "KERNEL",
         "BUTTER", "WATER", "JUICE", "POWDER", "ORGANIC", "CERTIFIED", "NATURAL", "AND", "THE",
         "STEM", "HERB", "PLANT", "WHOLE", "CERA", "AQUA", "USP", "NF", "VITAMIN", "WAX"}
_TOKSYN = {"YELLOW": "BEESWAX", "BEESWAX": "BEESWAX", "MANDARIN": "TANGERINE", "TANGERINE": "TANGERINE",
           "SEABUCKTHORN": "HIPPOPHAE", "BUCKTHORN": "HIPPOPHAE", "SHEA": "BUTYROSPERMUM",
           "TOCOPHERYL": "TOCOPHERYL", "PARFUM": "FRAGRANCE", "PERFUME": "FRAGRANCE",
           "VERA": "BARBADENSIS", "ARGAN": "ARGANIA", "CHAMOMILE": "CHAMOMILLA", "GINSENG": "PANAX",
           "ASIAN": "", "RANDOMIZED": "", "FLOWERING": "", "TOP": ""}


def tokens(name):
    """Distinctive words of a name, bracketed common names included."""
    n = re.sub(r"[^A-Z0-9]+", " ", (name or "").upper())
    out = set()
    for w in n.split():
        if len(w) < 3 or w in _STOP:
            continue
        w = _TOKSYN.get(w, w)
        if w:
            out.add(w)
    if {"WHITE", "WAX"} <= set(n.split()) or {"YELLOW", "WAX"} <= set(n.split()):
        out.add("BEESWAX")
    return out


def same(a, b):
    """Two names for one ingredient: equal loose keys, or one name's distinctive
    words all appear in the other ("SUNFLOWER OIL" ~ "Helianthus Annuus (Sunflower) Seed Oil")."""
    if key(a) == key(b):
        return True
    ka, kb = key(a), key(b)
    if min(len(ka), len(kb)) >= 8 and difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.92:
        return True                                # spelling variants ("methylparaen")
    # "SUNFLOWER OIL" ~ "Helianthus Annuus (Sunflower) Seed Oil": the shorter name's
    # words must all be the longer name's bracketed common name (or its genus+species);
    # "DIMETHICONE" is NOT "PEG-10 DIMETHICONE", "ALCOHOL" is NOT "CETOSTEARYL ALCOHOL".
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb or ta == tb:
        return bool(ta) and ta == tb
    small, big = (a, b) if len(ta) < len(tb) else (b, a)
    ts = tokens(small)
    paren = set()
    for m in re.findall(r"\(([^()]*)\)", big.upper()):
        paren |= tokens(m)
    latin = set(re.findall(r"[A-Z]+", re.sub(r"\(.*?\)", " ", big.upper()))[:2])
    return ts <= paren or (ts <= latin and len(ts) >= 2)


_MAY = re.compile(r"[.\s]*[\[(]?\s*(?:\+/-|\(\+/-\))?\s*\bmay\s+contai?n\w*\b\s*(?:/\s*peut\s+cont\w+)?\s*(?:\(?\+/-\)?|/\+/-)?\s*[:/]?\s*", re.I)
_LEAD = re.compile(r"^\s*(?:\u200b)?(?:section\s+)?(?:inactive|inctive)\s+ingredients?\s*[:.]?\s*|"
                   r"^\s*/?\s*ingr[ée]dients?\s+inactifs\s*[:.]?\s*|^\s*aqueous\s+extracts?\s+of\s*:\s*|"
                   r"^\s*glitter\s*:\s*", re.I)


def _clean(x):
    x = re.sub(r"<[^>]*>", " ", x.replace("\u200b", ""))          # <iln...> label codes
    x = re.sub(r"^\s*(?:=|\*+|\(s\)|\u2020|\u2021)\s*", "", x)          # footnote markers
    x = _LEAD.sub("", x)
    x = re.sub(r"\s*\[?\+/-\]?\s*$", "", x).strip().strip("[]").strip().rstrip(".:").strip()
    return x


def resplit(items):
    """Stored printed lists from before the 2026-10-19 splitter fix may hold two
    ingredients in one item ("Beheneth-25, Triethoxycaprylylsilane"); "May
    contain" colorant notes are split off their neighbour ("Phenoxyethanol MAY
    CONTAIN (+/-): Mica" -> "Phenoxyethanol", "Mica"); stray headings are dropped."""
    out = []
    for x in items or []:
        for part in _MAY.split(x):
            if not part.strip():
                continue
            # "Polysorbate 20. Fragrance" -> two items; split_ingredient_list also
            # handles commas, semicolons and bullets
            for piece in re.split(r"\.\s+(?=[A-Z])", part):
                got = split_ingredient_list(piece)
                out.extend(got if got else [piece])
    out = [_clean(x) for x in out]
    return [x for x in out if x and not _JUNK_ITEM.match(x)]


# UV filter actives under their INCI / other names, so a printed list that
# repeats the actives ("Ingredients: Zinc Oxide, Water, ...") does not put an
# active among the inactives.
_ACTIVE_SYN = {
    "OCTINOXATE": {"ETHYLHEXYLMETHOXYCINNAMATE", "OCTYLMETHOXYCINNAMATE"},
    "OCTISALATE": {"ETHYLHEXYLSALICYLATE", "OCTYLSALICYLATE"},
    "OXYBENZONE": {"BENZOPHENONE3"},
    "AVOBENZONE": {"BUTYLMETHOXYDIBENZOYLMETHANE"},
    "ENSULIZOLE": {"PHENYLBENZIMIDAZOLESULFONICACID"},
    "BEMOTRIZINOL": {"BISETHYLHEXYLOXYPHENOLMETHOXYPHENYLTRIAZINE"},
    "ECAMSULE": {"TEREPHTHALYLIDENEDICAMPHORSULFONICACID"},
    "MERADIMATE": {"MENTHYLANTHRANILATE"},
    "SULISOBENZONE": {"BENZOPHENONE4"},
    "DIOXYBENZONE": {"BENZOPHENONE8"},
    "PADIMATEO": {"ETHYLHEXYLDIMETHYLPABA"},
    "ZINCOXIDE": {"CI77947"},
    "TITANIUMDIOXIDE": {"CI77891"},
}


def active_keys(r):
    out = set()
    for a in r.get("active_ingredients") or []:
        k = key(a.get("name") if isinstance(a, dict) else str(a))
        out.add(k)
        out |= _ACTIVE_SYN.get(k, set())
    return out


def is_active(name, akeys):
    n = (name or "").upper()
    if key(n) in akeys:
        return True
    # "Zinc Oxide (CI 77947)", "CI 77891 (Titanium Dioxide)": any bracketed or bare part
    parts = [key(x) for x in re.split(r"[()\[\]]", n) if x.strip()]
    return bool(parts) and all(p in akeys for p in parts)


_VOCAB = None


def _unreadable(items):
    """A printed list read from a poor scan: 30%+ of its items carry a word (5+
    letters) that no other label in the corpus uses ("BU'IYL METHOXYDIBENZOYLMETHANE")."""
    if _VOCAB is None or len(items) < 5:
        return False
    odd = 0
    for x in items:
        ws = [w for w in re.findall(r"[A-Z']+", x.upper()) if len(w) >= 5]
        if any(_VOCAB.get(w, 0) <= 1 for w in ws) or "'" in x and re.search(r"[A-Z]'[A-Z]", x.upper()):
            odd += 1
    return odd / len(items) >= 0.3


def build_vocab(rows):
    global _VOCAB
    c = {}
    for r in rows:
        seen = set()
        for x in (r.get("printed_inactives") or []) + [(i.get("name") if isinstance(i, dict) else str(i)) or ""
                                                      for i in r.get("inactive_ingredients") or []]:
            seen |= {w for w in re.findall(r"[A-Z']+", x.upper()) if len(w) >= 5}
        for w in seen:
            c[w] = c.get(w, 0) + 1
    _VOCAB = c


def union_row(r):
    struct = [(i.get("name") if isinstance(i, dict) else str(i)) or "" for i in r.get("inactive_ingredients") or []]
    struct = [x for x in struct if x.strip()]
    akeys = active_keys(r)
    struct = [x for x in struct if not is_active(x, akeys)]
    text_all = resplit(r.get("printed_inactives"))
    text = [x for x in text_all if not is_active(x, akeys)]
    unreadable = _unreadable(text)
    if unreadable:                       # scanned text too garbled to trust: use the filing
        text = []
    out = []
    for name in text:                       # the printed list, in label order
        if not any(key(name) == key(o) for o in out):
            out.append(name)
    struct_only = [x for x in struct if not any(same(x, t) for t in text)]
    for name in struct_only:                # filed but not found on the printed list
        if not any(same(name, o) for o in out):
            out.append(name)
    src = "both" if struct and text else ("text" if text else "structured")
    return {"setid": r["setid"], "i_union": out, "i_src": src,
            "i_struct_n": len(struct), "i_text_n": len(text), "i_union_n": len(out),
            "struct_only": struct_only, "struct": struct,
            "printed_actives_dropped": len(text_all) - len(text) if not unreadable else 0,
            "text_unreadable": unreadable, "thin": len(out) <= THIN_MAX}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data/canonical/us_sunscreens.jsonl")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data/views/inactive_union.jsonl")
    n = thin = 0
    rows = [json.loads(line) for line in open(src, encoding="utf-8")]
    build_vocab(rows)
    with open(dst, "w", encoding="utf-8") as f:
        for r in rows:
            # every label, whatever its category: downstream products (the
            # Sunnytime db) hold labels later reclassified as makeup or lip balm
            row = union_row(r)
            row["category"] = r.get("category")
            if row["category"] == "sunscreen":
                n += 1
                thin += row["thin"]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {dst}: {n} sunscreen labels, {thin} still thin (<= {THIN_MAX} inactives)")


if __name__ == "__main__":
    main()
