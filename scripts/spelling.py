"""Misspelled ingredient names on filed labels ("Phenoxyethenol", "Methyl Paraben",
"Butly Octyl Salicylate") still name the ingredient: a corrected spelling is used to
find the flags, while the evidence keeps the name as printed."""
import difflib
import functools
import re

# ingredients that give a flag, as the rules spell them
TERMS = ["phenoxyethanol", "fragrance", "parfum", "methylparaben", "ethylparaben", "propylparaben", "butylparaben",
         "isobutylparaben", "methylisothiazolinone", "methylchloroisothiazolinone", "butyloctyl salicylate",
         "linalool", "limonene", "citronellol", "geraniol", "eugenol", "coumarin", "cyclopentasiloxane",
         "cyclotetrasiloxane", "cyclohexasiloxane", "dmdm hydantoin", "propylene glycol", "retinyl palmitate",
         "benzyl alcohol", "methyldibromo glutaronitrile", "isobornyl acrylate", "iodopropynyl butylcarbamate",
         "triethanolamine", "imidazolidinyl urea", "diazolidinyl urea", "oxybenzone", "octocrylene", "avobenzone",
         "homosalate", "octisalate", "octinoxate", "benzophenone", "hexyl cinnamal", "citral", "farnesol"]
_T = {re.sub(r"[^a-z]", "", t): t for t in TERMS}
# real, different ingredients that sit close to a term
NOT = re.compile(r"behenyl|bahenyl|beheneyl|benhenyl|bhenyl|cetyl ?palmitate|ethyl ?palmitate|dipropylene|"
                 r"phenylethanol|phenethyl|quaternium|tocopher|methylpropanediol|isopropyl ?paraben|citronell[ay]|"
                 r"cinnamate", re.I)
# a misspelled propylene glycol ESTER (laurate, stearate) is not propylene glycol
_ESTER = re.compile(r"gl\w*\s*col\s+\w*(?:ate|ates)\b|alginate|acetal", re.I)


@functools.lru_cache(maxsize=None)
def corrected(name):
    """The name with a misspelled flag ingredient respelled, or None when nothing changed."""
    low = (name or "").lower()
    if NOT.search(low):
        return None
    flat = re.sub(r"[^a-z]", "", low)
    toks = re.findall(r"[a-z]+(?:-[a-z0-9]+)?", low)
    # single tokens and adjacent pairs ("methyl paraben", "butly octyl")
    cands = toks + [a + b for a, b in zip(toks, toks[1:])] + [a + b + c for a, b, c in zip(toks, toks[1:], toks[2:])]
    for c in cands:
        c2 = re.sub(r"[^a-z]", "", c)
        if len(c2) < 6:
            continue
        if c2 in _T:
            if _T[c2] != "propylene glycol" or not _ESTER.search(low):
                if c2 not in flat.replace(c2, "", 0) and c != _T[c2] and _T[c2].replace(" ", "") not in flat:
                    return _T[c2]
            continue
        for k, t in _T.items():
            if k in flat:          # spelled right somewhere in the name: the rules already read it
                continue
            if t == "propylene glycol" and _ESTER.search(low):
                continue
            if abs(len(c2) - len(k)) <= 2 and c2[0] == k[0] and difflib.SequenceMatcher(None, c2, k).ratio() >= 0.88:
                return t
    return None
