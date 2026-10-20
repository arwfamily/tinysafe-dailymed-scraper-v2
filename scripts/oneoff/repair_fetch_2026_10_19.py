#!/usr/bin/env python3
"""One-off repair of the 2026-10-19 run (kept as the record of what was changed).

That run read ~470 labels without their SPL document (DailyMed rate limits): their
actives came back empty or their UNII-coded inactive table was replaced by openFDA
text. The snapshot step logged 249 'reformulated' events, almost all of them this
fetch failure, and 172 real sunscreens lost their actives and fell out of scope.

This applies the rule snapshot_and_history.carry_forward() now applies every week:
a label read worse than last time keeps its last good record (the 2026-10-12 raw
snapshot; for actives still missing, the last history entry that had them).
Formula events that only existed because of the bad read move from the history log
to data/history/fetch_degraded.jsonl.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
os.chdir(ROOT)
from classify import classify  # noqa: E402
from snapshot_and_history import (CANONICAL, FETCH_LOG, HISTORY, STATE, degraded,  # noqa: E402
                                  formulation_fingerprint, meta_view)

RUN, PREV = "2026-10-19", "2026-10-12"


def main():
    can = [json.loads(l) for l in open(CANONICAL, encoding="utf-8") if l.strip()]
    raw = {p["setid"]: p for p in json.load(open(f"data/raw/dailymed/{PREV}/master.json"))["products"]}
    hist = [json.loads(l) for l in open(HISTORY, encoding="utf-8") if l.strip()]
    last_acts = {}
    for h in hist:
        if h.get("active_ingredients") and h["observed_on"] < RUN:
            last_acts[h["setid"]] = h
    state = json.load(open(STATE, encoding="utf-8"))
    out, log, fixed = [], [], set()
    for c in can:
        sid = c["setid"]
        p = raw.get(sid)
        keep = None
        if degraded(c, p):
            keep = dict(p, first_seen=c.get("first_seen"), last_seen=c.get("last_seen"),
                        fetch_status="carried_forward", carried_since=RUN, carried_from=PREV)
            src = f"raw snapshot {PREV}"
        if not (keep or c).get("active_ingredients") and sid in last_acts:
            h = last_acts[sid]
            keep = dict(keep or c)
            keep["active_ingredients"] = h["active_ingredients"]
            if keep.get("inactive_source") != "spl_xml" and h.get("inactive_ingredients"):
                keep["inactive_ingredients"] = h["inactive_ingredients"]
                keep["inactive_source"] = "spl_xml"
            keep.update(classify(keep))
            keep.update(fetch_status="carried_forward", carried_since=RUN, carried_from=h["observed_on"])
            src = f"history entry {h['observed_on']}"
        if keep:
            keep["formulation_hash"] = formulation_fingerprint(keep)[0]
            fixed.add(sid)
            log.append({"observed_on": RUN, "setid": sid, "product_name": c.get("product_name"),
                        "this_run": {"inactive_source": c.get("inactive_source"),
                                     "n_actives": len(c.get("active_ingredients") or [])},
                        "action": "kept_last_good", "kept_record_from": src, "repair": "oneoff 2026-10-19"})
            st = state["setids"].get(sid) or {}
            fh, payload = formulation_fingerprint(keep)
            state["setids"][sid] = dict(st, formulation_hash=fh, payload=payload, meta=meta_view(keep))
            out.append(keep)
        else:
            out.append(c)
    # formula events of this run that came from the bad read
    keep_h, moved = [], 0
    for h in hist:
        if (h["observed_on"] == RUN and h["change"] == "reformulated" and not h.get("keys_added")
                and not h.get("keys_removed")):
            moved += 1                   # nothing changed in the formula: an event with no keys is a no-op
            continue
        if h["observed_on"] == RUN and h["setid"] in fixed and h["change"] in ("reformulated", "metadata"):
            new_hash = state["setids"][h["setid"]]["formulation_hash"]
            if h["change"] == "metadata" or h.get("previous_hash") == new_hash:
                moved += 1
                continue                 # the formula did not change; the read did
            h = dict(h, note="re-checked after the fetch repair: the formula still differs from the last good read")
        keep_h.append(h)
    with open(CANONICAL, "w", encoding="utf-8") as f:
        for r in sorted(out, key=lambda r: r["setid"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(HISTORY, "w", encoding="utf-8") as f:
        for h in keep_h:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")
    with open(FETCH_LOG, "a", encoding="utf-8") as f:
        for e in log:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    still = sum(1 for r in out if not r.get("active_ingredients"))
    print(f"repaired {len(fixed)} labels; {moved} history events moved to {FETCH_LOG}; "
          f"labels still without actives: {still}")


if __name__ == "__main__":
    main()
