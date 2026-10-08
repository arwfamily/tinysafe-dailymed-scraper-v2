#!/usr/bin/env python3
"""
build_evidence.py — generate site/evidence.json for the arwhouse.com evidence
pages, exactly in the shape defined by docs/SITE_DATA_CONTRACT.md.

Inputs (read-only):
  data/views/jurisdiction_matrix.json   regulatory limits, per-cell sources
  claims/claim_ledger.json              registry measurements; only claims
                                        with status == "verified" are emitted

The site renders this file and nothing else. Every number on a page traces
to a cell here, and every cell carries the URL of the document that states it.

  python scripts/build_evidence.py            # writes site/evidence.json
  python scripts/build_evidence.py --check    # validate only, non-zero on any violation
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX = os.path.join(ROOT, "data", "views", "jurisdiction_matrix.json")
LEDGER = os.path.join(ROOT, "claims", "claim_ledger.json")
OUT = os.path.join(ROOT, "site", "evidence.json")

# The 20 filters on the v1 pages, in page order. slug -> (display name, matrix key, role)
INGREDIENTS = [
    ("zinc-oxide", "Zinc Oxide", "ZINC OXIDE", "uv_filter_mineral"),
    ("titanium-dioxide", "Titanium Dioxide", "TITANIUM DIOXIDE", "uv_filter_mineral"),
    ("bemotrizinol", "Bemotrizinol", "BEMOTRIZINOL", "uv_filter_organic"),
    ("avobenzone", "Avobenzone", "AVOBENZONE", "uv_filter_organic"),
    ("oxybenzone", "Oxybenzone", "OXYBENZONE", "uv_filter_organic"),
    ("octinoxate", "Octinoxate", "OCTINOXATE", "uv_filter_organic"),
    ("homosalate", "Homosalate", "HOMOSALATE", "uv_filter_organic"),
    ("octisalate", "Octisalate", "OCTISALATE", "uv_filter_organic"),
    ("octocrylene", "Octocrylene", "OCTOCRYLENE", "uv_filter_organic"),
    ("ensulizole", "Ensulizole", "ENSULIZOLE", "uv_filter_organic"),
    ("meradimate", "Meradimate", "MERADIMATE", "uv_filter_organic"),
    ("dioxybenzone", "Dioxybenzone", "DIOXYBENZONE", "uv_filter_organic"),
    ("sulisobenzone", "Sulisobenzone", "SULISOBENZONE", "uv_filter_organic"),
    ("cinoxate", "Cinoxate", "CINOXATE", "uv_filter_organic"),
    ("padimate-o", "Padimate O", "PADIMATE O", "uv_filter_organic"),
    ("paba", "PABA (Aminobenzoic Acid)", "AMINOBENZOIC ACID", "uv_filter_organic"),
    ("trolamine-salicylate", "Trolamine Salicylate", "TROLAMINE SALICYLATE", "uv_filter_organic"),
    ("ecamsule", "Ecamsule", "ECAMSULE", "uv_filter_organic"),
    ("drometrizole-trisiloxane", "Drometrizole Trisiloxane", "DROMETRIZOLE TRISILOXANE", "uv_filter_organic"),
    ("ethylhexyl-triazone", "Ethylhexyl Triazone", "ETHYLHEXYL TRIAZONE", "uv_filter_organic"),
]

# Jurisdictions published in v1, and the document that is the complete
# positive list for each (absence from a complete list = "not_listed").
JURISDICTIONS = {
    "US": {"title": "FDA OTC Monograph M020 (Sunscreen Drug Products for OTC Human Use)",
           "url": "https://www.accessdata.fda.gov/drugsatfda_docs/omuf/monographs/OTCMonograph_M020-SunscreenDrugProductsforOTCHumanUse09242021.pdf",
           "version": "Final Administrative Order OTC000006, posted 2021-09-24, as amended by OTC000039"},
    "EU": {"title": "Regulation (EC) No 1223/2009, Annex VI (UV filters)",
           "url": "https://webgate.ec.europa.eu/reqs2/public/v2/requirement/auxi/eu/32009R1223_spcosmet_annex_6.pdf",
           "version": "consolidated text 02009R1223, 038.001 (2025-05-01)"},
    "AU": {"title": "Therapeutic Goods (Permissible Ingredients) Determination (No. 2) 2026",
           "url": "https://www.legislation.gov.au/F2026L00707/asmade",
           "version": "F2026L00707, commenced 2026-06-12"},
}
# KR is deliberately absent: the extract is partial and unverified secondary.

STATUSES = {"permitted", "permitted_with_conditions", "approved_product_only",
            "removal_finalized_not_yet_effective", "removed", "not_listed",
            "listed_no_numeric_limit"}


def _commit():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def _fmt(x):
    return f"{x:g}%"


def cell(juris, entry, built_on):
    """One jurisdiction cell in contract shape."""
    doc = JURISDICTIONS[juris]
    if entry is None:
        return {"jurisdiction": juris, "status": "not_listed", "max_percent": None,
                "conditions": [],
                "source": {"title": doc["title"], "url": doc["url"],
                           "version": doc["version"], "data_as_of": built_on}}
    st = entry.get("status")
    cond_limits = entry.get("conditional_limits")
    mx = entry.get("max_percent")
    if st in ("removal_finalized_not_yet_effective", "removed", "approved_product_only"):
        status = st
    elif cond_limits:
        status = "permitted_with_conditions"
    elif mx is not None:
        status = "permitted"
    else:
        status = "listed_no_numeric_limit"
    conditions = []
    for c in cond_limits or []:
        conditions.append({"applies_to": c["applies_to"], "max_percent": c["max_percent"]})
    out = {"jurisdiction": juris, "status": status, "max_percent": mx,
           "conditions": conditions,
           # AU "requirements" is the whole legal paragraph for every use of
           # the ingredient (e.g. zinc oxide's ORAL-dose warnings). Shown on a
           # sunscreen page it would mislead, so AU text is reachable through
           # the source link only, never rendered as a note.
           "notes": (None if juris == "AU" else (entry.get("conditions") or None)),
           "source": {"title": entry.get("source") or doc["title"],
                      "url": entry.get("source_url") or doc["url"],
                      "version": entry.get("source_version") or doc["version"],
                      "data_as_of": built_on}}
    if entry.get("source_status"):
        out["source"]["status"] = entry["source_status"]
    if status == "removal_finalized_not_yet_effective":
        out["effective_date"] = entry.get("removal_effective")
        out["status_source_url"] = entry.get("status_source_url")
    if status == "removed":
        out["removed_on"] = entry.get("removed_on")
        out["status_source_url"] = entry.get("status_source_url")
    return out


SPOKEN = {"US": "the US", "EU": "the EU", "AU": "Australia"}
LIST_IN = {"US": "the US", "EU": "the EU", "AU": "Australia"}


def summary(name, cells):
    """One sentence, numbers only from the cells. Conditional rows give no
    single number, so they are described, never collapsed into one."""
    parts = []
    for c in cells:
        j = SPOKEN[c["jurisdiction"]]
        s = c["status"]
        if s == "permitted":
            parts.append(f"up to {_fmt(c['max_percent'])} in {j}")
        elif s == "permitted_with_conditions":
            parts.append(f"limits in {j} depend on product type")
        elif s == "listed_no_numeric_limit":
            parts.append(f"permitted in {j} with no numeric limit")
        elif s == "approved_product_only":
            parts.append(f"allowed in {j} only in specifically approved products")
        elif s == "removal_finalized_not_yet_effective":
            parts.append(f"removal from the permitted list in {LIST_IN[c['jurisdiction']]} finalized, effective {c['effective_date']}")
        elif s == "removed":
            parts.append(f"removed in {j} on {c['removed_on']}")
        elif s == "not_listed":
            parts.append(f"not on the permitted list in {LIST_IN[c['jurisdiction']]}")
    return f"{name}: " + "; ".join(parts) + "."


def registry_claims(ledger, slug):
    out = []
    for c in ledger.get("claims", []):
        if c.get("status") != "verified" or slug not in (c.get("ingredient_slugs") or []):
            continue
        out.append(_registry_item(c))
    return out


def _registry_item(c):
    item = {"id": c["id"], "status": "verified",
            "sentence": c["publishable_sentence"],
            "numerator": c.get("numerator"), "denominator": c.get("denominator"),
            "population": c.get("population"),
            "caveat": c.get("caveat"),
            "source": c.get("site_source")}
    if c.get("legal_framing"):
        item["legal_framing"] = c["legal_framing"]
    return item


def findings(ledger):
    """Verified registry findings that belong to no single filter page
    (e.g. UV absorbers hidden among inactive ingredients)."""
    return [{"finding": c["finding"], **_registry_item(c)}
            for c in ledger.get("claims", [])
            if c.get("status") == "verified" and c.get("finding")]


def build():
    with open(MATRIX, encoding="utf-8") as f:
        mdoc = json.load(f)
    m, built_on = mdoc["matrix"], mdoc["built_on"]
    ledger = {}
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            ledger = json.load(f)
    items = []
    for slug, name, key, role in INGREDIENTS:
        row = m.get(key)
        if row is None:
            raise SystemExit(f"matrix has no row for {key} ({slug})")
        cells = [cell(j, row["limits"].get(j), built_on) for j in JURISDICTIONS]
        items.append({"slug": slug, "name": name, "matrix_key": key,
                      "also_known_as": row.get("also_known_as", []), "role": role,
                      "summary": summary(name, cells),
                      "limits": cells,
                      "registry": registry_claims(ledger, slug)})
    return {"built_on": built_on,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commit": _commit(),
            "contract": "docs/SITE_DATA_CONTRACT.md",
            "jurisdictions": list(JURISDICTIONS),
            "ingredients": items,
            "findings": findings(ledger),
            "registry_population": ledger.get("registry_population")}


def check(doc):
    errors = []
    for it in doc["ingredients"]:
        for c in it["limits"]:
            where = f"{it['slug']}/{c['jurisdiction']}"
            if c["status"] not in STATUSES:
                errors.append(f"{where}: status {c['status']!r} not in contract vocabulary")
            if not (c.get("source") or {}).get("url"):
                errors.append(f"{where}: no source url")
            if c["status"] == "permitted" and c["max_percent"] is None:
                errors.append(f"{where}: permitted without a number")
            if c["status"] == "permitted_with_conditions" and not c["conditions"]:
                errors.append(f"{where}: conditional without conditions")
        for r in it["registry"]:
            if r["status"] != "verified":
                errors.append(f"{it['slug']}: unverified registry claim {r['id']}")
            if not (r.get("source") or {}).get("url") or not r.get("caveat"):
                errors.append(f"{it['slug']}: registry claim {r['id']} lacks source url or caveat")
    for fnd in doc.get("findings", []):
        if fnd["status"] != "verified" or not (fnd.get("source") or {}).get("url"):
            errors.append(f"finding {fnd['id']}: not verified or no source")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    doc = build()
    errors = check(doc)
    for e in errors:
        print("CONTRACT VIOLATION:", e, file=sys.stderr)
    if errors:
        sys.exit(1)
    if a.check:
        print(f"ok: {len(doc['ingredients'])} ingredients, contract checks passed")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    n_reg = sum(len(i["registry"]) for i in doc["ingredients"])
    print(f"wrote {OUT}: {len(doc['ingredients'])} ingredients, "
          f"{sum(len(i['limits']) for i in doc['ingredients'])} cells, {n_reg} verified registry claims, "
          f"{len(doc['findings'])} findings")


if __name__ == "__main__":
    main()
