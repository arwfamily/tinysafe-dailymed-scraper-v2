"""Reproduce every number in claim_ledger.json from the raw data files.

Usage:
  python3 verify_ledger.py us_sunscreens.jsonl au_ingredients.jsonl

Sources:
  https://raw.githubusercontent.com/arwfamily/tinysafe-dailymed-scraper-v2/main/data/canonical/us_sunscreens.jsonl
  https://raw.githubusercontent.com/arwfamily/global-sunscreen/main/data/canonical/au_ingredients.jsonl
"""
import json, re, sys

CHEM_ACTIVE = re.compile(
    r"AVOBENZONE|OCTOCRYLENE|HOMOSALATE|OCTISALATE|OCTINOXATE|OXYBENZONE|ENSULIZOLE|"
    r"MERADIMATE|SULISOBENZONE|DIOXYBENZONE|PADIMATE|AMINOBENZOIC|TROLAMINE|CINOXATE|"
    r"ECAMSULE|BEMOTRIZINOL|ETHYLHEXYL SALICYLATE|OCTYL SALICYLATE|METHOXYCINNAMATE")
MINERAL = re.compile(r"ZINC OXIDE|TITANIUM DIOXIDE")
HIDDEN = {
    "butyloctyl salicylate": r"BUTYLOCTYL SALICYLATE",
    "ethylhexyl methoxycrylene": r"METHOXYCRYLENE",
    "polyester-8": r"POLYESTER-8",
    "tridecyl salicylate": r"TRIDECYL SALICYLATE",
    "ethyl ferulate": r"ETHYL FERULATE",
}


def us(path):
    rows = [json.loads(l) for l in open(path)]
    sun = [r for r in rows if r["category"] == "sunscreen"]
    print(f"US-CORPUS-001  rows={len(rows)} sunscreen={len(sun)} "
          f"unique={len({r['formulation_hash'] for r in sun})} "
          f"baby_sunscreen={sum(r['baby_labeled'] for r in sun)}")
    uniq = {}
    for r in sun:
        if r["baby_labeled"]:
            uniq.setdefault(r["formulation_hash"], r)
    a = b = bos = 0
    for r in uniq.values():
        acts = [x["name"].upper() for x in r["active_ingredients"]]
        if any(CHEM_ACTIVE.search(x) for x in acts) or not any(MINERAL.search(x) for x in acts):
            continue
        inact = " | ".join(i["name"].upper() for i in r["inactive_ingredients"])
        hits = [k for k, p in HIDDEN.items() if re.search(p, inact)]
        if hits:
            b += 1
            bos += "butyloctyl salicylate" in hits
        else:
            a += 1
    print(f"US-HID-001     {b}/{a + b} = {b / (a + b):.1%}")
    print(f"US-HID-002     {bos}/{a + b} = {bos / (a + b):.1%}")


def au(path):
    rows = [json.loads(l) for l in open(path)]
    bem = [p for p in rows if any(re.search(r"bemotrizinol|bis-ethylhexyloxyphenol", a["name"].lower())
                                  for a in p.get("actives", []))]
    kids = [p for p in bem if re.search(r"baby|kid|child|junior|toddler", p["product_name"].lower())]
    print(f"AU-BEMT-001    {len(bem)}/{len(rows)} (baby/kids-named {len(kids)})  SCOPE: search export, not census")


if __name__ == "__main__":
    us(sys.argv[1])
    au(sys.argv[2])
