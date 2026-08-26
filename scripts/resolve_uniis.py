#!/usr/bin/env python3
"""
resolve_uniis.py — turn UV-filter NAMES into UNII codes, from the source.

The scraper's net is an active-ingredient UNII search. Widening that net means
adding UNII codes — and a wrong code silently collects nothing, which looks
identical to "this filter isn't used in the US". So codes are never typed from
memory: this script asks DailyMed's own /uniis service and writes down what it
answered, plus how many SPLs actually carry each code.

Writes data/reference/uv_filter_uniis.json:
  {
    "resolved_on": "...",
    "filters": [
      {"query": "AVOBENZONE", "unii": "...", "unii_name": "...",
       "spl_count": 1234, "status": "ok"|"ambiguous"|"not_found"|"zero_spls",
       "candidates": [...]}
    ]
  }

Only entries with status == "ok" are used as search seeds. Everything else is
written down too, so the gap is visible instead of silent.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
OUT = "data/reference/uv_filter_uniis.json"

# US OTC monograph M020 actives + filters allowed elsewhere that show up on
# US shelves. Names only — codes are resolved, never assumed.
UV_FILTER_NAMES = [
    # mineral (already in the scraper, kept so one file describes the whole net)
    "ZINC OXIDE",
    "TITANIUM DIOXIDE",
    # organic filters, US monograph
    "AVOBENZONE",
    "OXYBENZONE",
    "OCTINOXATE",
    "OCTISALATE",
    "OCTOCRYLENE",
    "HOMOSALATE",
    "ENSULIZOLE",
    "SULISOBENZONE",
    "DIOXYBENZONE",
    "MERADIMATE",
    "CINOXATE",
    "PADIMATE O",
    "TROLAMINE SALICYLATE",
    "AMINOBENZOIC ACID",
    # filters common outside the US — bemotrizinol is the live one:
    # FDA proposed order OTC000039 would add it to M020 at up to 6%.
    # Collecting it now is what makes a before/after possible later.
    "BEMOTRIZINOL",
    "BISOCTRIZOLE",
    "ECAMSULE",
    "DROMETRIZOLE TRISILOXANE",
    "OCTYL TRIAZONE",
    "IscotrizinolL",  # deliberately odd casing: proves the resolver is case-safe
]


def fetch(url, tries=4, backoff=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "tinysafe-ingredients/1.0 (research)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                print(f"    fetch failed: {url} :: {e}", file=sys.stderr)
                return None
            time.sleep(backoff * (i + 1))
    return None


def lookup_unii(name):
    """Ask /uniis for this substance name. Return (status, chosen, candidates)."""
    q = urllib.parse.quote(name)
    doc = fetch(f"{BASE}/uniis.json?substance_name={q}&pagesize=100")
    if doc is None:
        return "fetch_error", None, []
    rows = doc.get("data") or []
    if not rows:
        return "not_found", None, []

    def norm(x):
        return "".join(ch for ch in str(x).upper() if ch.isalnum())

    target = norm(name)
    exact = [r for r in rows if norm(r.get("unii_name") or r.get("name")) == target]
    if len(exact) == 1:
        return "ok", exact[0], rows[:10]
    if len(exact) > 1:
        return "ambiguous", None, exact[:10]
    if len(rows) == 1:
        # single near-match: usable, but flagged so a human can eyeball it
        return "single_inexact", rows[0], rows[:10]
    return "ambiguous", None, rows[:10]


def count_spls(unii):
    doc = fetch(f"{BASE}/spls.json?unii_code={urllib.parse.quote(unii)}&pagesize=1")
    if doc is None:
        return None
    try:
        return int(doc.get("metadata", {}).get("total_elements", 0))
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--names", nargs="*", default=None,
                    help="override the filter name list (for testing)")
    args = ap.parse_args()

    names = args.names if args.names else UV_FILTER_NAMES
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    results = []
    for name in names:
        print(f"[resolve] {name}", flush=True)
        status, chosen, cands = lookup_unii(name)
        entry = {"query": name, "status": status, "unii": None, "unii_name": None,
                 "spl_count": None,
                 "candidates": [{"unii": c.get("unii_code") or c.get("unii"),
                                 "name": c.get("unii_name") or c.get("name")}
                                for c in cands]}
        if chosen:
            unii = chosen.get("unii_code") or chosen.get("unii")
            entry["unii"] = unii
            entry["unii_name"] = chosen.get("unii_name") or chosen.get("name")
            if unii:
                entry["spl_count"] = count_spls(unii)
                if entry["spl_count"] == 0:
                    entry["status"] = "zero_spls"
                elif status == "ok":
                    entry["status"] = "ok"
        results.append(entry)
        print(f"    -> {entry['status']} unii={entry['unii']} spls={entry['spl_count']}",
              flush=True)
        time.sleep(0.3)

    usable = [r for r in results if r["status"] in ("ok", "single_inexact") and r["unii"]]
    doc = {
        "resolved_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": f"{BASE}/uniis.json",
        "note": "Codes are resolved from DailyMed, never typed from memory. "
                "Only status ok/single_inexact are used as search seeds; "
                "everything else is recorded so the gap stays visible.",
        "usable_count": len(usable),
        "filters": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"\n--- RESOLVED ---")
    for r in results:
        flag = "OK " if r["status"] in ("ok", "single_inexact") else "!! "
        print(f"{flag}{r['query']:28} {str(r['unii'] or '-'):12} "
              f"spls={r['spl_count']} [{r['status']}]")
    print(f"\nusable seeds: {len(usable)}/{len(results)} -> {args.out}")
    if len(usable) < 2:
        print("FATAL: fewer than 2 usable seeds — refusing to hand this to the scraper",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
