#!/usr/bin/env python3
"""Quality gate between last week's site db.json and this week's.

A failed gate stops the publish; last week's data stays on the site.

  1. active labels must not drop by more than 2% (a DailyMed outage looks like mass delisting)
  2. a label whose version did not change must not lose an inactive ingredient
  3. ... nor a flag
  4. hand-checked anchor labels (data/reference/gate_anchors.json) keep their count while unchanged
  5. every label with 7 or fewer inactives carries a reason
  6. every record has the fields and types the site reads (docs/SITE_DATA_CONTRACT.md)

Checks 2-3 need the label version on both sides; the first build after the
switch (old db without versions) reports them without failing.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from inactive_union import same_display  # noqa: E402

ANCHORS = os.path.join(ROOT, "data/reference/gate_anchors.json")
MAX_DROP = 0.02
REQUIRED = {"id": str, "n": str, "i": list, "v3": list, "z": list, "r": list, "thin": bool, "st": str}


def check(old, new):
    problems, report = [], {}
    act_new = [p for p in new["p"] if p.get("st", "active") == "active"]
    report["active_labels"] = len(act_new)
    for p in new["p"]:
        for k, t in REQUIRED.items():
            if not isinstance(p.get(k), t):
                problems.append(f"contract: {p.get('id')} field {k} missing or not {t.__name__}")
                break
        if p.get("thin") and not p.get("thin_reason"):
            problems.append(f"thin without a reason: {p['id']}")
    anchors = json.load(open(ANCHORS, encoding="utf-8"))["anchors"] if os.path.exists(ANCHORS) else []
    by_id = {p["id"]: p for p in new["p"]}
    for a in anchors:
        p = by_id.get(a["setid"])
        if p and str(p.get("v")) == str(a["spl_version"]) and len(p["i"]) != a["inactives_n"]:
            problems.append(f"anchor {a['name']}: {len(p['i'])} inactives, expected {a['inactives_n']}")
    if old:
        act_old = [p for p in old["p"] if p.get("st", "active") == "active"]
        report["active_labels_before"] = len(act_old)
        if act_old and len(act_new) < len(act_old) * (1 - MAX_DROP):
            problems.append(f"active labels fell {len(act_old)} -> {len(act_new)} (> {MAX_DROP:.0%})")
        versioned = all("v" in p for p in old["p"])
        o_by = {p["id"]: p for p in old["p"]}
        lost_i = lost_f = 0
        examples = []
        for p in new["p"]:
            q = o_by.get(p["id"])
            if not q or (versioned and str(q.get("v")) != str(p.get("v"))):
                continue
            on = [old["names"][i] for i in q["i"]]
            nn = [new["names"][i] for i in p["i"]]
            nset = set(nn)
            gone = [x for x in on if x not in nset
                    and not any(same_display(x, y) or same_display(y, x) for y in nn)]
            fl = {f[0] for f in q["v3"]} - {f[0] for f in p["v3"]}
            if gone:
                lost_i += 1
                if len(examples) < 10:
                    examples.append({"id": p["id"], "lost_inactives": gone[:4]})
            if fl:
                lost_f += 1
                if len(examples) < 10:
                    examples.append({"id": p["id"], "lost_flags": sorted(fl)})
        report.update({"unchanged_labels_losing_inactives": lost_i, "unchanged_labels_losing_flags": lost_f,
                       "examples": examples, "versions_on_both_sides": versioned})
        if versioned and (lost_i or lost_f):
            problems.append(f"{lost_i} unchanged labels lost inactives, {lost_f} lost flags")
    return problems, report


if __name__ == "__main__":
    old = json.load(open(sys.argv[1], encoding="utf-8"))
    new = json.load(open(sys.argv[2], encoding="utf-8"))
    pr, rep = check(old, new)
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if pr:
        print("FAILED:\n  " + "\n  ".join(pr))
        sys.exit(2)
