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
UNII_CODESYSTEM = "2.16.840.1.113883.4.9"  # SPL에서 UNII를 나타내는 OID

CHEMICAL_FILTERS = [
    "AVOBENZONE", "OXYBENZONE", "OCTINOXATE", "OCTYL METHOXYCINNAMATE", "OCTISALATE",
    "OCTYL SALICYLATE", "HOMOSALATE", "OCTOCRYLENE", "ENSULIZOLE", "MEXORYL",
    "MERADIMATE", "PADIMATE", "SULISOBENZONE", "DIOXYBENZONE", "CINOXATE", "TROLAMINE SALICYLATE",
]
# salicylate texture/SPF boosters that read as "mineral" but absorb UV (transparency flag)
HIDDEN_FILTERS = ["BUTYLOCTYL SALICYLATE", "TRIDECYL SALICYLATE", "ETHYL FERULATE",
                  "C12-15 ALKYL BENZOATE", "DIETHYLHEXYL SYRINGYLIDENE MALONATE"]
# NOT a UV filter and NOT a hidden booster: ETHYLHEXYL METHOXYCRYLENE (SolaStay S1).
# It is a photostabilizer; it returns UV filters to their ground state without absorbing
# sunlight, and in mineral sunscreens it quenches ROS from ZnO/TiO2. Keep it off both lists.
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
def fetch_active(setid, xml=None):
    """SPL XML 1차(UNII 확보) → packaging.json 보조. 반환 [{name,strength,percent,unii}]."""
    xml = xml if xml is not None else http_xml(f"{BASE}/spls/{setid}.xml")
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
                            seen.add(nm)
                            actives.append({"name": nm, "strength": None, "percent": None,
                                            "percent_needs_review": True,
                                            "strength_raw": str(st), "unii": un})
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


LOINC_INACTIVE = "51727-6"


# ---------- Track A1: body-text audit, strength units, water resistance ----------


def extract_section_text(xml: str, loinc_code: str) -> str:
    """Return the plain text of the SPL section carrying `loinc_code`, or ''."""
    for m in re.finditer(r"<section\b.*?</section>", xml, re.DOTALL | re.IGNORECASE):
        block = m.group(0)
        if not re.search(r'<code\b[^>]*code="%s"' % re.escape(loinc_code), block, re.IGNORECASE):
            continue
        tm = re.search(r"<text\b.*?</text>", block, re.DOTALL | re.IGNORECASE)
        if not tm:
            continue
        txt = re.sub(r"<[^>]+>", " ", tm.group(0))
        txt = txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return re.sub(r"\s+", " ", txt).strip()
    return ""


def normalize(s: str) -> str:
    """Comparison form: uppercase, alphanumerics only. Survives punctuation drift."""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


# ---------------------------------------------------------------- the auditor

def audit_completeness(xml_names, text_blob):
    """
    Does the structured table account for the body text?

    Returns (verdict, missing_hint) where verdict is one of:
      "table_complete"   — every structured name appears in the text and the text has
                           no obvious surplus content
      "table_incomplete" — the text is materially longer than the table can explain
      "no_text"          — the label has no inactive-ingredient text section

    We deliberately do NOT split the text here. We measure coverage.
    """
    if not text_blob:
        return "no_text", None

    body = normalize(text_blob)
    if not body:
        return "no_text", None

    covered = 0
    for n in xml_names:
        if normalize(n) and normalize(n) in body:
            covered += len(normalize(n))

    # How much of the body text is explained by the structured names?
    # Ingredient lists are almost entirely ingredient names, so a complete table
    # should cover most of the alphanumeric mass. Separators and the leading
    # "Inactive ingredients:" account for the rest.
    lead = normalize("inactive ingredients")
    body_mass = max(len(body) - len(lead), 1)
    coverage = covered / body_mass

    if coverage < 0.70:
        return "table_incomplete", round(coverage, 3)
    return "table_complete", round(coverage, 3)


# ---------------------------------------------------------------- careful splitter

_PROTECT = [
    (re.compile(r"\((.*?)\)"), None),                    # never split inside parentheses
]
_SUFFIXES = {"D-", "DL-", "L-", "USP", "NF", "RANDOMIZED", "MEDIUM CHAIN",
             "HYDROGENATED", "ANHYDROUS", "MONOHYDRATE", "DIHYDRATE"}


def smart_split(text: str):
    """
    Split a free-text inactive-ingredient statement without shredding chemical names.

    Guards, in order:
      - strip a leading "Inactive ingredients:" label
      - mask parenthetical content so its commas are invisible
      - never split a comma that sits between two digits  (1,2-hexanediol)
      - never split a comma whose right-hand fragment is a known name suffix
        (".alpha.-tocopherol acetate, d-"  ·  "triglycerides, medium chain, randomized")
      - prefer semicolons when the statement uses them
    """
    text = re.sub(r"^\s*inactive\s+ingredients?\s*:?\s*", "", text, flags=re.IGNORECASE).strip()
    text = text.rstrip(" .")
    if not text:
        return []

    masked, parens = [], []

    def mask(m):
        parens.append(m.group(0))
        return "\x00%d\x00" % (len(parens) - 1)

    text = re.sub(r"\([^()]*\)", mask, text)

    if text.count(";") >= 2:
        parts = text.split(";")
    else:
        # split on commas that are not numeric-internal
        rough = re.split(r"(?<![0-9]),(?![0-9])", text)
        parts, buf = [], ""
        for p in rough:
            cand = p.strip()
            if buf and cand.upper().rstrip(" .") in _SUFFIXES:
                buf = buf + ", " + cand          # re-join a split-off suffix
                continue
            if buf:
                parts.append(buf)
            buf = cand
        if buf:
            parts.append(buf)

    out, seen = [], set()
    for p in parts:
        for i, orig in enumerate(parens):
            p = p.replace("\x00%d\x00" % i, orig)
        p = re.sub(r"\s+", " ", p).strip(" .").upper()
        if len(p) > 1 and p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ---------------------------------------------------------------- strength + units

def parse_strength(block: str):
    """
    Keep the unit and the denominator. `value` alone is meaningless.
    Returns {"value": float, "unit": str, "per_value": float, "per_unit": str} or None.
    """
    num = re.search(r'<numerator[^>]*value="([^"]+)"[^>]*unit="([^"]*)"', block, re.IGNORECASE)
    if not num:
        num = re.search(r'<numerator[^>]*unit="([^"]*)"[^>]*value="([^"]+)"', block, re.IGNORECASE)
        if num:
            num = type("M", (), {"group": lambda _s, i: num.group(2 if i == 1 else 1)})()
    if not num:
        return None
    den = re.search(r'<denominator[^>]*value="([^"]+)"[^>]*unit="([^"]*)"', block, re.IGNORECASE)
    try:
        v = float(num.group(1))
    except ValueError:
        return None
    rec = {"value": v, "unit": (num.group(2) or "").strip()}
    if den:
        try:
            rec["per_value"] = float(den.group(1))
        except ValueError:
            pass
        rec["per_unit"] = (den.group(2) or "").strip()
    return rec


def to_percent(strength):
    """
    Convert to % w/w only when the units permit it. Otherwise return None and let the
    record carry `needs_review`. Never guess: FDA caps ZnO and TiO2 at 25%.
    """
    if not strength:
        return None
    v, u = strength["value"], strength["unit"].lower()
    pv, pu = strength.get("per_value"), (strength.get("per_unit") or "").lower()

    if u in ("%", "pct"):
        pct = v
    elif u == "mg" and pu == "g" and pv:
        pct = v / (pv * 10.0)              # mg per g  → %
    elif u == "mg" and pu == "ml" and pv:
        pct = v / (pv * 10.0)              # mg per mL → % w/v, close enough, flag it
    elif u == "g" and pu == "g" and pv:
        pct = v / pv * 100.0
    else:
        return None

    return round(pct, 2) if 0 < pct <= 25.0 else None   # out of range → needs_review


# ---------------------------------------------------------------- water resistance

_WR = re.compile(r"water\s*resistant\s*\(?\s*(40|80)\s*minutes?\s*\)?", re.IGNORECASE)


def extract_water_resistance(xml: str):
    """
    The only claims FDA permits are "Water Resistant (40 minutes)" and "(80 minutes)".
    Absence of the phrase means the product made no claim — which is itself the answer.
    Returns 40, 80, or None.
    """
    plain = re.sub(r"<[^>]+>", " ", xml)
    hits = {int(m.group(1)) for m in _WR.finditer(plain)}
    return max(hits) if hits else None



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
            st = parse_strength(b)
            rec["strength"] = st                      # {value, unit, per_value, per_unit} or None
            pct = to_percent(st)
            rec["percent"] = pct
            rec["percent_needs_review"] = (st is not None and pct is None)
        seen.add(nm); out.append(rec)
    return out


# ---------- Phase D: inactive ingredients (XML table -> audited against body text) ----------
def fetch_inactive_xml(setid, xml=None):
    xml = xml if xml is not None else http_xml(f"{BASE}/spls/{setid}.xml")
    if not xml:
        return [], None
    items = _parse_ingredients_xml(xml, want_active=False)
    return (items, "spl_xml") if items else ([], None)


def fetch_inactive_openfda(setid):
    """openFDA 보조(텍스트라 UNII 없음). 반환 (list[{name,unii=None}], 'openfda') 또는 ([], None)."""
    d = http_json(f"{OPENFDA}?search=set_id:{setid}&limit=1")
    if not d or not d.get("results"):
        return [], None
    res = d["results"][0]
    raw = res.get("inactive_ingredient") or []
    names = []
    for blob in raw:
        names += smart_split(blob)
    items = [{"name": n, "unii": None} for n in names]
    return (items, "openfda") if items else ([], None)


def fetch_inactive(setid, xml=None):
    """
    SPL states inactive ingredients twice: the structured <ingredient classCode="IACT">
    table, and the body-text section (LOINC 51727-6). Manufacturers sometimes file an
    incomplete table (Goongbe: 4 in the table, 32 in the text, incl. FRAGRANCE and
    SALIX ALBA). Use the text as an auditor first, a source second.

    Returns (items, source, audit).
    """
    empty_audit = {"ingredients_verified": "openfda_fallback",
                   "table_coverage": None, "inactive_text_raw": ""}
    if not xml:
        items, src = fetch_inactive_openfda(setid)
        return items, (src or "empty"), empty_audit

    table = _parse_ingredients_xml(xml, want_active=False)
    names = [i["name"] for i in table]
    text_blob = extract_section_text(xml, LOINC_INACTIVE)
    verdict, coverage = audit_completeness(names, text_blob)

    if verdict == "table_incomplete":
        by_norm = {normalize(i["name"]): i.get("unii") for i in table}
        items = [{"name": n, "unii": by_norm.get(normalize(n))} for n in smart_split(text_blob)]
        return items, "spl_text", {"ingredients_verified": "spl_text_used",
                                   "table_coverage": coverage, "inactive_text_raw": text_blob}

    if table:
        verified = "spl_table_matches_text" if verdict == "table_complete" else "no_text_section"
        return table, "spl_xml", {"ingredients_verified": verified,
                                  "table_coverage": coverage, "inactive_text_raw": text_blob}

    items, src = fetch_inactive_openfda(setid)
    return items, (src or "empty"), {"ingredients_verified": "openfda_fallback",
                                     "table_coverage": coverage, "inactive_text_raw": text_blob}


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
    xml = http_xml(f"{BASE}/spls/{setid}.xml")     # fetched ONCE, reused three times
    actives = fetch_active(setid, xml)
    inact, src, audit = fetch_inactive(setid, xml)
    rec = {
        "setid": setid,
        "title": title,
        "product_name": re.sub(r"\s*\[.*?\]\s*$", "", title).strip(),
        "active_ingredients": actives,
        "inactive_ingredients": inact,
        "inactive_source": src,
        "inactive_count": len(inact),
        "water_resistance_minutes": extract_water_resistance(xml) if xml else None,
        "dailymed_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
    }
    rec.update(audit)
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
    # Nothing vanishes silently: every sunscreen carries a scope_exclusion_reason (or None).
    # TiO2 is an FDA-approved mineral filter — titanium-only products are IN scope.
    for r in records:
        reason = None
        if r.get("category") != "sunscreen":
            reason = f"Not a sunscreen ({r.get('category')})"
        elif r.get("contains_chemical_filter"):
            reason = "Contains a chemical UV filter — not a mineral sunscreen"
        elif not (r.get("contains_zinc_oxide") or r.get("contains_titanium_dioxide")):
            reason = "No mineral UV filter"
        elif not r.get("inactive_ingredients"):
            reason = "Ingredient list unavailable — we can't verify this one"
        r["scope_exclusion_reason"] = reason

    mineral = [r for r in records if r.get("scope_exclusion_reason") is None]
    mineral_path = os.path.join(args.output_dir, "tinysafe_dailymed_v2_mineral_sun.json")
    json.dump({"metadata": {"count": len(mineral), "filter": "sunscreen + ZnO + no_chemical_filter"},
               "products": mineral}, open(mineral_path, "w"), ensure_ascii=False, indent=1)
    print(f"[F] mineral sunscreen → {mineral_path} ({len(mineral)})", flush=True)

    # quick health report
    empty = src_counts.get("empty", 0)
    ver = _count(records, "ingredients_verified")
    needs_pct = sum(1 for r in records for a in r.get("active_ingredients", [])
                    if a.get("percent_needs_review"))
    wr = _count(records, "water_resistance_minutes")
    print(f"\n--- INGREDIENT COMPLETENESS (the number Track A exists for) ---")
    print(f"ingredients_verified: {ver}")
    print(f"  spl_text_used = structured table was hiding ingredients")
    print(f"active strengths needing unit review: {needs_pct}")
    print(f"water_resistance_minutes: {wr}")
    print(f"scope_exclusion_reason: {_count(records, 'scope_exclusion_reason')}")
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
