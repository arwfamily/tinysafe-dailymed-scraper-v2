#!/usr/bin/env python3
"""Verification ledger: every check of a label's inactive list, keyed by
(setid, spl_version).

data/verification/ledger.jsonl, one row per check, append-only:

  {setid, spl_version, checked, status, source, inactives?, note?, readings?}

status (what the check found):
  confirmed               the list was read from the label (text, or images read twice) and is final
  partial                 read twice; only illegible words left out
  text_confirms_current   the label text holds nothing the list lacks
  no_list_on_label_images neither the SPL text nor the label images print a list
  image_unreadable        the label images are too poor to read
  label_image_mismatch    DailyMed shows another product's label
  non_english_label       label printed only in Korean/CJK; the English filing is kept
  spl_not_on_dailymed     the SPL is gone from DailyMed
  needs_review            the two readings disagree; nothing applied

Rule: a row applies only while the label's spl_version equals the row's. When
the label changes, older rows stop applying (they stay as history) and the
label goes back to the reading queue. For one (setid, version) the LAST row
in the file wins, so a newer check overrides an older one.

Usage (one-off migration of the 2026-10-19 checks):
  python3 scripts/ledger.py migrate THIN_FETCH_DIR
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data/verification/ledger.jsonl")
APPLIES = {"confirmed", "partial"}            # statuses that replace the printed list
KNOWN = {"confirmed", "partial", "text_confirms_current", "no_list_on_label_images", "image_unreadable",
         "label_image_mismatch", "non_english_label", "spl_not_on_dailymed", "needs_review"}


def load(path=LEDGER):
    """{setid: {spl_version: row}} — the last row per (setid, version)."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        out.setdefault(r["setid"], {})[str(r.get("spl_version"))] = r
    return out


def current(ledger, setid, spl_version):
    """The check that applies to this label version, or None."""
    return (ledger.get(setid) or {}).get(str(spl_version))


def stale(ledger, setid, spl_version):
    """Checks of this label made on an older version (history, not applied)."""
    return [r for v, r in (ledger.get(setid) or {}).items() if v != str(spl_version)]


def append(rows, path=LEDGER):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            assert r["status"] in KNOWN, r["status"]
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _row(r, version, origin):
    keep = {"setid": r["setid"], "spl_version": str(version), "checked": r.get("checked", "2026-10-19"),
            "status": r["status"], "source": r.get("source", ""), "origin": origin}
    for k in ("inactives", "note", "legibility", "one_reader_only", "kept_db_items", "added"):
        if r.get(k):
            keep[k] = r[k]
    return keep


def migrate(thin_fetch_dir):
    canon = {}
    for line in open(os.path.join(ROOT, "data/canonical/us_sunscreens.jsonl"), encoding="utf-8"):
        c = json.loads(line)
        canon[c["setid"]] = c.get("spl_version")
    thin_v = {}
    for f in glob.glob(os.path.join(thin_fetch_dir, "*.json")):
        r = json.load(open(f, encoding="utf-8"))
        thin_v[r["setid"]] = r.get("spl_version")
    thin = {}
    for line in open(os.path.join(ROOT, "data/corrections/thin_check_2026-10-19.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        thin[r["setid"]] = r
    full = {}
    for line in open(os.path.join(ROOT, "data/corrections/full_check_2026-10-19.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        full[r["setid"]] = r
    rows = []
    for sid in sorted(set(thin) | set(full)):
        t, f = thin.get(sid), full.get(sid)
        if t and t["status"] not in KNOWN:          # "unconfirmed": two readings disagreed
            t = dict(t, status="needs_review")
        if f and f["status"] not in KNOWN:          # unresolved_*: covered by the thin check, or nothing found
            f = None
        tv = thin_v.get(sid) or canon.get(sid)
        fv = (f or {}).get("spl_version") or canon.get(sid)
        t_row = _row(t, tv, "thin_check_2026-10-19") if t else None
        f_row = _row(f, fv, "full_check_2026-10-19") if f else None
        # same precedence sunnytime_db.py used: a confirmed thin check stands unless the full
        # check read the label twice where the thin check only had the label text
        full_wins = f is not None and (t is None or t["status"] not in APPLIES or (
            f["status"] in APPLIES and "two_reads" in f.get("source", "") and t.get("source") == "label_text"))
        order = [t_row, f_row] if full_wins else [f_row, t_row]
        rows += [r for r in order if r]
    if os.path.exists(LEDGER):
        os.remove(LEDGER)
    append(rows)
    led = load()
    print(f"wrote {len(rows)} rows for {len(led)} labels -> {LEDGER}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "migrate":
        migrate(sys.argv[2])
    else:
        print(__doc__)
