#!/usr/bin/env python3
"""Merge two independent readings (A/B) of the same items.
  kind=inci: agree on kind and (INCI or plant), both found -> accepted; else review
  kind=job : agree on main job -> accepted (low if either low); else review
Usage: merge_two_reads.py inci|job OUT.json A0 B0 [A1 B1 ...]"""
import json, re, sys


def fold(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    mode, out, files = sys.argv[1], sys.argv[2], sys.argv[3:]
    acc, rev = {}, {}
    for fa, fb in zip(files[0::2], files[1::2]):
        A, B = json.load(open(fa)), json.load(open(fb))
        kA = "name" if mode == "inci" else "inci"
        bmap = {x[kA]: x for x in B}
        for a in A:
            b = bmap.get(a[kA])
            if b is None:
                rev[a[kA]] = {"A": a, "B": None}
                continue
            if mode == "inci":
                same = a["kind"] == b["kind"] and (
                    (a["kind"] == "INCI" and fold(a["inci"]) == fold(b["inci"])) or
                    (a["kind"] == "PLANT" and fold((a.get("plant") or "").split()[0] if a.get("plant") else "") ==
                     fold((b.get("plant") or "").split()[0] if b.get("plant") else "")) or
                    (a["kind"] == "NO_COSING" and a.get("category") == b.get("category")) or
                    a["kind"] == "NOT_INGREDIENT")
            else:
                same = a["job"] == b["job"]
            if same:
                conf = "high" if a.get("confidence") == b.get("confidence") == "high" else "low"
                acc[a[kA]] = dict(a, confidence=conf, read_b=b)
            else:
                rev[a[kA]] = {"A": a, "B": b}
    json.dump({"accepted": acc, "review": rev}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"accepted {len(acc)} (low {sum(1 for v in acc.values() if v['confidence'] == 'low')}), review {len(rev)}")


if __name__ == "__main__":
    main()
