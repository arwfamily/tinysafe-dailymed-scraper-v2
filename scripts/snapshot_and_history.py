#!/usr/bin/env python3
"""
snapshot_and_history.py — turn a scraper run into a permanent, comparable asset.

Reads  : output/tinysafe_dailymed_v2_master.json   (produced by dailymed_scraper.py)
Writes : data/raw/dailymed/<RUN_DATE>/master.json  immutable L0 snapshot
         data/canonical/us_sunscreens.jsonl        latest state, one line per setid
         data/history/us_formulation_history.jsonl append-only observation log
         data/history/_state.json                  last-seen hash per setid

Design rules (learned the hard way):
  * setid is the identity. Compare a product ONLY against its own past.
    A product vanishing is `delisted`, never `reformulated`.
  * formulation_hash keys on UNII when present, name otherwise. SPL spells the
    same ingredient many ways (TOCOPHEROL vs .ALPHA.-TOCOPHEROL); UNII does not.
  * Inactive ORDER is kept in the hash (it encodes concentration order).
    Active order is NOT (registration order is meaningless).
  * Metadata drift (title, dosage form, SPF re-parse) is recorded as `metadata`,
    never as `reformulated` — otherwise a logo change fakes a formula event.
  * Every history line carries a FULL snapshot, so any past state can be
    reconstructed from the history file alone.

Partial runs (--limit N in the scraper) must never touch canonical/history:
pass --partial to write only the raw snapshot.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

RAW_DIR = "data/raw/dailymed"
CANONICAL = "data/canonical/us_sunscreens.jsonl"
HISTORY = "data/history/us_formulation_history.jsonl"
STATE = "data/history/_state.json"

# Fields that describe the FORMULA. Changes here = reformulated.
# Fields outside this set = metadata.
META_FIELDS = [
    "title", "product_name", "dosage_form", "spf", "category",
    "baby_labeled", "labeler", "brand",
]


def norm_name(name):
    """
    Fallback identity for ingredients SPL gave us without a UNII.
    SPL spells the same thing many ways, so strip the noise that is known to
    drift without the formula changing:
      'HELIANTHUS ANNUUS (SUNFLOWER) SEED OIL' -> 'HELIANTHUS ANNUUS SEED OIL'
      '.ALPHA.-TOCOPHEROL'                     -> 'TOCOPHEROL'
      'SUNFLOWER  OIL,'                        -> 'SUNFLOWER OIL'
    This is a heuristic, not an identifier — see `confidence` on the event.
    """
    import re
    s = (name or "").upper()
    s = re.sub(r"\.(ALPHA|BETA|GAMMA|DELTA|D|L|DL)\.\-?", "", s)   # .ALPHA.-X
    s = re.sub(r"\([^)]*\)", " ", s)                               # (SUNFLOWER)
    s = re.sub(r"\b(USP|NF|EP|ANHYDROUS|PURIFIED)\b", " ", s)
    s = re.sub(r"[^A-Z0-9/\- ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ing_key(ing):
    """Stable identity for one ingredient: UNII if we have it, else normalised name."""
    if isinstance(ing, dict):
        unii = (ing.get("unii") or "").strip().upper()
        if unii:
            return f"U:{unii}"
        return "N:" + norm_name(ing.get("name"))
    return "N:" + norm_name(str(ing))


def norm_strength(s):
    """Normalise a strength string so '20 %' and '20%' don't look different."""
    if s is None:
        return ""
    return "".join(str(s).split()).upper()


def formulation_fingerprint(rec):
    """
    Canonical representation of the FORMULA only.
      actives   : sorted (registration order carries no meaning) + strength
      inactives : original order preserved (order encodes concentration ranking)
      dosage    : included — lotion vs stick is a formulation fact
    """
    actives = sorted(
        f"{ing_key(a)}@{norm_strength(a.get('strength') if isinstance(a, dict) else None)}"
        for a in (rec.get("active_ingredients") or [])
    )
    inactives = [ing_key(i) for i in (rec.get("inactive_ingredients") or [])]
    dosage = (rec.get("dosage_form") or "").strip().upper()
    payload = {"actives": actives, "inactives": inactives, "dosage": dosage}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16], payload


def meta_view(rec):
    return {k: rec.get(k) for k in META_FIELDS}


def key_delta(prev_payload, new_payload):
    """Which ingredient keys entered / left, actives and inactives together."""
    def keys(pl):
        return set(pl.get("inactives") or []) | {
            a.split("@")[0] for a in (pl.get("actives") or [])
        }
    a, b = keys(prev_payload), keys(new_payload)
    return sorted(b - a), sorted(a - b)


def diff_meta(old, new):
    out = {}
    for k in META_FIELDS:
        if (old or {}).get(k) != (new or {}).get(k):
            out[k] = {"from": (old or {}).get(k), "to": (new or {}).get(k)}
    return out


def load_state(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"setids": {}}


def read_master(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    prods = doc.get("products", doc if isinstance(doc, list) else [])
    meta = doc.get("metadata", {}) if isinstance(doc, dict) else {}
    return prods, meta


def coverage_report(prods):
    """Print what the net did and did NOT catch. A dataset must state its own limits."""
    n = len(prods)

    def cnt(fn):
        return sum(1 for p in prods if fn(p))

    empty_inact = cnt(lambda p: not (p.get("inactive_ingredients") or []))
    no_unii = 0
    total_ing = 0
    for p in prods:
        for i in (p.get("inactive_ingredients") or []):
            total_ing += 1
            if isinstance(i, dict) and not i.get("unii"):
                no_unii += 1
    cats = {}
    for p in prods:
        cats[p.get("category")] = cats.get(p.get("category"), 0) + 1

    print("\n--- COVERAGE ---", flush=True)
    print(f"collected SPLs                : {n}")
    print(f"categories                    : {cats}")
    print(f"zero inactive ingredients     : {empty_inact} ({pct(empty_inact, n)})")
    print(f"inactive rows without UNII    : {no_unii}/{total_ing} ({pct(no_unii, total_ing)})"
          "   <- these fall back to name matching")
    print(f"baby_labeled                  : {cnt(lambda p: p.get('baby_labeled'))}")
    print(f"has_hidden_chemical_filter    : {cnt(lambda p: p.get('has_hidden_chemical_filter'))}")
    print(f"contains_chemical_filter      : {cnt(lambda p: p.get('contains_chemical_filter'))}")
    print("NOTE: the Phase A net is an ACTIVE-ingredient search on ZnO/TiO2.")
    print("      Chemical-only sunscreens are NOT collectable by design, so this")
    print("      dataset cannot compute a mineral-vs-chemical market share.")


def pct(a, b):
    return "0%" if not b else f"{round(100 * a / b)}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="output/tinysafe_dailymed_v2_master.json")
    ap.add_argument("--run-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--partial", action="store_true",
                    help="smoke test / limited run: write raw snapshot only, never touch "
                         "canonical or history (a capped run would look like mass delisting)")
    args = ap.parse_args()

    if not os.path.exists(args.master):
        print(f"FATAL: {args.master} not found", file=sys.stderr)
        return 1

    prods, meta = read_master(args.master)
    if not prods:
        print("FATAL: master has zero products — refusing to write "
              "(this would delist everything)", file=sys.stderr)
        return 1

    # ---- 1. immutable raw snapshot -------------------------------------
    snap_dir = os.path.join(RAW_DIR, args.run_date)
    os.makedirs(snap_dir, exist_ok=True)
    snap_path = os.path.join(snap_dir, "master.json")
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump({"metadata": meta, "products": prods}, f, ensure_ascii=False, indent=1)
    print(f"[snapshot] {snap_path} ({len(prods)} products)", flush=True)

    coverage_report(prods)

    if args.partial:
        print("\n[partial] limited run — canonical and history untouched.", flush=True)
        return 0

    # ---- 2. compare against last known state ---------------------------
    os.makedirs(os.path.dirname(CANONICAL), exist_ok=True)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    state = load_state(STATE)
    seen_before = state.get("setids", {})

    events = []
    now_state = {}
    counts = {"new": 0, "reformulated": 0, "metadata": 0, "unchanged": 0, "delisted": 0}

    for rec in prods:
        setid = rec.get("setid")
        if not setid:
            continue
        fhash, payload = formulation_fingerprint(rec)
        mv = meta_view(rec)
        prev = seen_before.get(setid)

        now_state[setid] = {
            "formulation_hash": fhash,
            "payload": payload,
            "meta": mv,
            "last_seen": args.run_date,
            "first_seen": (prev or {}).get("first_seen", args.run_date),
        }

        if prev is None:
            change = "new"
            extra = {}
        elif prev.get("formulation_hash") != fhash:
            change = "reformulated"
            prev_payload = prev.get("payload") or {}
            added, removed = key_delta(prev_payload, payload)
            # A change is only trustworthy if every key that moved was
            # UNII-identified. Name-only keys drift on relabelling alone.
            name_only = [k for k in (added + removed) if k.startswith("N:")]
            extra = {
                "previous_hash": prev.get("formulation_hash"),
                "keys_added": added,
                "keys_removed": removed,
                "confidence": "low" if name_only else "high",
                "confidence_reason": (
                    "changed ingredients lack a UNII — may be a relabelling, "
                    "verify against the raw snapshots before citing"
                    if name_only else "all changed ingredients are UNII-identified"
                ),
            }
        else:
            md = diff_meta(prev.get("meta"), mv)
            if md:
                change = "metadata"
                extra = {"meta_changed": md}
            else:
                change = "unchanged"
                extra = {}

        counts[change] += 1
        if change == "unchanged":
            continue

        events.append({
            "observed_on": args.run_date,
            "setid": setid,
            "change": change,
            "formulation_hash": fhash,
            **extra,
            "product_name": rec.get("product_name") or rec.get("title"),
            "dosage_form": rec.get("dosage_form"),
            "spf": rec.get("spf"),
            "active_ingredients": rec.get("active_ingredients"),
            "inactive_ingredients": rec.get("inactive_ingredients"),
            "fingerprint_payload": payload,
        })

    # ---- 3. delisting: seen before, absent now -------------------------
    gone = [s for s in seen_before if s not in now_state]
    # Safety valve: a scrape that lost >20% of the corpus is a broken run,
    # not a market event. Keep the old entries and shout.
    if seen_before and len(gone) > 0.2 * len(seen_before):
        print(f"\nABORT: {len(gone)}/{len(seen_before)} setids missing (>20%). "
              "Treating as a failed scrape, not delisting. "
              "Canonical/history NOT updated.", file=sys.stderr)
        return 1

    for setid in gone:
        prev = seen_before[setid]
        counts["delisted"] += 1
        events.append({
            "observed_on": args.run_date,
            "setid": setid,
            "change": "delisted",
            "formulation_hash": prev.get("formulation_hash"),
            "product_name": (prev.get("meta") or {}).get("product_name")
                            or (prev.get("meta") or {}).get("title"),
            "note": "present in a previous run, absent in this one — "
                    "withdrawal, relabel under a new setid, or scraper miss",
        })
        # keep the record so we never lose its history
        now_state[setid] = {**prev, "delisted_on": args.run_date}

    # ---- 4. write ------------------------------------------------------
    with open(HISTORY, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    with open(CANONICAL, "w", encoding="utf-8") as f:
        for rec in sorted(prods, key=lambda r: r.get("setid") or ""):
            rec = dict(rec)
            rec["formulation_hash"] = now_state[rec["setid"]]["formulation_hash"]
            rec["first_seen"] = now_state[rec["setid"]]["first_seen"]
            rec["last_seen"] = args.run_date
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"run_date": args.run_date, "setids": now_state}, f,
                  ensure_ascii=False, indent=1)

    print("\n--- CHANGE LOG ---", flush=True)
    for k in ("new", "reformulated", "metadata", "delisted", "unchanged"):
        print(f"{k:14}: {counts[k]}")
    if counts["reformulated"]:
        print("\nreformulated this run:")
        for e in events:
            if e["change"] == "reformulated":
                print(f"  - [{e.get('confidence','?'):4}] {e['product_name']} "
                      f"({e['previous_hash']} -> {e['formulation_hash']})")
                if e.get("keys_added"):
                    print(f"          + {', '.join(e['keys_added'])}")
                if e.get("keys_removed"):
                    print(f"          - {', '.join(e['keys_removed'])}")
    print(f"\nhistory  -> {HISTORY} (+{len(events)} lines)")
    print(f"canonical-> {CANONICAL} ({len(prods)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
