#!/usr/bin/env python3
"""Active strengths as the label prints them, read from the Drug Facts "Active
ingredient(s)" text (data/views/label_claims.jsonl, field actives_text).

The FDA filing's structured strengths are sometimes an amount per volume (g per
100 mL) or a scaled ratio, which is not the w/w percentage on the tube (2026-10-22
label audit: 13.2 filed for a printed 12%). Where the printed text names the active
with a percentage, that percentage is the one a parent reads.
"""
import difflib
import re

SYN = {
    "OCTINOXATE": ["OCTYL METHOXYCINNAMATE", "ETHYLHEXYL METHOXYCINNAMATE"],
    "OCTISALATE": ["OCTYL SALICYLATE", "ETHYLHEXYL SALICYLATE"],
    "AVOBENZONE": ["BUTYL METHOXYDIBENZOYLMETHANE"],
    "OXYBENZONE": ["BENZOPHENONE-3", "BENZOPHENONE 3"],
    "ENSULIZOLE": ["PHENYLBENZIMIDAZOLE SULFONIC ACID"],
    "OCTOCRYLENE": [], "HOMOSALATE": [], "ZINC OXIDE": [], "TITANIUM DIOXIDE": [],
}
NUM = r"(\d{1,2}(?:\.\d{1,3})?)"
NAME_PCT = re.compile(r"([A-Z][A-Z0-9 \-]{2,45}?)[\s\(\)\-:\.…·,\u2013\u2014]*" + NUM + r"\s*%")
PCT_NAME = re.compile(NUM + r"\s*%\s*(?:W/W)?\s*([A-Z][A-Z \-]{2,40})")


def _close(a, b):
    a, b = re.sub(r"[^A-Z0-9]", "", a), re.sub(r"[^A-Z0-9]", "", b)
    return a == b or (len(b) >= 8 and (b in a or difflib.SequenceMatcher(None, a[-len(b) - 2:], b).ratio() >= 0.86))


def read(text, names):
    """{active name: printed %} for the names found exactly once with one value."""
    if not text:
        return {}
    t = text.split(" || ")[0].upper()
    t = re.sub(r"\bNON[- ]?NANO\b|\bUNCOATED\b|\bMICRONI[SZ]ED\b|\bSUNSCREEN\b", " ", t)
    # "3% Avobenzone 13% Homosalate" or "Avobenzone 3% Homosalate 13%": the text's first
    # token decides which way each number belongs
    if re.match(r"[\W_]*\d{1,2}(?:\.\d+)?\s*%", t):
        pairs = [(m.group(2), float(m.group(1))) for m in PCT_NAME.finditer(t)]
    else:
        pairs = [(m.group(1), float(m.group(2))) for m in NAME_PCT.finditer(t)]
    # a run of names before one number ("Zinc Oxide Titanium Dioxide Zinc Oxide - 19.5%", where
    # the panel lists the names and then each with its strength): the number is the last name's
    def _last(nm):
        best, end = None, -1
        for n in names:
            for a in [n] + SYN.get(n, []):
                i = nm.rfind(a)
                if i >= 0 and i + len(a) > end:
                    best, end = n, i + len(a)
        return best
    out = {}
    for n in names:
        alts = [n] + SYN.get(n, [])
        vals = {v for nm, v in pairs if any(_close(nm.strip(), a) for a in alts) and 0 < v <= 25
                and _last(nm) in (None, n)}
        if len(vals) == 1:
            out[n] = vals.pop()
    return out


if __name__ == "__main__":
    for t, ns in [("Avobenzone (2.0%)......Sunscreen Octinoxate (7.0%)........Sunscreen Ozybenzone (2.5%)......Sunscreen",
                   ["AVOBENZONE", "OCTINOXATE", "OXYBENZONE"]),
                  ("3% Avobenzone 13% Homosalate 5% Octisalate 7% Octocrylene 4% Oxybenzone || x",
                   ["AVOBENZONE", "HOMOSALATE", "OCTISALATE", "OCTOCRYLENE", "OXYBENZONE"]),
                  (": Zinc Oxide - 18.6%", ["ZINC OXIDE"]), ("Non-nano Zinc Oxide 22%", ["ZINC OXIDE"]),
                  ("Titanium Dioxide 6.24%, Zinc Oxide 3.84%, Arbutin 2.00%", ["TITANIUM DIOXIDE", "ZINC OXIDE"]),
                  ("Homosalate 10.0 Octocrylene 10.0", ["HOMOSALATE"]),
                  ("Zinc Oxide Titanium Dioxide Zinc Oxide - 19.5% ....... Sunscreen Titanium Dioxide \u2013 4.0%....... Sunscreen",
                   ["TITANIUM DIOXIDE", "ZINC OXIDE"])]:
        print(read(t, ns))
