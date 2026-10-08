#!/usr/bin/env python3
"""Summarise a capped (smoke) scraper run for review: how many records got each
new label field, the label checks found, and the actives corrected. Writes
data/smoke/summary.json (the only thing a smoke run commits)."""
import collections, json, os, sys
m = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "output/tinysafe_dailymed_v2_master.json"))
prods = m.get("products", m)
n = len(prods)
fill = {k: sum(1 for p in prods if p.get(k) not in (None, "", [], {})) for k in
        ("dosage_form", "labeler", "spl_version", "effective_date", "monograph_id", "printed_actives",
         "printed_inactives", "label_flags", "label_parse_error", "label_actives_proposal")}
checks = collections.Counter(c["type"] for p in prods for c in p.get("label_checks") or [])
flags = collections.Counter(k for p in prods for k, v in (p.get("label_flags") or {}).items() if v)
corr = [{"setid": p["setid"], "title": p["title"][:90],
         "filed": [(a.get("name"), a.get("percent_ww")) for a in p["active_ingredients"]],
         "label": [(a.get("name"), a.get("percent_ww")) for a in p["label_actives_proposal"]]}
        for p in prods if p.get("label_actives_proposal")]
pc = collections.Counter(p.get("product_count") for p in prods)
os.makedirs("data/smoke", exist_ok=True)
json.dump({"records": n, "filled": fill, "checks": checks, "flags_true": flags, "product_count": pc,
           "corrections": corr[:200]}, open("data/smoke/summary.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps({"records": n, "filled": fill, "checks": checks, "corrections": len(corr)}, indent=1))
