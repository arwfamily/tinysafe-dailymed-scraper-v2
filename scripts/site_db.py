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


def build(release_dir, thumbs_dir=None):
    manifest = json.load(open(os.path.join(release_dir, "manifest.json"), encoding="utf-8"))
    meta = json.load(open(REF_FLAGS, encoding="utf-8"))["meta"]
    rows = [json.loads(x) for x in open(os.path.join(release_dir, "us_all.jsonl"), encoding="utf-8") if x.strip()]
    names, idx, out = [], {}, []
    as_of = manifest["source"]["collected"]
    # package images DailyMed lists for each label (scripts/verify/image_names.py), front first
    _imp = os.path.join(ROOT, "data/views/label_image_names.json")
    IMGS = json.load(open(_imp, encoding="utf-8")) if os.path.exists(_imp) else {}
    # a label whose filed images a reader found to show another product: no photo (a parent would
    # take it for this one; Avon's Sport Refresh filed with its Kids lotion art; 2026-10-24)
    WRONG = set()
    for _f in ("artwork_reads", "confirm_reads", "third_reads", "bs_reads", "absent_reads", "no_artwork"):
        _fp = os.path.join(ROOT, "data/corrections", _f + ".jsonl")
        if os.path.exists(_fp):
            for _l in open(_fp, encoding="utf-8"):
                _d = json.loads(_l)
                if _d.get("wrong_product") or _d.get("reason") == "wrong_product":
                    WRONG.add(_d["setid"])
    # formula changes seen in the weekly history (data/history): what the FDA filing added or dropped
    FC = {}
    _hp = os.path.join(ROOT, "data/history/us_formulation_history.jsonl")
    if os.path.exists(_hp):
        _last = {}
        for _l in open(_hp, encoding="utf-8"):
            _h = json.loads(_l)
            def _keys(h):
                # diff on the FDA ingredient code (UNII) so a renamed or re-spelled name is not "added" (name if no code)
                k = {}
                for a in h.get("inactive_ingredients") or []:
                    nm = (a.get("name") or "").strip().upper()
                    k[a.get("unii") or "N:" + nm] = nm
                for a in h.get("active_ingredients") or []:
                    nm = (a.get("name") or "").strip().upper()
                    pc = f" {a['percent_ww']:g}%" if a.get("percent_ww") is not None else ""
                    k["A:" + (a.get("unii") or nm) + pc] = "ACTIVE: " + nm + pc
                return k
            prev = _last.get(_h["setid"])
            if _h.get("change") == "reformulated" and prev is not None:
                now, was = _keys(_h), _keys(prev)
                add = sorted(now[k] for k in now.keys() - was.keys())
                rem = sorted(was[k] for k in was.keys() - now.keys())
                if add or rem:
                    FC.setdefault(_h["setid"], []).append([_h["observed_on"], add[:10], rem[:10]])
            if _h.get("inactive_ingredients") or _h.get("active_ingredients"):
                _last[_h["setid"]] = _h
    # the FDA recall records (firm, which products, which lots), to say how far a recall reaches
    RC = {}
    _rp = os.path.join(ROOT, "data/recalls/us_drug_recalls.jsonl")
    if os.path.exists(_rp):
        for _l in open(_rp, encoding="utf-8"):
            _d = json.loads(_l)
            RC[_d["recall_number"]] = _d

    def _scope(rn):
        d = RC.get(rn) or {}
        desc, code = d.get("product_description") or "", d.get("code_info") or ""
        if re.search(r"distributed to specific .{0,40}stores", desc, re.I):
            return "store"                                  # a store pulled stock it kept badly, not the maker's recall
        if re.search(r"\b(lot|batch)\b", code, re.I):
            return "lot"
        return ""
    def _reach(rn):
        d = RC.get(rn) or {}
        m = re.search(r"distributed to specific .{0,200}", d.get("product_description") or "", re.I)
        return (m.group(0) if m else (d.get("code_info") or ""))[:160].strip()
    # Broad Spectrum as read from the package image (same label version): 1 claim seen, 0 the package was
    # read and shows none, for labels whose FDA text settles nothing (2026-10-26 random audit)
    PKG_BS, PKG_FORM = {}, {}
    for _f in ("artwork_reads", "claims_reads"):
        _fp = os.path.join(ROOT, "data/corrections", _f + ".jsonl")
        if os.path.exists(_fp):
            for _l in open(_fp, encoding="utf-8"):
                _d = json.loads(_l)
                if _d.get("readable") is False:
                    continue
                _k = (_d["setid"], str(_d.get("spl_version")))
                if _d.get("form") in ("aerosol spray", "non-aerosol spray"):
                    PKG_FORM[_k] = "aerosol" if _d["form"] == "aerosol spray" else "pump"
                if _d.get("broad_spectrum") not in (True, False):
                    continue
                PKG_BS[_k] = 1 if (_d["broad_spectrum"] is True or PKG_BS.get(_k) == 1) else 0
    # a propellant spray the FDA files only as "SPRAY": its label text warns that the contents are under
    # pressure (2026-10-26 live audit: Equate Kids, Sun Shades, Coppertone Sport)
    _tp = os.path.join(ROOT, "data/views/label_text_all.jsonl.gz")
    if os.path.exists(_tp):
        import gzip
        for _l in gzip.open(_tp, "rt", encoding="utf-8"):
            _d = json.loads(_l)
            if re.search(r"(?i)contents?\s+under\s+pressure|do\s+not\s+puncture\s+or\s+incinerate", _d.get("text") or ""):
                PKG_FORM.setdefault((_d["setid"], str(_d.get("spl_version"))), "aerosol")
    for r in sorted(rows, key=lambda r: (r.get("status") != "active", r.get("name") or "")):
        ii = []
        for n in r.get("inactives") or []:
            if n not in idx:
                idx[n] = len(names)
                names.append(n)
            ii.append(idx[n])
        recs = r.get("recalls") or []
        haz = sorted({h for x in recs if x["status"] == "matched" and _scope(x["recall_number"]) != "store"
                      for h in x.get("hazards") or []})
        p = {"id": r["setid"], "n": r.get("name"), "b": r.get("brand"), "s": r.get("spf"), "d": (lambda e: f"{e[:4]}-{e[4:6]}-{e[6:8]}" if e and len(str(e)) == 8 else None)(str(r.get("effective_date") or "")),  # the label version's own date (FDA effective date)
             "m": r.get("mineral_type"), "z": [[a["name"], a.get("percent")] for a in r.get("actives") or []],
             "r": haz, "rk": 1 if (r.get("recall_checked") or haz) else 0, "v": r.get("spl_version"),
             "i": ii, "v3": r.get("flags") or [],
             "i_src": r.get("inactive_source"), "i_struct_n": r.get("inactives_filed_n"),
             "i_text_n": r.get("inactives_printed_n"), "thin": r.get("thin"), "ft": r.get("filter_type"),
             "bk": 1 if r.get("is_baby_kids") else 0, "st": r.get("status"),
             "bs": {True: 1, False: 0}.get(r.get("broad_spectrum")),
             "df": r.get("dosage_form")}
        if (r["setid"], str(r.get("spl_version"))) in PKG_FORM:
            p["pf"] = PKG_FORM[(r["setid"], str(r.get("spl_version")))]   # aerosol or pump, from the package read
        if p["bs"] is None and (r["setid"], str(r.get("spl_version"))) in PKG_BS:
            p["bsp"] = PKG_BS[(r["setid"], str(r.get("spl_version")))]                   # FDA dosage form (AEROSOL = propellant spray: EU conditions)
        w = r.get("actives_percent_withheld")
        if w:
            # 1 filed strengths implausible for the SPF, 2 filed as an amount per volume (not the
            # label's w/w %), 3 one filing for several products
            p["pw"] = {"not_w_w": 2, "multi_product": 3}.get(w, 1)
        if r.get("multi_product"):
            p["mp"] = r["multi_product"]                    # product count, or "kit"
        # last confirmed against FDA DailyMed (weekly), and when the package was last read
        if r.get("last_seen"):
            p["ck"] = r["last_seen"]
        if r.get("package_read"):
            p["pr"] = r["package_read"]
        if r.get("evidence_tier"):
            p["ev"] = r["evidence_tier"]                    # A two package reads agreed, B one read = filing, C filing only
        if r.get("thin_reason"):
            p["thin_reason"] = r["thin_reason"]
        if r.get("status") == "active" and r["setid"] not in WRONG and (IMGS.get(r["setid"]) or {}).get("names") and (
                thumbs_dir is None or os.path.exists(os.path.join(thumbs_dir, r["setid"] + ".webp"))):
            # (only with the site's own thumbnail: a photo it cannot show is not promised)
            p["im"] = IMGS[r["setid"]]["names"][:3]
        if r.get("label_check"):
            p["label_check"] = r["label_check"]
        if any(x["status"] == "needs_review" for x in recs):
            p["rr"] = 1                                    # a recall matched on brand + name only: under review
        rd = [[x.get("recall_number"), x.get("date"), x.get("classification"), x.get("reason"), x.get("recall_status"), x.get("url"),
               (RC.get(x["recall_number"]) or {}).get("recalling_firm"), _scope(x["recall_number"]),
               _reach(x["recall_number"])]
              for x in recs if x["status"] == "matched" and _scope(x["recall_number"]) != "store"]
        # (a store pulling stock it kept badly is not a recall of the product: not on the card; see how-we-check)
        _st = [x for x in recs if x["status"] == "matched" and _scope(x["recall_number"]) == "store"]
        if _st:
            # a store-level withdrawal on file: the card says "no maker recall", not "no recall"
            p["rs"] = [(RC.get(_st[0]["recall_number"]) or {}).get("recalling_firm"), _st[0].get("date"), _st[0].get("recall_number")]
        if rd:
            p["rd"] = rd                                   # the FDA recall records behind "recall on record"
        if FC.get(r["setid"]):
            p["fc"] = FC[r["setid"]]                       # [date, added, removed] in the FDA filing
        out.append(p)
    chp = os.path.join(ROOT, "data/reference/rules_changelog.json")
    changelog = json.load(open(chp, encoding="utf-8"))["changes"] if os.path.exists(chp) else []
    # the ingredient dictionary (scripts/cosing/dictionary.py): per name, its main job in a
    # sunscreen and how we know (r reviewed by two reads, c CosIng functions, p plant material,
    # x two reads of a name CosIng lacks); null where nothing is verified
    sys.path.insert(0, os.path.join(HERE, "cosing"))
    import dictionary as DICT
    dic = DICT.build(names)
    SRC = {"reviewed": "r", "cosing": "c", "plant": "p", "read": "x", "combined": "m"}
    nj = [dic[n]["job"] if dic[n]["src"] in SRC else None for n in names]
    njs = [SRC.get(dic[n]["src"]) for n in names]
    # several ingredients printed as one name: each part and its job, keyed by name index
    njp = {str(i): [[p["name"], p["job"]] for p in dic[n]["parts"]] for i, n in enumerate(names)
           if dic[n]["src"] == "combined"}
    return {"count": len(out), "as_of": as_of, "release_id": manifest["release_id"], "meta": meta,
            "nj": nj, "njs": njs, "njp": njp, "dictionary": {"source": "EU CosIng register (functions), main job reviewed by two "
                                                 "independent reads for the most-used ingredients",
                                                 "cosing_fetched": json.load(open(os.path.join(ROOT, "data/reference/cosing/manifest.json")))["fetched"]},
            "rules_changelog": changelog,
            "rules_version": RULES_VERSION, "flags": [], "inactives_as_of": as_of, "inactives_note": NOTE,
            "names": names, "p": out}


def explained(release_dir):
    """Reviewed reasons a label may leave the site or change its list this week
    (see quality_gate.check)."""
    from us_master import MASTER, TEXT_REVIEW
    out = {}
    for line in open(MASTER, encoding="utf-8"):
        r = json.loads(line)
        if not r.get("in_scope") and r.get("excluded_reason") and (r.get("scope_override") or r["excluded_reason"] in (
                "spf_makeup", "spf_lip_balm", "diaper_cream", "not_a_sunscreen", "zinc_only_no_sun_claim",
                "topical_analgesic", "skin_lightener")):
            out[r["setid"]] = "scope:" + r["excluded_reason"]
        elif r["setid"] in TEXT_REVIEW and TEXT_REVIEW[r["setid"]].get("actives"):
            out[r["setid"]] = "text_review_actives"        # a reviewer read the label's printed actives (2026-10-24 fullcheck)
        elif r.get("inactives_withheld"):
            out[r["setid"]] = "implausible_list_withheld"   # hundreds of names for one product (2026-10-24)
        elif r.get("actives_corrected"):
            out[r["setid"]] = "actives_corrected"
        elif r.get("absent_names_removed"):
            out[r["setid"]] = "three_reads_not_printed"    # three readers: a filed name printed nowhere on the package, no warning attached (2026-10-24)
        elif r.get("confirm_names_renamed"):
            out[r["setid"]] = "second_read_rename"         # two readers: the printed name, not the filed one (2026-10-24)
        elif r.get("fetch_status") == "carried_forward":
            out[r["setid"]] = "last_good_read_kept"
        elif r.get("inactives_tidied") or r.get("filed_synonyms_dropped"):
            out[r["setid"]] = "list_split_repaired"
        elif r.get("full_list_replaced"):
            out[r["setid"]] = "package_full_list"           # the package's full ingredient list, read twice (2026-10-24)
        elif r.get("artwork_list_withheld") == "multi_product":
            out[r["setid"]] = "multi_product_combined_list"  # the filing's list for all its products, as the site says (2026-10-24)
        elif r.get("artwork_list_withheld") == "unread_words":
            out[r["setid"]] = "artwork_list_withdrawn"       # the package read had words its reader could not read
        elif r.get("inactive_source") == "artwork":
            out[r["setid"]] = "artwork_list"            # the package artwork, read twice (artwork_reads.jsonl)
        elif (r.get("inactives_printed_n") or 0) >= 5:
            out[r["setid"]] = "printed_list_only"       # checked flag by flag (quality_gate)
        elif r.get("inactives_added_from_label_text"):
            out[r["setid"]] = "label_text_addition"
    return out


def headline(db):
    act = [p for p in db["p"] if p.get("st") == "active"]
    has = lambda p, f: any(x[0] == f for x in p["v3"])  # noqa: E731
    h = {
        "read": len(act),
        "booster": sum(1 for p in act if p.get("ft") == "mineral_only" and has(p, "hidden_uv_booster")),
        "recall": sum(1 for p in act if p["r"]),
    }
    ap = os.path.join(ROOT, "data/verification/audit_history.jsonl")
    if os.path.exists(ap):
        rows = [json.loads(x) for x in open(ap, encoding="utf-8") if x.strip()]
        rows = [r for r in rows if r.get("checked", 0) >= 300]
        if rows:
            h["audit"] = rows[-1]
    return h


def audit_line(a):
    import datetime as _dt
    d = _dt.date.fromisoformat(a["date"]).strftime("%B %Y")
    pct = lambda x: f"{x * 100:.1f}".rstrip("0").rstrip(".")  # noqa: E731
    return (f"How accurate is this? In our latest independent audit ({d}), {a['checked']} randomly picked labels "
            f"were re-read against the package: {pct(a['rate'])}% had at least one error "
            f"(95% range {pct(a['ci95'][0])} to {pct(a['ci95'][1])}%). We correct what the evidence confirms, and we audit again every month.")


def patch_index(html, h):
    def sub(label, value, s):
        new, n = re.subn(r"(<b>)[\d,]+(</b><span>" + re.escape(label) + r")", r"\g<1>" + f"{value:,}" + r"\2", s)
        if n != 1:
            raise SystemExit(f"index.html: stat '{label}' not found exactly once")
        return new
    html = sub("FDA-registered sunscreens, checked", h["read"], html)
    html = sub("mineral sunscreens list a possible SPF booster as an inactive", h["booster"], html)
    html = sub("with a recall on record", h["recall"], html)
    html, n = re.subn(r"(I checked all )[\d,]+( FDA-registered sunscreen labels)", r"\g<1>" + f"{h['read']:,}" + r"\2", html)
    if n != 1:
        raise SystemExit("index.html: intro count not found exactly once")
    if h.get("audit"):
        html, n = re.subn(r'(<p class="audit[^"]*"[^>]*>)[^<]*(</p>)', lambda m: m.group(1) + audit_line(h["audit"]) + m.group(2), html)
        if n != 1:
            raise SystemExit("index.html: audit line not found exactly once")
    html = re.sub(r"[\d,]+ sunscreens · (?:3-tier )?rules v[\d.]+", f"{h['read']:,} sunscreens · rules "
                  + RULES_VERSION.split(" ")[0], html)
    return html


def evidence(site_dir):
    """The card's evidence: every sentence a parent reads, each with its source (data/reference)."""
    ref = os.path.join(ROOT, "data/reference")
    out = {"lib": json.load(open(os.path.join(ref, "evidence_library.json"), encoding="utf-8")),
           "uvs": json.load(open(os.path.join(ref, "uv_absorber_status.json"), encoding="utf-8")),
           "nea": json.load(open(os.path.join(ref, "nea_exclusion.json"), encoding="utf-8"))["names"]}
    lim_p = os.path.join(os.path.dirname(site_dir), "evidence", "data.json")
    if os.path.exists(lim_p):
        lim = {}
        for g in json.load(open(lim_p, encoding="utf-8"))["ingredients"]:
            row = {"slug": g["slug"], "name": g["name"], "aka": g.get("also_known_as") or [],
                   "l": [[x["jurisdiction"], x["status"], x.get("max_percent"), x.get("notes"),
                          (x.get("source") or {}).get("url"), (x.get("source") or {}).get("title"),
                          [[c.get("applies_to"), c.get("max_percent")] for c in x.get("conditions") or []]] for x in g["limits"]]}
            lim[g["matrix_key"]] = row
        # UV filters some US labels file as actives that the evidence pages do not cover yet: the US status
        # (not in FDA's monograph), the EU status (Annex VI, checked 2026-10-26); Australia not checked here
        S = out["lib"]["sources"]
        us = ["US", "not_listed", None, None, S["fda_m020"]["url"], S["fda_m020"]["title"], []]
        eu = lambda st, mx, src="eu_annex_vi": ["EU", st, mx, None, S[src]["url"], S[src]["title"], []]  # noqa: E731
        au = ["AU", "not_checked", None, None, None, None, []]
        for key, name, aka, e in [
                ("DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE", "DHHB", ["DHHB"], eu("permitted", 10.0)),
                ("METHYLENE BIS BENZOTRIAZOLYL TETRAMETHYLBUTYLPHENOL", "Bisoctrizole", ["BISOCTRIZOLE"], eu("permitted", 10.0)),
                ("DIETHYLHEXYL BUTAMIDO TRIAZONE", "Iscotrizinol", ["ISCOTRIZINOL"], eu("permitted", 10.0)),
                ("ISOAMYL P METHOXYCINNAMATE", "Amiloxate", ["AMILOXATE", "ISOAMYL METHOXYCINNAMATE", "ISOPENTYL 4 METHOXYCINNAMATE"], eu("permitted", 10.0)),
                ("POLYSILICONE 15", "Polysilicone-15", ["DIMETHICODIETHYLBENZALMALONATE"], eu("permitted", 10.0)),
                ("ENZACAMENE", "Enzacamene (4-MBC)", ["4 METHYLBENZYLIDENE CAMPHOR", "3 4 METHYLBENZYLIDENE CAMPHOR"], eu("removed", None, "eu_2024_996")),
                ("ETHYL METHOXYCINNAMATE", "Ethyl methoxycinnamate", [], eu("not_listed", None))
                ]:
            if key not in lim:
                a_ = ["AU", "permitted", 4.0, "under TGA safety review (2026)", S["tga_4mbc_2026"]["url"], S["tga_4mbc_2026"]["title"], []] if key == "ENZACAMENE" else au
                lim[key] = {"slug": None, "name": name, "aka": aka, "l": [us, e, a_]}
        for key, extra in (("TITANIUM DIOXIDE", ["CI 77891"]), ("ZINC OXIDE", ["CI 77947"])):
            if key in lim:
                lim[key]["aka"] = lim[key]["aka"] + extra
        out["limits"] = lim
    p = os.path.join(site_dir, "evidence.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", p)


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
    db = build(a.release, os.path.join(os.path.dirname(idx_p), "p") if idx_p else None)
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
        evidence(os.path.dirname(idx_p))
        # the Sunscreen Check's own page (arwhouse.com/sunscreen-check) carries the same numbers
        chk = os.path.join(os.path.dirname(os.path.dirname(idx_p)), "sunscreen-check/index.html")
        if os.path.exists(chk):
            c = open(chk, encoding="utf-8").read()
            open(chk, "w", encoding="utf-8").write(patch_index(c, h))
            print("rewrote the headline numbers in", chk)


if __name__ == "__main__":
    main()
