#!/usr/bin/env python3
"""
resolve_uniis.py — resolve UV-filter NAMES to UNII codes. v2, assumption-free.

WHAT WENT WRONG IN v1
  v1 called /uniis.json?substance_name=<NAME>. That parameter does not exist.
  The documented filters on /uniis are: active_moiety, drug_class_code,
  drug_class_coding_system, rxcui, unii_code, pagesize, page — and the response
  fields are unii_code and active_moiety, not unii_name. Every lookup silently
  returned nothing, the file was written with zero usable codes, and the scraper
  fell back to mineral-only. The fallback did its job; the resolver did not.

WHAT v2 DOES INSTEAD
  Downloads the whole /uniis list once (paginated) and matches locally. No guess
  about server-side matching semantics, one pass covers every filter, and the
  downloaded catalogue is written to disk so a failed match can be inspected
  rather than argued about.

  Matching is layered and each layer is recorded:
    exact      normalised name equals an active_moiety      -> ok
    alias      an alias for that filter matches exactly      -> ok
    contains   exactly one active_moiety contains the name   -> single_inexact
    several    more than one candidate                       -> ambiguous
    none                                                     -> not_found

  Every resolved code is then counted against /spls?unii_code=... . A code with
  zero SPLs is marked zero_spls and NOT used as a seed: it would widen the net
  by nothing while looking like success.

Writes:
  data/reference/uv_filter_uniis.json   seeds + provenance for every attempt
  data/reference/_uniis_catalogue.json  the raw downloaded list (audit trail)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
OUT = "data/reference/uv_filter_uniis.json"
CATALOGUE = "data/reference/_uniis_catalogue.json"

# UV filters, each with the aliases DailyMed might use for the active moiety.
# INCI, USAN and trade names diverge, so several spellings are offered and the
# first that resolves wins. Adding a NAME here is safe; inventing a CODE is not.
UV_FILTERS = [
    ("ZINC OXIDE", []),
    ("TITANIUM DIOXIDE", []),
    ("AVOBENZONE", ["BUTYL METHOXYDIBENZOYLMETHANE"]),
    ("OXYBENZONE", ["BENZOPHENONE-3"]),
    ("OCTINOXATE", ["OCTYL METHOXYCINNAMATE", "ETHYLHEXYL METHOXYCINNAMATE"]),
    ("OCTISALATE", ["OCTYL SALICYLATE", "ETHYLHEXYL SALICYLATE"]),
    ("OCTOCRYLENE", []),
    ("HOMOSALATE", []),
    ("ENSULIZOLE", ["PHENYLBENZIMIDAZOLE SULFONIC ACID"]),
    ("SULISOBENZONE", ["BENZOPHENONE-4"]),
    ("DIOXYBENZONE", ["BENZOPHENONE-8"]),
    ("MERADIMATE", ["MENTHYL ANTHRANILATE"]),
    ("CINOXATE", []),
    ("PADIMATE O", ["ETHYLHEXYL DIMETHYL PABA"]),
    ("TROLAMINE SALICYLATE", []),
    ("AMINOBENZOIC ACID", ["PABA"]),
    # Not currently GRASE in the US. Collected deliberately: FDA proposed order
    # OTC000039 would add bemotrizinol to Monograph M020, and a before/after
    # needs the "before" already in the corpus.
    ("BEMOTRIZINOL",
     ["BIS-ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE", "BEMOTRIZINOLE"]),
    ("BISOCTRIZOLE",
     ["METHYLENE BIS-BENZOTRIAZOLYL TETRAMETHYLBUTYLPHENOL"]),
    ("ECAMSULE", ["TEREPHTHALYLIDENE DICAMPHOR SULFONIC ACID"]),
    ("DROMETRIZOLE TRISILOXANE", []),
    ("OCTYL TRIAZONE", ["ETHYLHEXYL TRIAZONE"]),
    ("DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE", ["DHHB"]),
    # Found by discover_actives.py in the 2026-08-26 run: real UV filters that
    # were sitting in collected products without being search seeds themselves.
    # A product using ONLY one of these was invisible to the net.
    ("ENZACAMENE", ["4-METHYLBENZYLIDENE CAMPHOR"]),      # 6 products
    ("AMILOXATE", ["ISOAMYL P-METHOXYCINNAMATE"]),        # 3
    ("ETHYL METHOXYCINNAMATE", []),                       # 3
    ("BENZOPHENONE", []),                                 # 3
]


def norm(s):
    """Fold the spelling variance SPL is known to carry."""
    s = str(s or "").upper()
    s = re.sub(r"\.(ALPHA|BETA|GAMMA|DELTA|DL|D|L)\.-?", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch(url, tries=4, backoff=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "TinySafe-research/2.2 (contact: support@tinysafe.app)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                print(f"    fetch failed: {url} :: {e}", file=sys.stderr)
                return None
            time.sleep(backoff * (i + 1))
    return None


def download_catalogue(max_pages=600):
    """Page the whole /uniis list. Documented params only: pagesize, page."""
    rows, page = [], 1
    while page <= max_pages:
        doc = fetch(f"{BASE}/uniis.json?pagesize=100&page={page}")
        if doc is None:
            print(f"  page {page} failed — stopping with {len(rows)} rows",
                  file=sys.stderr)
            break
        batch = doc.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        meta = doc.get("metadata", {})
        if page == 1:
            print(f"  total_elements={meta.get('total_elements')} "
                  f"total_pages={meta.get('total_pages')}", flush=True)
        if not meta.get("next_page"):
            break
        page += 1
        if page % 25 == 0:
            print(f"  ...page {page} ({len(rows)} rows)", flush=True)
        time.sleep(0.15)
    return rows


def build_index(rows):
    """normalised active_moiety -> list of {unii, moiety}"""
    idx = {}
    for r in rows:
        code = r.get("unii_code") or r.get("unii")
        moiety = r.get("active_moiety") or r.get("name")
        if not code or not moiety:
            continue
        idx.setdefault(norm(moiety), []).append({"unii": code, "moiety": moiety})
    return idx


def resolve(name, aliases, idx, flat):
    for cand_name, how in [(name, "exact")] + [(a, "alias") for a in aliases]:
        hits = idx.get(norm(cand_name))
        if hits and len(hits) == 1:
            return "ok", hits[0], how, []
        if hits and len(hits) > 1:
            return "ambiguous", None, how, hits[:8]
    # last resort: substring over the catalogue
    target = norm(name)
    part = [e for k, v in flat if target and target in k for e in v]
    if len(part) == 1:
        return "single_inexact", part[0], "contains", part[:8]
    if len(part) > 1:
        return "ambiguous", None, "contains", part[:8]
    return "not_found", None, "none", []


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
    ap.add_argument("--catalogue", default=CATALOGUE)
    ap.add_argument("--catalogue-file", default=None,
                    help="use a saved catalogue instead of downloading (testing)")
    ap.add_argument("--no-spl-count", action="store_true",
                    help="skip the per-code SPL count (testing)")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    if args.catalogue_file:
        rows = json.load(open(args.catalogue_file, encoding="utf-8"))
        print(f"[catalogue] loaded {len(rows)} rows from file", flush=True)
    else:
        print("[catalogue] downloading /uniis ...", flush=True)
        rows = download_catalogue()
        print(f"[catalogue] {len(rows)} rows", flush=True)

    if len(rows) < 100:
        print(f"FATAL: catalogue has only {len(rows)} rows — refusing to resolve "
              "against a truncated list", file=sys.stderr)
        return 1

    with open(args.catalogue, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)

    idx = build_index(rows)
    flat = list(idx.items())
    print(f"[catalogue] {len(idx)} distinct normalised moieties\n", flush=True)

    results = []
    for name, aliases in UV_FILTERS:
        status, chosen, how, cands = resolve(name, aliases, idx, flat)
        entry = {
            "query": name, "aliases": aliases, "status": status,
            "matched_via": how, "unii": None, "active_moiety": None,
            "spl_count": None,
            "candidates": [{"unii": c["unii"], "active_moiety": c["moiety"]}
                           for c in cands],
        }
        if chosen:
            entry["unii"] = chosen["unii"]
            entry["active_moiety"] = chosen["moiety"]
            if not args.no_spl_count:
                entry["spl_count"] = count_spls(chosen["unii"])
                if entry["spl_count"] == 0:
                    entry["status"] = "zero_spls"
                time.sleep(0.2)
        results.append(entry)
        print(f"{name:44} {entry['status']:14} {str(entry['unii'] or '-'):12} "
              f"spls={entry['spl_count']} via={how}", flush=True)

    usable = [r for r in results
              if r["status"] in ("ok", "single_inexact") and r["unii"]]
    doc = {
        "resolved_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": f"{BASE}/uniis.json (full paged download, matched locally)",
        "catalogue_rows": len(rows),
        "note": "Only documented /uniis parameters are used (pagesize, page). "
                "Matching happens locally so no assumption is made about "
                "server-side search behaviour. Codes are never typed by hand.",
        "usable_count": len(usable),
        "filters": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    unresolved = [r["query"] for r in results if r not in usable]
    print(f"\nusable seeds : {len(usable)}/{len(results)}")
    if unresolved:
        print(f"unresolved   : {', '.join(unresolved)}")
    print(f"written      : {args.out}")

    if len(usable) < 2:
        print("FATAL: fewer than 2 usable seeds — the scraper will fall back to "
              "mineral-only", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
