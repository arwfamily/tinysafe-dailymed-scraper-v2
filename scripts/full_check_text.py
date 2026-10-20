#!/usr/bin/env python3
"""Re-read every label's printed inactive list from the current DailyMed SPL text
(fetched by thin_check_fetch.py --no-images into the full-check-text branch) and
write data/corrections/full_check_text_2026-10-19.jsonl:

  {setid, checked, status, source, inactives, n_old_text, n_fresh, added, note}

status:
  fresh_text     the SPL's inactive-ingredient text parsed cleanly; `inactives`
                 is that list (label order), used as the printed list
  same_as_db     parsed cleanly and nothing on it is missing from the DB list
  unsplittable   text present but run together with no separators -> needs the
                 label image
  no_text        the SPL has no inactive-ingredient text -> needs the label image
  fetch_error    DailyMed request failed

Usage: full_check_text.py FETCH_DIR DB_JSON
"""
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inactive_union as U  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data/corrections/full_check_text_2026-10-19.jsonl")
_SPANISH = re.compile(r"\b(ingredientes|agua|aceite|extracto|inactivos|alcohol desnaturalizado|octocrileno)\b", re.I)
_FRENCH = re.compile(r"\b(ingrédients|non m[ée]dicinaux|huile|cire d'abeille)\b", re.I)
_CUT = re.compile(r"\s(?:distributed|manufactured|mfd\.?|made in|questions\??|www\.|marketed by|dist\. by|"
                  r"for external use|warnings?:|directions:|other information|keep out of)\b.*$", re.I)


def pick_text(r):
    secs = [s.strip() for s in (r.get("inactive_section") or "").split(" | ") if s.strip()]
    if not secs:
        secs = [p["text"] for p in r.get("ingredient_passages") or []]
    eng = [s for s in secs if not _SPANISH.search(s) and not _FRENCH.search(s)] or secs[:1]
    return max(eng, key=len) if eng else ""


def norm_text(t):
    t = re.sub(r"^\s*(?:(?:inactive|other|non-?medicinal)\s+)?ingredients?\s*[:：.]?\s*", "", t, flags=re.I)
    t = _CUT.sub("", t)
    t = t.replace("，", ",").replace("、", ",").replace("；", ";")
    t = re.sub(r"\s*\[\s*\]\s*", ", ", t)                 # "WATER [] GLYCERIN"
    if t.count(",") < 3:                                 # "AQUA - GLYCERIN - ..." (no commas at all);
        t = re.sub(r"\s+[-–—]\s+", ", ", t)              # with commas, "Polyglyceryl – 3 ..." is one name
    t = re.sub(r"\s*\|\s*", ", ", t)
    t = re.sub(r"\s\*\s?", ", ", t)                      # "Water * Glycerin"
    return t


def parse(r, akeys):
    t = norm_text(pick_text(r))
    items = [x for x in U.resplit([t]) if x.strip()]
    items = [x for x in items if not U.is_active(x, akeys) and not re.search(r"\d+(\.\d+)?\s*%", x)]
    out = []
    for x in items:
        x = re.sub(r"\s*\(\s*\d\s*\)\s*$", "", x).strip(" .*†")
        if x and not any(U.key(x) == U.key(o) for o in out):
            out.append(x)
    return t, out


def clean_ok(items):
    if len(items) < 2:
        return False
    w = [len(x.split()) for x in items]
    return max(w) <= 14 and sum(w) / len(w) <= 6


def main():
    fetch_dir, dbp = sys.argv[1], sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else OUT
    db = json.load(open(dbp, encoding="utf-8"))
    P = {p["id"]: p for p in db["p"]}
    c = collections.Counter()
    rows = []
    for f in sorted(glob.glob(os.path.join(fetch_dir, "*.json"))):
        r = json.load(open(f, encoding="utf-8"))
        sid = r["setid"]
        p = P.get(sid)
        if not p:
            continue
        akeys = set()
        for z in p["z"]:
            k = U.key(z[0]); akeys.add(k); akeys |= U._ACTIVE_SYN.get(k, set())
        cur = [db["names"][i] for i in p["i"]]
        row = {"setid": sid, "title": r.get("title", "")[:120], "checked": "2026-10-19",
               "source": "spl_text", "spl_version": r.get("spl_version")}
        raw = pick_text(r)
        if r.get("error") and not raw:
            row.update(status="fetch_error", note=r["error"][:200])
        elif len(re.findall(r"[A-Za-z]{3,}", raw)) < 2:
            row.update(status="no_text")
        else:
            t, items = parse(r, akeys)
            if not clean_ok(items):
                row.update(status="unsplittable", raw=t[:3000], inactives=items)
            else:
                added = [x for x in items if not any(U.same(x, y) for y in cur)]
                row.update(status="fresh_text" if added else "same_as_db", inactives=items,
                           n_fresh=len(items), n_db=len(cur), added=added)
        c[row["status"]] += 1
        rows.append(row)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(dict(c), "->", out_path)


if __name__ == "__main__":
    main()
