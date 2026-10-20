#!/usr/bin/env python3
"""Labels that need reading this week -> data/verification/reading_queue.json

A label is queued when it is an active sunscreen with no ledger row for its
current spl_version: a new label, a label whose version changed, or a label
never checked. The fetch + read job (thin_check.yml today, the Claude API
reader in phase 2) works through this list; results go to the ledger.

  {generated, count, by_reason, labels: [{setid, spl_version, name, reason, had_older_check}]}
"""
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ledger as L  # noqa: E402
from us_master import MASTER  # noqa: E402

OUT = os.path.join(ROOT, "data/verification/reading_queue.json")


def main():
    led = L.load()
    q = []
    for line in open(MASTER, encoding="utf-8"):
        r = json.loads(line)
        if not r.get("in_scope") or r.get("status") != "active" or r.get("label_check"):
            continue
        older = bool(led.get(r["setid"]))
        q.append({"setid": r["setid"], "spl_version": r.get("spl_version"), "name": r.get("name"),
                  "reason": "label_changed" if older else "never_checked", "had_older_check": older})
    out = {"generated": datetime.date.today().isoformat(), "count": len(q),
           "by_reason": dict(collections.Counter(x["reason"] for x in q)), "labels": q}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"reading queue: {len(q)} labels", out["by_reason"])


if __name__ == "__main__":
    main()
