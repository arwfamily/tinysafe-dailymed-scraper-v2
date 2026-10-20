#!/usr/bin/env python3
"""Re-read named labels from DailyMed, one at a time (runs on GitHub Actions).

For labels the weekly run could not read (fetch_status carried_forward), so they
do not wait a week on last week's record. Same reader as the weekly scrape
(dailymed_scraper.process_setid). Output: refetch/records.jsonl, one scraper
record per label read in full; refetch/failed.json for the rest.

Usage: python scripts/refetch_labels.py --targets data/views/refetch_targets.json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dailymed_scraper as D  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", default="refetch")
    a = ap.parse_args()
    want = [t["setid"] for t in json.load(open(a.targets))]
    titles = {}
    for line in open(os.path.join(ROOT, "data/canonical/us_sunscreens.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r["setid"] in set(want):
            titles[r["setid"]] = r.get("title") or ""
    os.makedirs(a.out, exist_ok=True)
    done, left = {}, list(want)
    for rnd in range(1, 4):
        nxt = []
        for sid in left:
            time.sleep(1.0 * rnd)
            try:
                r = D.process_setid({"setid": sid, "title": titles.get(sid, ""), "found_by": "refetch"})
            except Exception as e:  # noqa: BLE001
                print("error", sid, e)
                r = None
            if r and r.get("spl_fetched") and r.get("active_ingredients"):
                done[sid] = r
            else:
                nxt.append(sid)
        print(f"round {rnd}: read {len(left) - len(nxt)}, still unread {len(nxt)}", flush=True)
        left = nxt
        if not left:
            break
        time.sleep(30 * rnd)
    with open(os.path.join(a.out, "records.jsonl"), "w", encoding="utf-8") as f:
        for r in done.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(left, open(os.path.join(a.out, "failed.json"), "w"))
    print(f"read {len(done)} of {len(want)}")


if __name__ == "__main__":
    main()
