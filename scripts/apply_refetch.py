#!/usr/bin/env python3
"""Apply a re-read (scripts/refetch_labels.py output) to canonical + history.

A label that was carried forward and is now read in full replaces its kept
record. If the formula differs from the last good read, that is logged as a
`reformulated` event (same confidence rule as the weekly snapshot); if it is
the same, nothing is logged. fetch_status becomes "read".

Usage: python3 scripts/apply_refetch.py REFETCH_DIR --date YYYY-MM-DD
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.chdir(ROOT)
from snapshot_and_history import (CANONICAL, FETCH_LOG, HISTORY, STATE, degraded, formulation_fingerprint,  # noqa: E402
                                  key_delta, meta_view)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    new = {}
    for line in open(os.path.join(a.dir, "records.jsonl"), encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            new[r["setid"]] = r
    can = [json.loads(l) for l in open(CANONICAL, encoding="utf-8") if l.strip()]
    state = json.load(open(STATE, encoding="utf-8"))
    events, log, applied, changed = [], [], 0, 0
    out = []
    for c in can:
        r = new.get(c["setid"])
        # only labels we are holding on last week's record; and only a read that is at
        # least as complete as that record (never a second bad read over a good one)
        if not r or c.get("fetch_status") != "carried_forward" or degraded(r, c):
            out.append(c)
            continue
        rec = dict(r, first_seen=c.get("first_seen"), last_seen=c.get("last_seen"), fetch_status="read",
                   refetched_on=a.date)
        rec.pop("found_by", None)
        rec["found_by"] = c.get("found_by")
        fh, payload = formulation_fingerprint(rec)
        prev = state["setids"].get(c["setid"]) or {}
        rec["formulation_hash"] = fh
        if prev.get("formulation_hash") and prev["formulation_hash"] != fh:
            added, removed = key_delta(prev.get("payload") or {}, payload)
            name_only = [k for k in added + removed if k.startswith("N:")]
            events.append({
                "observed_on": a.date, "setid": c["setid"], "change": "reformulated", "formulation_hash": fh,
                "previous_hash": prev["formulation_hash"], "keys_added": added, "keys_removed": removed,
                "confidence": "low" if name_only else "high",
                "confidence_reason": ("changed ingredients lack a UNII — may be a relabelling, verify against the raw "
                                      "snapshots before citing" if name_only else "all changed ingredients are UNII-identified"),
                "note": f"re-read on {a.date} after DailyMed failed to serve this label in the weekly run",
                "product_name": rec.get("product_name") or rec.get("title"), "dosage_form": rec.get("dosage_form"),
                "spf": rec.get("spf"), "active_ingredients": rec.get("active_ingredients"),
                "inactive_ingredients": rec.get("inactive_ingredients"), "fingerprint_payload": payload})
            changed += 1
        state["setids"][c["setid"]] = dict(prev, formulation_hash=fh, payload=payload, meta=meta_view(rec))
        log.append({"observed_on": a.date, "setid": c["setid"], "action": "re-read in full",
                    "formula_changed": bool(prev.get("formulation_hash") and prev["formulation_hash"] != fh)})
        out.append(rec)
        applied += 1
    with open(CANONICAL, "w", encoding="utf-8") as f:
        for r in sorted(out, key=lambda r: r["setid"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(HISTORY, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(FETCH_LOG, "a", encoding="utf-8") as f:
        for e in log:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    still = sum(1 for r in out if r.get("fetch_status") == "carried_forward")
    print(f"applied {applied} re-reads; {changed} formula changes logged; still carried forward: {still}")


if __name__ == "__main__":
    main()
