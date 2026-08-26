#!/usr/bin/env python3
"""
TinySafe DailyMed Scraper v2.2
==============================
INGREDIENT-BASED search (not keyword). Collects every SPL whose ACTIVE ingredient
matches one of the UV-filter UNII seeds — regardless of "baby"/"mineral" wording.
This is what pulls in adult/family mineral sunscreens (Native, Vanicream, EltaMD)
that the old keyword scraper missed.

v2.2 — THE NET IS NO LONGER MINERAL-ONLY.
Seeds are read from data/reference/uv_filter_uniis.json, produced by
scripts/resolve_uniis.py, which resolves UV-filter NAMES to UNII codes against
DailyMed's own /uniis service. Codes are never typed by hand: a wrong UNII
returns zero SPLs, which is indistinguishable from "this filter is not used in
the US". If the seed file is missing or unusable the scraper falls back to the
two mineral codes, so a widening attempt can fail without stopping collection.

Why widen: chemical-only sunscreens were structurally uncollectable, so this
dataset could never compute a mineral-vs-chemical market share — the denominator
did not exist. It also means a filter entering or leaving the market (FDA
proposed order OTC000039 would add bemotrizinol to Monograph M020) would be
invisible. A before/after needs the "before" collected now.

Pipeline:
  Phase A  search  : /v2/spls.json?unii_code=<UNII> for every seed, paginated
  Phase B  dedup   : union of setids across all UNII searches
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

# ---------------------------------------------------------------------------
# Search seeds (FDA Unique Ingredient Identifiers)
#
# Resolved by scripts/resolve_uniis.py from DailyMed's own /uniis service and
# written to data/reference/uv_filter_uniis.json. Never typed by hand.
# The two mineral codes are the fallback AND are always kept in the seed set,
# so widening the net can never accidentally shrink it.
# ---------------------------------------------------------------------------
UNII_SEED_FILE = os.path.join("data", "reference", "uv_filter_uniis.json")
UNII_FALLBACK = {"SOI2LOH54Z": "ZINC OXIDE", "15FIX9V2JP": "TITANIUM DIOXIDE"}


def _load_unii_seeds():
    """Read resolved seeds; fall back to mineral-only on any problem."""
    try:
        with open(UNII_SEED_FILE, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"[UNII] no seed file at {UNII_SEED_FILE} -> mineral-only fallback "
              "(run scripts/resolve_uniis.py to widen the net)", flush=True)
        return dict(UNII_FALLBACK)
    except Exception as e:
        print(f"[UNII] seed file unreadable ({e}) -> mineral-only fallback", flush=True)
        return dict(UNII_FALLBACK)

    seeds = {}
    for row in doc.get("filters", []):
        if row.get("status") in ("ok", "single_inexact") and row.get("unii"):
            seeds[row["unii"]] = row.get("unii_name") or row.get("query")

    if len(seeds) < 2:
        print(f"[UNII] seed file has {len(seeds)} usable code(s) -> mineral-only "
              "fallback", flush=True)
        return dict(UNII_FALLBACK)

    for code, name in UNII_FALLBACK.items():
        seeds.setdefault(code, name)      # minerals are never dropped

    skipped = [r["query"] for r in doc.get("filters", [])
               if r.get("status") not in ("ok", "single_inexact")]
    print(f"[UNII] {len(seeds)} search seeds (resolved {doc.get('resolved_on')})",
          flush=True)
    if skipped:
        print(f"[UNII] {len(skipped)} unresolved, NOT searched: "
              f"{', '.join(skipped[:12])}{' ...' if len(skipped) > 12 else ''}",
          flush=True)
    return seeds


UNII = _load_unii_seeds()
UNII_CODESYSTEM = "2.16.840.1.113883.4.9"  # SPL에서 UNII를 나타내는 OID

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


# ---------- Phase C: active ingredients (UNII 포함) ----------
def fetch_active(setid):
    """SPL XML 1차(UNII 확보) → packaging.json 보조. 반환 [{name,strength,unii}]."""
    xml = http_xml(f"{BASE}/spls/{setid}.xml")
    if xml:
        actives = _parse_ingredients_xml(xml, want_active=True)
        if actives:
            return actives
    d = http_json(f"{BASE}/spls/{setid}/packaging.json")
    actives, seen = [], set()
    if not d:
        return actives
    def walk(node):
        if isinstance(node, dict):
            for key in ("active_ingredients", "active_ingredient"):
                if key in node and isinstance(node[key], list):
                    for ing in node[key]:
                        nm = (ing.get("name") or ing.get("active_moiety_name") or "").strip().upper()
                        st = (ing.get("strength") or ing.get("active_numerator_strength") or "")
                        un = ing.get("unii") or ing.get("active_moiety_unii")
                        if nm and nm not in seen:
                            seen.add(nm); actives.append({"name": nm, "strength": str(st), "unii": un})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(d)
    return actives


# ---------- inactive 텍스트 분해 헬퍼 (openFDA 보조용) ----------
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


# ---------- SPL XML 성분 파서 (UNII 추출 핵심) ----------
def _parse_ingredients_xml(xml, want_active):
    """<ingredient classCode> 블록에서 name + UNII 추출. 정규식 기반(기존 스타일 유지)."""
    classcodes = r"(?:ACTIB|ACTIM|ACTIR)" if want_active else r"IACT"
    pattern = r'<ingredient[^>]*classCode="' + classcodes + r'"[^>]*>(.*?)</ingredient>'
    blocks = re.findall(pattern, xml, re.DOTALL | re.IGNORECASE)
    out, seen = [], set()
    for b in blocks:
        m = re.search(r"<name>(.*?)</name>", b, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        nm = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        if not nm or nm in seen:
            continue
        unii = None
        for cm in re.finditer(r"<code\b[^>]*>", b, re.IGNORECASE):
            tag = cm.group(0)
            if UNII_CODESYSTEM in tag:
                um = re.search(r'code="([^"]+)"', tag)
                if um:
                    unii = um.group(1); break
        rec = {"name": nm, "unii": unii}
        if want_active:
            sm = re.search(r'<numerator[^>]*value="([^"]+)"', b, re.IGNORECASE)
            if sm:
                rec["strength"] = sm.group(1)
        seen.add(nm); out.append(rec)
    return out


# ---------- Phase D: inactive ingredients (XML 1차로 뒤집음, UNII 확보) ----------
def fetch_inactive_xml(setid):
    """SPL XML에서 IACT 성분 + UNII. 반환 (list[{name,unii}], 'spl_xml') 또는 ([], None)."""
    xml = http_xml(f"{BASE}/spls/{setid}.xml")
    if not xml:
        return [], None
    items = _parse_ingredients_xml(xml, want_active=False)
    return (items, "spl_xml") if items else ([], None)


def fetch_inactive_openfda(setid):
    """openFDA 보조(텍스트라 UNII 없음 → None). 반환 (list[{name,unii=None}], 'openfda') 또는 ([], None)."""
    d = http_json(f"{OPENFDA}?search=set_id:{setid}&limit=1")
    if not d or not d.get("results"):
        return [], None
    res = d["results"][0]
    raw = res.get("inactive_ingredient") or []
    names = []
    for blob in raw:
        names += _split_list(blob)
    items = [{"name": n, "unii": None} for n in names]
    return (items, "openfda") if items else ([], None)


def fetch_inactive(setid):
    """UNII 확보 우선: XML(1차) → openFDA(보조). 기존과 우선순위 뒤집힘."""
    items, src = fetch_inactive_xml(setid)
    if items:
        return items, src
    time.sleep(0.2)
    items, src = fetch_inactive_openfda(setid)
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
    inact_names = [i["name"] if isinstance(i, dict) else i for i in inact]
    rec["has_hidden_chemical_filter"] = has_any(inact_names, HIDDEN_FILTERS)
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
            "scraper_version": "2.2",
            "search_method": "ingredient_unii",
            "unii_searched": UNII,
            "unii_seed_source": ("resolved_file" if UNII != UNII_FALLBACK
                                 else "mineral_fallback"),
            "net_caveat": ("Active-ingredient UNII search. Any sunscreen whose "
                           "actives are all outside the seed set is NOT collected, "
                           "so market-share figures are only valid for filters in "
                           "'unii_searched'."),
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
