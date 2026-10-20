#!/usr/bin/env python3
"""Cut this week's three US releases from the master.

    data/releases/us/latest/us_all.jsonl        every sunscreen label (active + discontinued)
    data/releases/us/latest/us_mineral.jsonl    labels with zinc oxide / titanium dioxide actives, hybrids included
    data/releases/us/latest/us_baby_kids.jsonl  labels whose name says baby / kids / children ...
    data/releases/us/latest/manifest.json       what this release is (id, counts, checksums)
    data/releases/us/manifest_history.jsonl     one manifest per release, append-only

The three files are views of ONE master (data/master/us_master.jsonl); a label
in two views is the same record in both. Older releases are recovered from the
git tag `us-data-<date>`, not kept as files.

Usage: python3 scripts/us_release.py --run-date YYYY-MM-DD
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from us_master import MASTER, RULES_VERSION, SCHEMA_VERSION  # noqa: E402

OUT = os.path.join(ROOT, "data/releases/us/latest")
HISTORY = os.path.join(ROOT, "data/releases/us/manifest_history.jsonl")
VIEWS = {
    "us_all": lambda r: True,
    "us_mineral": lambda r: r.get("is_mineral"),
    "us_baby_kids": lambda r: r.get("is_baby_kids"),
}
DEFINITIONS = {
    "us_all": "Every label FDA DailyMed lists as a sunscreen drug. Out of scope, with the reason recorded in the "
              "master: SPF makeup (BB/CC creams, foundations, cushions, concealers, makeup powders, and primers or "
              "setting products not named as sunscreens; scripts/scope_rules.py), SPF lip products, diaper creams, "
              "calamine, and zinc-oxide products with no sun claim. Tinted sunscreens and tinted moisturizers are "
              "sunscreens. Labels that left DailyMed stay, with status 'discontinued'. A label DailyMed failed to "
              "serve this week keeps its last fully read record (fetch_status 'carried_forward').",
    "us_mineral": "Labels whose declared actives include zinc oxide or titanium dioxide, adult and baby, "
                  "hybrids included. filter_type gives the main filter by summed w/w % on the Drug Facts panel. "
                  "Actives follow the printed Drug Facts where the FDA filing contradicts it "
                  "(data/corrections/spl_label_errors.jsonl).",
    "us_baby_kids": "Baby and kids sunscreens: the reviewed decisions in claims/baby_decisions.csv (the population "
                    "the arwhouse.com/evidence pages count), then, for labels not yet reviewed, the rule: the product "
                    "name (not the labeler) or the label's front panel says baby, infant, toddler, kids, children, "
                    "junior or little ones. Any filter type. baby_kids_basis says which.",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stats(rows):
    c = {"labels": len(rows)}
    c["status"] = dict(collections.Counter(r.get("status") for r in rows))
    c["filter_type"] = dict(collections.Counter(r.get("filter_type") for r in rows if r.get("status") == "active"))
    act = [r for r in rows if r.get("status") == "active"]
    lc = collections.Counter(r.get("label_check") or "not_checked_yet" for r in act)
    c["label_check"] = dict(lc)
    checked = sum(v for k, v in lc.items() if k in ("confirmed", "partial", "text_confirms_current"))
    c["label_verified_share"] = round(checked / len(act), 4) if act else None
    c["inactives_7_or_fewer"] = sum(1 for r in act if r.get("thin"))
    c["recalls"] = {
        "labels_matched": sum(1 for r in rows if any(x["status"] == "matched" for x in r.get("recalls") or [])),
        "labels_needs_review": sum(1 for r in rows if any(x["status"] == "needs_review" for x in r.get("recalls") or [])),
    }
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    master = [json.loads(x) for x in open(MASTER, encoding="utf-8") if x.strip()]
    scope = [r for r in master if r.get("in_scope")]
    os.makedirs(OUT, exist_ok=True)
    files, counts = {}, {}
    for name, keep in VIEWS.items():
        rows = [r for r in scope if keep(r)]
        path = os.path.join(OUT, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        files[name + ".jsonl"] = {"rows": len(rows), "sha256": sha256(path)}
        counts[name] = stats(rows)
    # what the master leaves out, and why: downstream collectors (global-sunscreen)
    # use it so every copy of the US data has the same scope
    out_path = os.path.join(OUT, "us_out_of_scope.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for r in master:
            if not r.get("in_scope"):
                f.write(json.dumps({"setid": r["setid"], "name": r.get("name"), "title": r.get("title"),
                                    "excluded_reason": r.get("excluded_reason"),
                                    "scope_override": r.get("scope_override")}, ensure_ascii=False) + "\n")
    files["us_out_of_scope.jsonl"] = {"rows": sum(1 for r in master if not r.get("in_scope")), "sha256": sha256(out_path)}
    manifest = {
        "release_id": f"us-{a.run_date}",
        "git_tag": f"us-data-{a.run_date}",
        "released": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
        "rules_version": RULES_VERSION,
        "source": {"register": "FDA DailyMed (SPL)", "collected": a.run_date,
                   "scraper_commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID")},
        "definitions": DEFINITIONS,
        "counts": counts,
        "out_of_scope": dict(collections.Counter(r.get("excluded_reason") for r in master if not r.get("in_scope"))),
        "files": files,
    }
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    # one manifest per release id: a rerun on the same day replaces that day's line
    hist = [json.loads(x) for x in open(HISTORY, encoding="utf-8")] if os.path.exists(HISTORY) else []
    hist = [h for h in hist if h.get("release_id") != manifest["release_id"]] + [manifest]
    with open(HISTORY, "w", encoding="utf-8") as f:
        for h in hist:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")
    print(json.dumps({k: {"labels": v["labels"], "verified": v["label_verified_share"]} for k, v in counts.items()}))


if __name__ == "__main__":
    main()
