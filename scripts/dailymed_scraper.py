#!/usr/bin/env python3
"""
TinySafe DailyMed Scraper v2.0
==============================
INGREDIENT-BASED search (not keyword). Collects every SPL whose ACTIVE ingredient
contains Zinc Oxide and/or Titanium Dioxide — regardless of "baby"/"mineral" wording.
This is what pulls in adult/family mineral sunscreens (Native, Vanicream, EltaMD)
that the old keyword scraper missed.

Pipeline:
  Phase A  search  : /v2/spls.json?unii_code=<UNII>  (ZnO=SOI2LOH54Z, TiO2=15FIX9V2JP), paginated
  Phase B  dedup   : union of setids across both UNII searches
  Phase C  active  : /v2/spls/{setid}/packaging.json  → active ingredients (name + strength)
  Phase D  inactive: openFDA (primary) → SPL XML IACT classCode (fallback)  [active never leaks]
  Phase E  enrich  : SPF parse, mineral_type, chemical/hidden-filter flags, baby_labeled, category
  Phase F  output  : raw master (everything) + sunscreen-filtered mineral file

Outputs:
  output/tinysafe_dailymed_v2_master.json      — ALL collected SPLs (raw, incl. chemical / non-sunscreen)
  output/tinysafe_dailymed_v2_mineral_sun.json — filtered: sunscreen + mineral(ZnO/ZnO+TiO2) + no chemical filter
"""

import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request, urllib.error

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
OPENFDA = "https://api.fda.gov/drug/label.json"
UA = {"User-Agent": "TinySafe-research/2.0 (contact: support@tinysafe.app)"}

# UNII codes (FDA Unique Ingredient Identifiers)
UNII = {"SOI2LOH54Z": "ZINC OXIDE", "15FIX9V2JP": "TITANIUM DIOXIDE"}

CHEMICAL_FILTERS = [
    "AVOBENZONE", "OXYBENZONE", "OCTINOXATE", "OCTYL METHOXYCINNAMATE", "OCTISALATE",
    "OCTYL SALICYLATE", "HOMOSALATE", "OCTOCRYLENE", "ENSULIZOLE", "MEXORYL",
    "MERADIMATE", "PADIMATE", "SULISOBENZONE", "DIOXYBENZONE", "CINOXATE", "TROLAMINE SALICYLATE",
]
# salicylate texture/SPF boosters that read as "mineral" but absorb UV (transparency flag)
HIDDEN_FILTERS = ["BUTYLOCTYL SALICYLATE", "TRIDECYL SALICYLATE", "ETHYL FERULATE"]
BABY_WORDS = ["BABY", "BABIES", "KIDS", "KID", "INFANT", "NEWBORN", "TODDLER", "PEDIATRIC", "CHILDREN"]


def http_json(url, tries=4, backoff=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(backoff * (i + 1)); continue
            if i < tries - 1:
                time.sleep(backoff * (i + 1)); continue
            return None
        except Exception:
            if i < tries - 1:
                time.sleep(backoff * (i + 1)); continue
            return None
    return None


def http_xml(url, tries=4, backoff=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i < tries - 1:
                time.sleep(backoff * (i + 1)); continue
            return None
        except Exception:
            if i < tries - 1:
                time.sleep(backoff * (i + 1)); continue
            return None
    return None


# ---------- Phase A: ingredient (UNII) search ----------
def search_by_unii(unii, limit=0):
    """Return list of {setid,title} for all SPLs containing this UNII active ingredient."""
    out, page, pagesize = [], 1, 100
    while True:
        url = f"{BASE}/spls.json?unii_code={unii}&pagesize={pagesize}&page={page}"
        d = http_json(url)
        if not d:
            break
        rows = d.get("data", []) or []
        for x in rows:
            out.append({"setid": x.get("setid"), "title": x.get("title", "")})
        meta = d.get("metadata", {}) or {}
        total_pages = int(meta.get("total_pages", page) or page)
        if limit and len(out) >= limit:
            out = out[:limit]; break
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)
    return out


# ---------- Phase C: active ingredients ----------
def fetch_active(setid):
    """packaging.json → list of {name, strength}. Returns [] on failure."""
    d = http_json(f"{BASE}/spls/{setid}/packaging.json")
    actives, seen = [], set()
    if not d:
        return actives
    # walk the structure defensively (shape varies); collect active_moiety/ingredient names
    def walk(node):
        if isinstance(node, dict):
            # common shapes: {"active_ingredients":[{"name":..,"strength":..}]}
            for key in ("active_ingredients", "active_ingredient"):
                if key in node and isinstance(node[key], list):
                    for ing in node[key]:
                        nm = (ing.get("name") or ing.get("active_moiety_name") or "").strip().upper()
                        st = (ing.get("strength") or ing.get("active_numerator_strength") or "")
                        if nm and nm not in seen:
                            seen.add(nm); actives.append({"name": nm, "strength": str(st)})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(d)
    return actives


# ---------- Phase D: inactive ingredients (2-tier) ----------
SECTION_STOP = re.compile(
    r"\b(Active|Sun\s+Protection|Warnings|Directions|Other\s+Information|Questions|"
    r"Stop\s+use|Keep\s+out|Storage|Manufactured|Distributed|Purpose|Uses)\b", re.IGNORECASE)


def _split_list(text):
    text = re.sub(r"^\s*Inactive\s+ingredients?\s*:?\s*", "", text, flags=re.IGNORECASE).strip()
    parts = re.split(r"[;,\u2022\n]+", text)
    out, seen = [], set()
    for p in parts:
        p = re.sub(r"\(.*?\)", "", p).strip().upper()
        p = re.sub(r"\s+", " ", p).strip(" .")
        if p and len(p) > 1 and p not in seen and not SECTION_STOP.match(p):
            seen.add(p); out.append(p)
    return out


def fetch_inactive_openfda(setid):
    """openFDA (already-parsed). Returns (list, 'openfda') or ([], None)."""
    d = http_json(f"{OPENFDA}?search=set_id:{setid}&limit=1")
    if not d or not d.get("results"):
        return [], None
    res = d["results"][0]
    raw = res.get("inactive_ingredient") or []
    items = []
    for blob in raw:
        items += _split_list(blob)
    return (items, "openfda") if items else ([], None)


def fetch_inactive_xml(setid):
    """SPL XML: parse <ingredient classCode="IACT"> substance names. active (ACTIB/ACTIM) excluded."""
    xml = http_xml(f"{BASE}/spls/{setid}.xml")
    if not xml:
        return [], None
    # IACT = inactive ingredient (FDA SPL standard). Capture the substance <name> within.
    blocks = re.findall(r'<ingredient[^>]*classCode="IACT"[^>]*>(.*?)</ingredient>', xml, re.DOTALL | re.IGNORECASE)
    out, seen = [], set()
    for b in blocks:
        m = re.search(r"<name>(.*?)</name>", b, re.DOTALL | re.IGNORECASE)
        if m:
            nm = re.sub(r"\s+", " ", m.group(1)).strip().upper()
            if nm and nm not in seen:
                seen.add(nm); out.append(nm)
    return (out, "spl_xml") if out else ([], None)


def fetch_inactive(setid):
    items, src = fetch_inactive_openfda(setid)
    if items:
        return items, src
    time.sleep(0.2)
    items, src = fetch_inactive_xml(setid)
    return items, (src or "empty")


# ---------- Phase E: enrichment ----------
def parse_spf(title, *texts):
    for t in [title, *texts]:
        if not t:
            continue
        m = re.search(r"SPF\s*([0-9]{1,3})", t, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if 2 <= v <= 110:
                return v
    return None


def has_any(ings, keys):
    up = [i.upper() for i in ings]
    return any(any(k in i for k in keys) for i in up)


# color-cosmetic / makeup terms — excluded from "sunscreen" even if they carry SPF
MAKEUP_TERMS = [
    "FOUNDATION", "BB CREAM", "CC CREAM", "CUSHION", "BLUSH", "CONCEALER",
    "PRIMER", "SETTING", "POWDER", "LIPSTICK", "LIP TINT", "MASCARA",
    "EYESHADOW", "BRONZER", "HIGHLIGHTER", "TINTED",
]


def categorize(title, dosage, actives, has_spf):
    """A product is 'sunscreen' if it has SPF (or sunscreen wording) AND is not a color cosmetic.
    SPF moisturizers / day creams count as sunscreen (function-first). Tinted/makeup excluded
    (tinted is also hard-gated downstream)."""
    t = (title + " " + (dosage or "")).upper()
    is_makeup = any(m in t for m in MAKEUP_TERMS)
    looks_like_sunscreen = has_spf or "SUNSCREEN" in t or "SUNBLOCK" in t or "SUN LOTION" in t
    if "DIAPER" in t or "RASH" in t:
        return "diaper_cream"
    if "CALAMINE" in t:
        return "calamine"
    if "LIP" in t and "BALM" in t:
        return "lip_balm"
    if is_makeup:
        return "makeup"          # color cosmetic — excluded from sunscreen filter
    if looks_like_sunscreen:
        return "sunscreen"
    return "other"


def enrich(rec):
    title = rec.get("title", "")
    actives = rec.get("active_ingredients", [])
    inact = rec.get("inactive_ingredients", [])
    act_names = [a["name"] for a in actives]
    zno = has_any(act_names, ["ZINC OXIDE"])
    tio2 = has_any(act_names, ["TITANIUM DIOXIDE"])
    chem = has_any(act_names, CHEMICAL_FILTERS)
    spf = parse_spf(title, rec.get("dosage_form", ""))
    cat = categorize(title, rec.get("dosage_form", ""), act_names, spf is not None)
    rec["spf"] = spf
    rec["contains_zinc_oxide"] = zno
    rec["contains_titanium_dioxide"] = tio2
    rec["contains_chemical_filter"] = chem
    rec["has_hidden_chemical_filter"] = has_any(inact, HIDDEN_FILTERS)
    rec["mineral_type"] = ("zinc_titanium" if (zno and tio2) else "zinc" if zno
                           else "titanium" if tio2 else "none")
    rec["is_hundred_percent_mineral"] = (zno and not chem and not rec["has_hidden_chemical_filter"])
    rec["baby_labeled"] = any(w in title.upper() for w in BABY_WORDS)
    rec["category"] = cat
    return rec


def process_setid(item):
    setid = item["setid"]
    title = item.get("title", "")
    if not setid:
        return None
    actives = fetch_active(setid)
    inact, src = fetch_inactive(setid)
    # try to read dosage form from the title bracket if present
    rec = {
        "setid": setid,
        "title": title,
        "product_name": re.sub(r"\s*\[.*?\]\s*$", "", title).strip(),
        "active_ingredients": actives,
        "inactive_ingredients": inact,
        "inactive_source": src,
        "inactive_count": len(inact),
        "dailymed_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
    }
    return enrich(rec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap setids per UNII (0=all; use 10 for smoke test)")
    ap.add_argument("--parallel", type=int, default=5)
    ap.add_argument("--output-dir", default="output")
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # Phase A + B
    setid_map = {}
    for unii, name in UNII.items():
        print(f"[A] searching UNII {unii} ({name}) ...", flush=True)
        rows = search_by_unii(unii, limit=args.limit)
        print(f"    found {len(rows)}", flush=True)
        for r in rows:
            if r["setid"] and r["setid"] not in setid_map:
                setid_map[r["setid"]] = r
    items = list(setid_map.values())
    print(f"[B] unique setids: {len(items)}", flush=True)

    # Phase C+D+E (parallel)
    records = []
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(process_setid, it): it for it in items}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            if r:
                records.append(r)
            done += 1
            if done % 50 == 0:
                print(f"    processed {done}/{len(items)}", flush=True)

    # Phase F: outputs
    master_path = os.path.join(args.output_dir, "tinysafe_dailymed_v2_master.json")
    src_counts = {}
    for r in records:
        src_counts[r["inactive_source"]] = src_counts.get(r["inactive_source"], 0) + 1
    master = {
        "metadata": {
            "scraper_version": "2.1",
            "search_method": "ingredient_unii",
            "unii_searched": UNII,
            "total_products": len(records),
            "inactive_source_breakdown": src_counts,
            "mineral_type_breakdown": _count(records, "mineral_type"),
            "with_spf": sum(1 for r in records if r.get("spf")),
            "chemical_filter": sum(1 for r in records if r.get("contains_chemical_filter")),
            "baby_labeled": sum(1 for r in records if r.get("baby_labeled")),
        },
        "products": records,
    }
    json.dump(master, open(master_path, "w"), ensure_ascii=False, indent=1)
    print(f"[F] master → {master_path} ({len(records)})", flush=True)

    # mineral sunscreen filtered: sunscreen + ZnO present + no chemical filter
    mineral = [r for r in records
               if r.get("category") == "sunscreen"
               and r.get("contains_zinc_oxide")
               and not r.get("contains_chemical_filter")]
    mineral_path = os.path.join(args.output_dir, "tinysafe_dailymed_v2_mineral_sun.json")
    json.dump({"metadata": {"count": len(mineral), "filter": "sunscreen + ZnO + no_chemical_filter"},
               "products": mineral}, open(mineral_path, "w"), ensure_ascii=False, indent=1)
    print(f"[F] mineral sunscreen → {mineral_path} ({len(mineral)})", flush=True)

    # quick health report
    empty = src_counts.get("empty", 0)
    print(f"\n--- HEALTH ---")
    print(f"inactive source: {src_counts}")
    print(f"inactive MISSING (empty): {empty} ({round(100*empty/max(len(records),1))}%)")
    print(f"with SPF: {master['metadata']['with_spf']} | baby_labeled: {master['metadata']['baby_labeled']}")


def _count(records, field):
    out = {}
    for r in records:
        out[r.get(field)] = out.get(r.get(field), 0) + 1
    return out


if __name__ == "__main__":
    main()
