#!/usr/bin/env python3
"""Check queued labels against their current DailyMed text and write the ledger.

Input : a fetch directory from thin_check_fetch.py (one JSON per setid, with
        inactive_section / ingredient_passages, spl_version, images)
        data/master/us_master.jsonl (the list each label shows today)
Output: ledger rows (data/verification/ledger.jsonl) for every label the text settles:
          text_confirms_current  the text parses cleanly and holds nothing the list lacks
          confirmed (spl_text)   the text parses cleanly and adds items: the text list becomes the printed list
          spl_not_on_dailymed    DailyMed answered 404
        data/verification/needs_reading.json for the rest (run-together or garbled text,
        no text, doubtful items): these are read twice (label text or label images).

Usage: python3 scripts/queue_text_check.py FETCH_DIR
"""
import collections
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import full_check_text as F  # noqa: E402
import inactive_union as U  # noqa: E402
import ledger as L  # noqa: E402
from us_master import MASTER, akeys_of  # noqa: E402

NEEDS = os.path.join(ROOT, "data/verification/needs_reading.json")


def vocab(master):
    names = set()
    for r in master.values():
        names |= set(r.get("inactives") or [])
    keys = {U.key(n) for n in names}
    words = collections.Counter(w for n in names for w in re.sub(r"[^A-Z0-9]+", " ", n.upper()).split())
    return keys, words


def known(x, keys, words):
    if U.key(x) in keys:
        return True
    ws = [w for w in re.sub(r"[^A-Z0-9]+", " ", re.sub(r"\(.*?\)", "", x).upper()).split() if len(w) >= 3]
    return bool(ws) and all(words[w] >= 3 for w in ws) and len(ws) <= 8


def main():
    fetch_dir = sys.argv[1]
    master = {}
    for line in open(MASTER, encoding="utf-8"):
        r = json.loads(line)
        master[r["setid"]] = r
    keys, words = vocab(master)
    today = datetime.date.today().isoformat()
    rows, needs, c = [], [], collections.Counter()
    for f in sorted(glob.glob(os.path.join(fetch_dir, "*.json"))):
        r = json.load(open(f, encoding="utf-8"))
        sid = r["setid"]
        m = master.get(sid)
        if not m:
            continue
        ver = r.get("spl_version") or m.get("spl_version")
        base = {"setid": sid, "spl_version": str(ver), "checked": today, "origin": "weekly_text_check"}
        raw = F.pick_text(r)
        if r.get("error") and "404" in r["error"] and not raw:
            rows.append(dict(base, status="spl_not_on_dailymed", source="dailymed_api"))
            c["spl_not_on_dailymed"] += 1
            continue
        if r.get("error") and not raw:
            c["fetch_error"] += 1                      # stays in the queue; retried next week
            continue
        images = [i["file"] for i in r.get("images") or [] if i.get("file")]
        item = {"setid": sid, "spl_version": ver, "name": m.get("name"),
                "actives": [a["name"] for a in m.get("actives") or []],
                "db_list": m.get("inactives") or [], "images": images}
        if len(re.findall(r"[A-Za-z]{3,}", raw)) < 2:
            needs.append(dict(item, mode="image", why="no_text"))
            c["needs_image"] += 1
            continue
        ak = akeys_of(m.get("actives") or [])
        t, items = F.parse(r, ak)
        if not F.clean_ok(items) or U._unreadable(items):
            needs.append(dict(item, mode="text", why="unsplittable_or_garbled", label_text=t[:6000]))
            c["needs_text_reading"] += 1
            continue
        cur = m.get("inactives") or []
        added = [x for x in items if not any(U.same(x, y) for y in cur)]
        if any(not known(x, keys, words) for x in added):
            needs.append(dict(item, mode="text", why="doubtful_items", label_text=t[:6000], parsed=items))
            c["needs_text_reading"] += 1
            continue
        if added:
            rows.append(dict(base, status="confirmed", source="spl_text", inactives=items, added=added))
            c["confirmed_from_text"] += 1
        else:
            rows.append(dict(base, status="text_confirms_current", source="spl_text"))
            c["text_confirms_current"] += 1
    L.append(rows)
    json.dump({"generated": today, "count": len(needs), "labels": needs},
              open(NEEDS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(dict(c), f"-> {len(rows)} ledger rows, {len(needs)} need reading")


if __name__ == "__main__":
    main()
