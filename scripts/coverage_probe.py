#!/usr/bin/env python3
"""
scripts/coverage_probe.py — proof of completeness.
Reads every SPL listing in DailyMed (all marketing categories), keeps titles
that name a UV filter, SPF or sunscreen wording, and compares them with the
collected corpus. Writes data/reports/coverage_<date>.json:
  {spls_listed, pages_read, sunscreen_titled, in_corpus, missing: [...]}
`missing` must be empty after a full run.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dailymed_scraper as S  # noqa: E402

ROOT = os.path.dirname(HERE)
CANON = os.path.join(ROOT, "data", "canonical", "us_sunscreens.jsonl")


def main():
    rows = S.enumerate_all_spls(0)
    have = {json.loads(l)["setid"] for l in open(CANON, encoding="utf-8") if l.strip()}
    sun = {r["setid"]: r["title"] for r in rows if r["setid"] and S.SUN_TITLE.search(r["title"] or "")}
    missing = sorted(([s, t] for s, t in sun.items() if s not in have), key=lambda x: x[1])
    out = {"date": datetime.date.today().isoformat(), "spls_listed": len(rows),
           "unique_setids": len({r["setid"] for r in rows}), "sunscreen_titled": len(sun),
           "in_corpus": len(sun) - len(missing), "missing_count": len(missing), "missing": missing,
           "corpus_labels": len(have)}
    p = os.path.join(ROOT, "data", "reports", f"coverage_{out['date']}.json")
    json.dump(out, open(p, "w"), indent=1, ensure_ascii=False)
    print({k: v for k, v in out.items() if k != "missing"})


if __name__ == "__main__":
    main()
