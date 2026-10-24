#!/usr/bin/env python3
"""Last checks on a built site database before it is published (run after site_db.py).
Exits non-zero, with the reasons, when something a parent would see is broken.

  python3 scripts/verify/selfcheck.py data/site/sunnytime_db.json --site <arwhouse checkout>
"""
import argparse, collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--site", help="arwhouse checkout, to check that every photo has its thumbnail")
    a = ap.parse_args()
    d = json.load(open(a.db, encoding="utf-8"))
    N, M = d["names"], d["meta"]
    bad = []
    act = [p for p in d["p"] if p.get("st", "active") == "active"]
    ids = collections.Counter(p["id"] for p in d["p"])
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        bad.append(f"{len(dup)} setids appear twice, e.g. {dup[:3]}")
    if len(act) < 5000:
        bad.append(f"only {len(act)} active labels")
    if not str(d.get("rules_version", "")).startswith("v"):
        bad.append("rules_version missing")
    tiers = collections.Counter(p.get("ev") for p in act)
    if tiers.get(None):
        bad.append(f"{tiers[None]} active labels without an evidence tier")
    ph = re.compile(r"^\s*(please\b|refer to\b|see (the )?(artwork|label|package|carton)\b|scan (for|the)\b)", re.I)
    for p in act:
        names = [N[i] for i in p["i"]]
        if any(ph.search(x) for x in names):
            bad.append(f"placeholder shown as an ingredient: {p['id']}")
        if any(len(x) > 120 and x.count("(") != x.count(")") for x in names) or any(len(x) > 600 for x in names):
            bad.append(f"ingredient names run together (unbalanced bracket): {p['id']}")
        for f in p["v3"]:
            if f[0] not in M or not M[f[0]].get("l"):
                bad.append(f"warning {f[0]} has no label text (meta): {p['id']}")
        if not p.get("n"):
            bad.append(f"no product name: {p['id']}")
        if a.site and p.get("im") and not os.path.exists(os.path.join(a.site, "sunnytime/p", p["id"] + ".webp")):
            bad.append(f"photo without thumbnail: {p['id']}")
    # every correction file still parses
    for f in sorted(os.listdir(os.path.join(ROOT, "data/corrections"))):
        if f.endswith(".jsonl"):
            for k, l in enumerate(open(os.path.join(ROOT, "data/corrections", f), encoding="utf-8")):
                if l.strip():
                    try:
                        json.loads(l)
                    except ValueError:
                        bad.append(f"{f} line {k + 1} is not JSON")
                        break
    out = {"active": len(act), "tiers": dict(tiers), "with_photo": sum(1 for p in act if p.get("im")),
           "problems": len(bad)}
    print(json.dumps(out))
    seen = set()
    for b in bad:
        k = b.split(":")[0]
        if k not in seen:
            print("  " + b)
            seen.add(k)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
