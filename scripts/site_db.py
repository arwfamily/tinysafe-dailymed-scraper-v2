#!/usr/bin/env python3
"""Sunnytime site data from the us_all release.

    <site>/sunnytime/db.json     the product finder's data (compact, names indexed)
    <site>/sunnytime/index.html  the three headline numbers are rewritten from the data

Nothing on the site is typed by hand any more: the counts come from the same
records the finder shows.

Usage: python3 scripts/site_db.py --site ../arwhouse [--check]
       python3 scripts/site_db.py --old data/site/sunnytime_db.json --out data/site/sunnytime_db.json
       --check: build into memory, run the quality gate against the live db.json, write nothing
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from us_master import REF_FLAGS, RULES_VERSION  # noqa: E402

NOTE = ("Inactive ingredients = the label's structured SPL table plus the printed Drug Facts 'Inactive ingredients' "
        "list, read from the current DailyMed label (text, and label images read twice where the text has no list). "
        "thin = 7 or fewer inactives; thin_reason: no_printed_list | label_prints_too_little | "
        "label_image_unreadable | short_list. label_check: how the label was verified. ft: main UV filter. "
        "bk: product name says baby/kids. st: active | discontinued (no longer on DailyMed).")


def build(release_dir):
    manifest = json.load(open(os.path.join(release_dir, "manifest.json"), encoding="utf-8"))
    meta = json.load(open(REF_FLAGS, encoding="utf-8"))["meta"]
    rows = [json.loads(x) for x in open(os.path.join(release_dir, "us_all.jsonl"), encoding="utf-8") if x.strip()]
    names, idx, out = [], {}, []
    as_of = manifest["source"]["collected"]
    for r in sorted(rows, key=lambda r: (r.get("status") != "active", r.get("name") or "")):
        ii = []
        for n in r.get("inactives") or []:
            if n not in idx:
                idx[n] = len(names)
                names.append(n)
            ii.append(idx[n])
        recs = r.get("recalls") or []
        haz = sorted({h for x in recs if x["status"] == "matched" for h in x.get("hazards") or []})
        p = {"id": r["setid"], "n": r.get("name"), "b": r.get("brand"), "s": r.get("spf"), "d": as_of,
             "m": r.get("mineral_type"), "z": [[a["name"], a.get("percent")] for a in r.get("actives") or []],
             "r": haz, "rk": 1 if (r.get("recall_checked") or haz) else 0, "v": r.get("spl_version"),
             "i": ii, "v3": r.get("flags") or [],
             "i_src": r.get("inactive_source"), "i_struct_n": r.get("inactives_filed_n"),
             "i_text_n": r.get("inactives_printed_n"), "thin": r.get("thin"), "ft": r.get("filter_type"),
             "bk": 1 if r.get("is_baby_kids") else 0, "st": r.get("status")}
        if r.get("thin_reason"):
            p["thin_reason"] = r["thin_reason"]
        if r.get("label_check"):
            p["label_check"] = r["label_check"]
        if any(x["status"] == "needs_review" for x in recs):
            p["rr"] = 1                                    # a recall matched on brand + name only: under review
        out.append(p)
    return {"count": len(out), "as_of": as_of, "release_id": manifest["release_id"], "meta": meta,
            "rules_version": RULES_VERSION, "flags": [], "inactives_as_of": as_of, "inactives_note": NOTE,
            "names": names, "p": out}


def explained(release_dir):
    """Reviewed reasons a label may leave the site or change its list this week
    (see quality_gate.check)."""
    from us_master import MASTER
    out = {}
    for line in open(MASTER, encoding="utf-8"):
        r = json.loads(line)
        if not r.get("in_scope") and r.get("excluded_reason") and (r.get("scope_override") or r["excluded_reason"] in (
                "spf_makeup", "spf_lip_balm", "diaper_cream", "not_a_sunscreen", "zinc_only_no_sun_claim")):
            out[r["setid"]] = "scope:" + r["excluded_reason"]
        elif r.get("actives_corrected"):
            out[r["setid"]] = "actives_corrected"
        elif r.get("fetch_status") == "carried_forward":
            out[r["setid"]] = "last_good_read_kept"
        elif r.get("inactives_tidied") or r.get("filed_synonyms_dropped"):
            out[r["setid"]] = "list_split_repaired"
        elif r.get("inactives_added_from_label_text"):
            out[r["setid"]] = "label_text_addition"
    return out


def headline(db):
    act = [p for p in db["p"] if p.get("st") == "active"]
    has = lambda p, f: any(x[0] == f for x in p["v3"])  # noqa: E731
    return {
        "read": len(act),
        "booster": sum(1 for p in act if p.get("ft") == "mineral_only" and has(p, "hidden_uv_booster")),
        "recall": sum(1 for p in act if p["r"]),
    }


def patch_index(html, h):
    def sub(label, value, s):
        new, n = re.subn(r"(<b>)[\d,]+(</b><span>" + re.escape(label) + r")", r"\g<1>" + f"{value:,}" + r"\2", s)
        if n != 1:
            raise SystemExit(f"index.html: stat '{label}' not found exactly once")
        return new
    html = sub("FDA-registered sunscreens, read", h["read"], html)
    html = sub("hide a UV booster", h["booster"], html)
    html = sub("with a recall on record", h["recall"], html)
    html = re.sub(r"[\d,]+ sunscreens · 3-tier rules v[\d.]+", f"{h['read']:,} sunscreens · 3-tier rules "
                  + RULES_VERSION.split(" ")[0], html)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=os.path.join(ROOT, "data/releases/us/latest"))
    ap.add_argument("--site", help="a checkout of arwhouse: reads and writes sunnytime/db.json + index.html")
    ap.add_argument("--old", help="last published db.json (default: <site>/sunnytime/db.json)")
    ap.add_argument("--out", help="where to write the new db.json (default: <site>/sunnytime/db.json)")
    ap.add_argument("--index", help="index.html whose headline numbers to rewrite (default: <site>/sunnytime/index.html)")
    ap.add_argument("--headline-json", help="also write the headline numbers here")
    ap.add_argument("--check", action="store_true", help="run the gate only, write nothing")
    a = ap.parse_args()
    site = a.site
    old_p = a.old or (os.path.join(site, "sunnytime/db.json") if site else None)
    out_p = a.out or (os.path.join(site, "sunnytime/db.json") if site else None)
    idx_p = a.index or (os.path.join(site, "sunnytime/index.html") if site else None)
    db = build(a.release)
    h = headline(db)
    old = json.load(open(old_p, encoding="utf-8")) if old_p and os.path.exists(old_p) else None
    import quality_gate as G
    problems, report = G.check(old, db, explained(a.release))
    print(json.dumps({"headline": h, "gate": report}, ensure_ascii=False, indent=1))
    if problems:
        print("QUALITY GATE FAILED:\n  " + "\n  ".join(problems))
        sys.exit(2)
    if a.check:
        return
    if a.headline_json:
        os.makedirs(os.path.dirname(os.path.abspath(a.headline_json)), exist_ok=True)
        json.dump(dict(h, release_id=db["release_id"], as_of=db["as_of"]), open(a.headline_json, "w"), indent=1)
    if out_p:
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
        print("wrote", out_p)
    if idx_p and os.path.exists(idx_p):
        html = open(idx_p, encoding="utf-8").read()
        open(idx_p, "w", encoding="utf-8").write(patch_index(html, h))
        print("rewrote the headline numbers in", idx_p)


if __name__ == "__main__":
    main()
