#!/usr/bin/env python3
"""Same ingredient, two names: the printed label's INCI name and the FDA filing's
substance name (UNII preferred term).

The site shows the printed list plus whatever the filing adds. When the filing
names a printed ingredient differently ("Carbomer" / "CARBOMER HOMOPOLYMER,
UNSPECIFIED TYPE", "Tocopherol" / ".ALPHA.-TOCOPHEROL, DL-"), the filed name
must not be shown a second time as if it were another ingredient.

How a pair is accepted (high precision, 2026-10-20):
  1. learned from the corpus: on labels where the printed list and the filing
     each have the same small number (1-3) of items left unmatched, those items
     are paired; a pair seen on 2+ labels is a candidate, and
  2. the candidate is kept only if the two names share a distinctive word
     (not a generic one such as EXTRACT, OIL, ACID, COPOLYMER), or the pair is
     in CURATED below (INCI <-> USAN/UNII names with no word in common).
Statistical pairing alone produced false pairs (CI 77491 <-> WATER), so a pair
with neither (2) condition is never used.
"""
import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data/reference/inactive_synonyms.json")

GENERIC = {"EXTRACT", "OIL", "SEED", "LEAF", "FLOWER", "FRUIT", "ROOT", "ACID", "SODIUM", "COPOLYMER",
           "CROSSPOLYMER", "POLYMER", "HYDROGENATED", "GLYCERYL", "ESTERS", "ESTER", "WATER", "POWDER",
           "ALCOHOL", "UNSPECIFIED", "TYPE", "SOURCE", "WHOLE", "BUTTER", "KERNEL", "PEEL", "STEM", "BARK",
           "ORGANIC", "NATURAL", "CERTIFIED", "DERIVED", "PLANT", "CROSSLINKED", "WAXES"}
# INCI name key -> filed/UNII name, no word in common (each checked by hand)
CURATED = {
    ("OZOKERITE", "CERESIN"), ("CHAMOMILLA RECUTITA", "CHAMOMILE"), ("CHAMOMILLA RECUTITA", "MATRICARIA"),
    ("CELLULOSE GUM", "CARBOXYMETHYLCELLULOSE"), ("CAPRIC/CAPRYLIC TRIGLYCERIDE", "MEDIUM-CHAIN TRIGLYCERIDES"),
    ("CAPRYLIC/CAPRIC TRIGLYCERIDE", "MEDIUM-CHAIN TRIGLYCERIDES"), ("VP/EICOSENE", "EICOSYL POVIDONE"),
    ("PVP/EICOSENE", "EICOSYL POVIDONE"), ("VP/HEXADECENE", "HEXADECYL POVIDONE"),
    ("TRIACONTANYL PVP", "TRICONTANYL POVIDONE"), ("SCLEROTIUM GUM", "BETASIZOFIRAN"),
    ("SYNTHETIC FLUORPHLOGOPITE", "MAGNESIUM POTASSIUM ALUMINOSILICATE FLUORIDE"),
    ("ACRYLATES/OCTYLACRYLAMIDE COPOLYMER", "N-TERT-OCTYLACRYLAMIDE"),
    ("ACRYLATES/C10-30 ALKYL ACRYLATE CROSSPOLYMER", "CARBOMER INTERPOLYMER"),
    ("ETHANOL", "ALCOHOL"), ("OCTYL PALMITATE", "ETHYLHEXYL PALMITATE"), ("UBIQUINONE", "UBIDECARENONE"),
    ("HYDROXYAPATITE", "TRIBASIC CALCIUM PHOSPHATE"), ("PHYTIC ACID", "FYTIC ACID"),
    ("LINUM USITATISSIMUM", "FLAX SEED"), ("AVENA SATIVA", "OATMEAL"), ("ORYZA SATIVA", "RICE BRAN"),
    ("HIBISCUS ESCULENTUS", "OKRA"), ("TERMINALIA FERDINANDIANA", "KAKADU PLUM"),
    ("BEESWAX", "YELLOW WAX"), ("CERA ALBA", "YELLOW WAX"), ("SWEET ALMOND OIL", "ALMOND OIL"),
    ("THEOBROMA CACAO", "COCOA BUTTER"), ("EUPHORBIA CERIFERA", "CANDELILLA WAX"),
    ("FOENICULUM VULGARE", "FENNEL SEED"), ("ANTHEMIS NOBILIS", "CHAMAEMELUM NOBILE"),
    ("GARDENIA FLORIDA", "GARDENIA JASMINOIDES"), ("CASSIA ALATA", "SENNA ALATA"),
    ("POLYGONUM TINCTORIUM", "PERSICARIA TINCTORIA"), ("SPIRAEA ULMARIA", "FILIPENDULA ULMARIA"),
    ("SPIRULINA MAXIMA", "ARTHROSPIRA MAXIMA"), ("CRAMBE ABYSSINICA", "CRAMBE HISPANICA"),
    ("C13-14 ISOALKANE", "C13-14 ISOPARAFFIN"), ("PEG-8", "POLYETHYLENE GLYCOL 400"),
    ("PEG-400", "POLYETHYLENE GLYCOL 400"), ("PHOSPHOLIPIDS", "LECITHIN"), ("LYSOLECITHIN", "LYSOPHOSPHATIDYLCHOLINE"),
    ("SILICONE", "SILICON"), ("ECTOIN", "ECTOINE"), ("SUNFLOWER SEED OIL", "SUNFLOWER OIL"),
}


def words(name):
    return {w for w in re.findall(r"[A-Z][A-Z0-9]{3,}", (name or "").upper().replace(".", " "))
            if w not in GENERIC}


def _stem(w):
    return w[:6]


_FATTY = re.compile(r"(LAURATE|OLEATE|STEARATE|ISOSTEARATE|PALMITATE|MYRISTATE|BEHENATE|CAPRYLATE|CAPRATE|"
                    r"SUCCINATE|LINOLEATE|COCOATE)")
_MARKERS = ("PEG", "GLYCOL", "STYRENE", "POLYGLYCERYL", "SILYLATE")


def conflict(p, f):
    """Names that share a word but are different substances: PEG-6 sorbitan oleate vs
    sorbitan oleate, polyethylene vs polyethylene glycol, laurate vs oleate."""
    for m in _MARKERS:
        if (m in p) != (m in f) and not (m == "POLYGLYCERYL" and "POLYGLYCEROL" in p):
            return True
    fp, ff = set(_FATTY.findall(p)), set(_FATTY.findall(f))
    return bool(fp and ff and not (fp & ff))


def related(printed, filed):
    p, f = (printed or "").upper(), (filed or "").upper()
    if conflict(p, f) and not any(a in p and b in f for a, b in CURATED):
        return False
    if any(a in p and b in f for a, b in CURATED):
        return True
    wp, wf = {_stem(w) for w in words(p)}, {_stem(w) for w in words(f)}
    return bool(wp & wf)


def learn(master_rows, canon_by_id, same_display, key):
    """Build {printed_key: [unii, ...]} from labels with matching residuals."""
    pairs, names = collections.Counter(), {}
    for r in master_rows:
        pn = r.get("inactives_printed_n") or 0
        if not pn:
            continue
        printed = r["inactives"][:pn]
        c = canon_by_id.get(r["setid"]) or {}
        filed = [(i.get("name") or "", i.get("unii")) for i in c.get("inactive_ingredients") or []
                 if isinstance(i, dict) and i.get("unii")]
        pm = [p for p in printed if not any(same_display(n, p) for n, _ in filed)]
        fm = [(n, u) for n, u in filed if not any(same_display(n, p) for p in printed)]
        if 1 <= len(pm) <= 3 and len(pm) == len(fm):
            for p in pm:
                for n, u in fm:
                    if related(p, n):
                        pairs[(key(p), u)] += 1
                        names[(key(p), u)] = (p, n)
    keep = {k: v for k, v in pairs.items() if v >= 2}
    out = collections.defaultdict(list)
    for (k, u), n in sorted(keep.items()):
        out[k].append(u)
    return dict(out), {f"{k}|{u}": {"printed": names[(k, u)][0], "filed": names[(k, u)][1], "labels": n}
                       for (k, u), n in keep.items()}


def main():
    import sys
    sys.path.insert(0, HERE)
    import inactive_union as U
    from us_master import CANON, MASTER
    canon = {}
    for line in open(CANON, encoding="utf-8"):
        c = json.loads(line)
        canon[c["setid"]] = c
    rows = [json.loads(l) for l in open(MASTER, encoding="utf-8")]
    rows = [r for r in rows if r.get("in_scope") and r.get("status") == "active"]
    syn, detail = learn(rows, canon, U.same_display, U.key)
    json.dump({"note": __doc__.strip().splitlines()[0], "pairs": detail}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    print(f"{len(detail)} synonym pairs -> {OUT}")


if __name__ == "__main__":
    main()
