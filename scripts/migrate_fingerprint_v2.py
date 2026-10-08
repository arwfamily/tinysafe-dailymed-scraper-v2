#!/usr/bin/env python3
"""
One-off, idempotent: move canonical + state from fingerprint v1 to v2
(see FINGERPRINT_VERSION in snapshot_and_history.py). Canonical holds the
last observed formula of every live setid, so its v2 hash is exact.
Writes no history events: the hash recipe changed, not any product.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snapshot_and_history import (CANONICAL, STATE, FINGERPRINT_VERSION,
                                  formulation_fingerprint, load_state)

def main():
    recs = [json.loads(l) for l in open(CANONICAL, encoding="utf-8") if l.strip()]
    state = load_state(STATE)
    changed = 0
    for r in recs:
        h, payload = formulation_fingerprint(r)
        if r.get("formulation_hash") != h:
            changed += 1
        r["formulation_hash"] = h
        st = state["setids"].get(r["setid"])
        if st is not None:
            st.update({"formulation_hash": h, "payload": payload, "fingerprint_version": FINGERPRINT_VERSION})
    with open(CANONICAL, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    live = {r["setid"] for r in recs}
    print(f"rehashed {len(recs)} canonical records ({changed} hash values changed); "
          f"{sum(1 for k in state['setids'] if k not in live)} delisted state entries left on v1")

if __name__ == "__main__":
    main()
