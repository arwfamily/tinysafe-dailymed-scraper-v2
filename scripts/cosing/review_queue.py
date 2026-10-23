#!/usr/bin/env python3
"""This week's ingredient-dictionary review queue: label names on active in-scope
labels that no review covers yet.

  names.json  names that match nothing (two reads must identify them)
  jobs.json   CosIng ingredients whose main job comes only from the CosIng rule
              (two reads must decide it), with the functions CosIng lists
Usage: review_queue.py <out dir>   (prints the counts)
The weekly review (scheduled task) reads both, two independent readers each,
merges them with tools/merge_two_reads.py and saves the accepted results as
data/reference/cosing/weekly/{names,jobs}_<date>.json.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import dictionary as D  # noqa: E402


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    use = collections.Counter()
    for line in open(os.path.join(ROOT, "data/releases/us/latest/us_all.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("status") == "active":
            for n in set(r.get("inactives") or []):
                use[n] += 1
    d = D.build(list(use))
    names = [n for n, _ in use.most_common() if d[n]["src"] == "none"]
    jobs = collections.Counter()
    fn = {}
    for n, u in use.items():
        e = d[n]
        if e["src"] == "cosing" and e.get("inci"):
            jobs[e["inci"]] += u
            fn[e["inci"]] = e.get("fn") or []
    json.dump(names, open(os.path.join(out, "names.json"), "w"), ensure_ascii=False, indent=0)
    json.dump([{"inci": k, "labels": c, "cosing_functions": fn[k]} for k, c in jobs.most_common()],
              open(os.path.join(out, "jobs.json"), "w"), indent=0)
    print(json.dumps({"names": len(names), "jobs": len(jobs)}))


if __name__ == "__main__":
    main()
