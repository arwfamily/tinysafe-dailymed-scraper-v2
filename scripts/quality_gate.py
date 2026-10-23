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

Reviewed changes are not failures: a label taken out of scope by a recorded rule
or override (scope_rules.py, scope_overrides.json) does not count toward the drop,
and a label whose actives were corrected or whose last good read was kept after a
failed fetch may change its list. The caller passes these as `explained`
{setid: reason}; the report lists how many of each were used.
"""
import re
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


# Reviewed rule changes that remove a flag on purpose. A lost flag is explained
# only when every name the old flag cited is one the new rule no longer counts.
SYNTHETIC = re.compile(r"\bSYNTHETIC\b", re.I)
RETIRED = {   # flag -> the cited names that no longer give it (rules v3.3, 2026-10-22)
    "propolis_beeswax": SYNTHETIC, "animal_derived": SYNTHETIC, "lanolin": SYNTHETIC,
    "essential_oil": re.compile(r"^(?!.*\b(OIL|OLEUM)\b)|\b(SEED|KERNEL|NUT|BRAN|GERM)\b.*\bOIL\b|"
                                r"\bROSA\s+(MOSCHATA|CANINA|RUBIGINOSA)\b(?!.*FLOWER)", re.I),  # extracts, waters; fixed seed oils (v3.6); rosehip (v3.7)
    "asteraceae": re.compile(r"PINASTER", re.I),          # pine bark matched "ASTER" (v3.7)
    # a silicone grade filed with its cyclopentasiloxane carrier, printed as dimethicone (v3.7)
    "d5_d6": re.compile(r"^(?!.*(CYCLO|SILOXANE|METHICONE\b(?<!DIMETHICONE))).*DIMETHICONE", re.I),
    "wheat": re.compile(r"\b(CORN|MAIZE|ZEA MAYS)\b.*GLUTEN", re.I),   # corn gluten is not wheat (v3.5)
    "propylene_glycol": re.compile(r"PROPYLENE ?GLY ?COL[ -]*(?:[A-Z]+ATE|MONO|DI[A-Z]+|ALGINATE|ESTER)", re.I),  # its esters (v3.6)
}
# product-level flags whose rule changed on purpose (rules v3.6, 2026-10-23 label audit):
# a spray needs a spray filing or spray wording on a label that is not a stick/cream/roll-on;
# "water-based" needs water among the main ingredients
RETIRED_PRODUCT = {"spray_powder", "no_preservative_water_base", "talc_inhalable"}


def rule_retired(flag, old_flags):
    if flag in RETIRED_PRODUCT:
        return True
    rx = RETIRED.get(flag)
    ev = next((f[1] for f in old_flags if f[0] == flag), None)
    return bool(rx and ev and all(rx.search(n) for n in ev))


def check(old, new, explained=None):
    explained = explained or {}
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
        new_ids = {p["id"] for p in act_new}
        gone_ids = [p["id"] for p in act_old if p["id"] not in new_ids]
        expl = [i for i in gone_ids if str(explained.get(i, "")).startswith("scope:")]
        report["left_by_reviewed_scope_rule"] = len(expl)
        base = len(act_old) - len(expl)
        if act_old and len(act_new) < base * (1 - MAX_DROP):
            problems.append(f"active labels fell {base} -> {len(act_new)} (> {MAX_DROP:.0%}; "
                            f"{len(expl)} more left by reviewed scope rules)")
        versioned = all("v" in p for p in old["p"])
        o_by = {p["id"]: p for p in old["p"]}
        lost_i = lost_f = 0
        examples = []
        for p in new["p"]:
            q = o_by.get(p["id"])
            if not q or (versioned and str(q.get("v")) != str(p.get("v"))):
                continue
            printed_only = explained.get(p["id"]) == "printed_list_only"
            if p["id"] in explained and not str(explained[p["id"]]).startswith("scope:") and not printed_only:
                continue                                   # reviewed correction / kept last good read
            on = [old["names"][i] for i in q["i"]]
            nn = [new["names"][i] for i in p["i"]]
            nset = set(nn)
            gone = [x for x in on if x not in nset
                    and not any(same_display(x, y) or same_display(y, x) for y in nn)]
            fl = {f[0] for f in q["v3"]} - {f[0] for f in p["v3"]}
            fl = {f for f in fl if not rule_retired(f, q["v3"])}
            if p.get("mp"):
                # several products in one filing: one product's fragrance-free claim is not a
                # conflict with another's fragrance (rules v3.6)
                fl.discard("fragrance_free_conflict")
            if printed_only:
                # only the printed list is shown (and flagged): names the FDA filing alone
                # had are dropped on purpose; a flag cited from a printed name may not go
                from us_master import strict_twin, SOURCE_FLAGS

                def on_label(n, f):
                    # the same ingredient in the same form (a filed rose OIL is not the printed
                    # rose WATER); for what-it-is-made-from flags, any form
                    rel = (lambda a, b: same_display(a, b) or same_display(b, a)) if f in SOURCE_FLAGS else strict_twin
                    return any(n == y or rel(n, y) for y in nn)
                fl = {f for f in fl if any(on_label(n, f) for g in q["v3"] if g[0] == f for n in g[1])}
                gone = [x for x in gone if x in on[:q.get("i_text_n") or 0]] if q.get("i_text_n") else gone
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
