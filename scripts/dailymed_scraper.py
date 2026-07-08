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
NDC_CODESYSTEM = "2.16.840.1.113883.6.69"   # SPL에서 NDC를 나타내는 OID

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


# ---------- NDC 추출 (SPL XML) ----------
def parse_ndc_xml(xml):
    """SPL XML의 <code codeSystem=NDC> 요소에서 제품 NDC 추출.
    manufacturedProduct 는 2-segment (labeler-product, 예: 83252-126),
    containerPackagedProduct 는 3-segment 패키지 NDC (예: 83252-126-25).
    반환 (ndc, ndc9): ndc = full 3-segment 우선(없으면 2-segment), ndc9 = 앞 두 segment."""
    if not xml:
        return None, None
    codes = []
    for m in re.finditer(r"<code\b[^>]*>", xml, re.IGNORECASE):
        tag = m.group(0)
        if NDC_CODESYSTEM not in tag:
            continue
        cm = re.search(r'code="([^"]+)"', tag)
        if not cm:
            continue
        c = cm.group(1).strip()
        # NDC shape: labeler(4-5 digits)-product(3-4)-[package(1-2)]
        if re.fullmatch(r"\d{4,5}-\d{3,4}(-\d{1,2})?", c) and c not in codes:
            codes.append(c)
    if not codes:
        return None, None
    full = next((c for c in codes if c.count("-") == 2), None)
    ndc = full or codes[0]
    ndc9 = "-".join(ndc.split("-")[:2])
    return ndc, ndc9


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

RISK_TOKENS = {
    "fragrance": [r"\bFRAGRANCE\b", r"\bPARFUM\b"],
    "oat":       [r"\bAVENA\b", r"\bOAT\b", r"\bOATMEAL\b"],   # \bOAT\b, never bare OAT:
                                                                 # BENZOATE / NEOPENTANOATE / GOAT MILK
    "chemical_uv_filter": [r"\bAVOBENZONE\b", r"\bOXYBENZONE\b", r"\bOCTOCRYLENE\b",
                           r"\bHOMOSALATE\b", r"\bOCTINOXATE\b", r"\bOCTISALATE\b",
                           r"\bENSULIZOLE\b", r"\bPADIMATE O\b"],
    "paraben":   [r"PARABEN\b"],
    "formaldehyde_releaser": [r"\bDMDM HYDANTOIN\b", r"\bDIAZOLIDINYL UREA\b",
                              r"\bIMIDAZOLIDINYL UREA\b", r"\bQUATERNIUM-15\b"],
}


def _risk_hits(text):
    up = (text or "").upper()
    return sorted({k for k, pats in RISK_TOKENS.items()
                   if any(re.search(p, up) for p in pats)})


def audit_completeness(xml_names, text_items, text_blob):
    """
    Is the structured table complete?

    String-mass coverage was the wrong measure: the table uses UNII preferred names
    ("TRIGLYCERIDES, MEDIUM CHAIN") while the body text uses INCI ("caprylic/capric
    triglyceride"). Comparing characters flags naming conventions as missing ingredients.

    Count is naming-agnostic. And the question that actually matters is not "how many"
    but "does the text disclose a fragrance / an oat / a chemical filter that the table
    does not". That is precisely what these tables were found to be hiding.

    Returns (verdict, detail) with verdict in
      "table_complete" | "table_incomplete" | "no_text_section"
    """
    if not text_blob or not text_items:
        return "no_text_section", {"table_n": len(xml_names), "text_n": 0, "text_only_risk": []}

    table_risk = _risk_hits(" | ".join(xml_names))
    text_risk = _risk_hits(" | ".join(text_items))
    text_only_risk = [r for r in text_risk if r not in table_risk]

    detail = {"table_n": len(xml_names), "text_n": len(text_items),
              "text_only_risk": text_only_risk}

    if text_only_risk:
        return "table_incomplete", detail          # a hidden allergen or filter. Decisive.
    if len(text_items) > len(xml_names) + 1:
        return "table_incomplete", detail          # materially longer
    return "table_complete", detail


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
        if not p or len(p) <= 1:
            continue
        # A masked parenthetical can swallow a whole run of ingredients. If an item still
        # carries 2+ top-level commas, it is not one ingredient. Split it again.
        if p.count(",") >= 2 and p.count("(") == p.count(")"):
            depth, buf, pieces = 0, "", []
            for ch in p:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if ch == "," and depth == 0:
                    pieces.append(buf); buf = ""
                else:
                    buf += ch
            pieces.append(buf)
            pieces = [x.strip(" .") for x in pieces if len(x.strip(" .")) > 1]
            # only accept the re-split if it does not shatter a numeric name like 1,2-HEXANEDIOL
            if all(not re.fullmatch(r"\d+", x) for x in pieces) and len(pieces) >= 3:
                for x in pieces:
                    if x not in seen:
                        seen.add(x); out.append(x)
                continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ---------------------------------------------------------------- strength + units

def _attr(tag: str, name: str):
    m = re.search(name + r'\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
    return m.group(1) if m else None


def parse_strength(block: str):
    """
    Keep the unit and the denominator. `value` alone is meaningless:
    <numerator unit="mg" value="89.6"/><denominator unit="g" value="1"/>  is 8.96%, not 89.6%.
    Attribute order varies across SPLs, so pull each attribute independently.
    """
    nm = re.search(r"<numerator\b[^>]*>", block, re.IGNORECASE)
    if not nm:
        return None
    ntag = nm.group(0)
    try:
        v = float(_attr(ntag, "value"))
    except (TypeError, ValueError):
        return None
    rec = {"value": v, "unit": (_attr(ntag, "unit") or "").strip()}

    dm = re.search(r"<denominator\b[^>]*>", block, re.IGNORECASE)
    if dm:
        dtag = dm.group(0)
        try:
            rec["per_value"] = float(_attr(dtag, "value"))
        except (TypeError, ValueError):
            pass
        rec["per_unit"] = (_attr(dtag, "unit") or "").strip()
    return rec


def to_percent(strength):
    """
    Convert to percent when the units permit it. Returns (percent, basis) or (None, None).

    basis is "w/w" or "w/v" — never conflated. Values above the FDA cap are NOT dropped;
    they are returned and flagged, because dropping a number is a decision and this
    function does not get to make it. (Diaper creams legitimately run zinc oxide to 40%.)
    """
    if not strength:
        return None, None
    v, u = strength["value"], strength["unit"].lower()
    pv, pu = strength.get("per_value"), (strength.get("per_unit") or "").lower()

    if u in ("%", "pct"):
        return round(v, 3), "w/w"
    if not pv:
        return None, None

    scale = {"g": 1.0, "mg": 0.001, "kg": 1000.0}.get(u)
    if scale is None:
        return None, None
    grams = v * scale

    if pu in ("g", "kg"):
        per_g = pv * (1000.0 if pu == "kg" else 1.0)
        return round(grams / per_g * 100.0, 3), "w/w"
    if pu in ("ml", "l"):
        per_ml = pv * (1000.0 if pu == "l" else 1.0)
        return round(grams / per_ml * 100.0, 3), "w/v"
    if pu == "1" and pv == 1.0:
        return None, None
    return None, None


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
            pct, basis = to_percent(st)
            rec["percent"] = pct
            rec["percent_basis"] = basis              # "w/w" | "w/v" | None
            rec["percent_unresolved"] = (st is not None and pct is None)
            rec["percent_implausible"] = (pct is not None and pct > 25.0)
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
    table (carries UNII) and the body-text section (LOINC 51727-6). Manufacturers sometimes
    file an incomplete table.

    We keep BOTH. Choosing a winner and discarding the loser is how you lose the ability
    to check yourself later — the same mistake `promote_enforcement.py` refuses to make
    when it flags a fuzzy match `needs_review` instead of auto-merging.

    Returns (chosen_items, source, audit).
    """
    if not xml:
        items, src_ = fetch_inactive_openfda(setid)
        return items, (src_ or "empty"), {
            "ingredients_verified": "openfda_fallback",
            "inactive_from_table": [], "inactive_from_text": [],
            "inactive_text_raw": "", "table_vs_text": None}

    table = _parse_ingredients_xml(xml, want_active=False)
    table_names = [i["name"] for i in table]
    text_blob = extract_section_text(xml, LOINC_INACTIVE)
    text_items = smart_split(text_blob) if text_blob else []
    verdict, detail = audit_completeness(table_names, text_items, text_blob)

    audit = {"ingredients_verified": verdict,
             "inactive_from_table": table,
             "inactive_from_text": text_items,
             "inactive_text_raw": text_blob,
             "table_vs_text": detail}

    if verdict == "table_incomplete":
        by_norm = {normalize(n): i.get("unii") for n, i in zip(table_names, table)}
        chosen = [{"name": n, "unii": by_norm.get(normalize(n))} for n in text_items]
        audit["ingredients_verified"] = "spl_text_used"
        return chosen, "spl_text", audit

    if table:
        return table, "spl_xml", audit

    if text_items:
        audit["ingredients_verified"] = "spl_text_used"
        return [{"name": n, "unii": None} for n in text_items], "spl_text", audit

    items, src_ = fetch_inactive_openfda(setid)
    audit["ingredients_verified"] = "openfda_fallback"
    return items, (src_ or "empty"), audit


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
    xml = http_xml(f"{BASE}/spls/{setid}.xml")     # fetched ONCE, reused four times
    actives = fetch_active(setid, xml)
    inact, src, audit = fetch_inactive(setid, xml)
    ndc, ndc9 = parse_ndc_xml(xml)
    rec = {
        "setid": setid,
        "title": title,
        "product_name": re.sub(r"\s*\[.*?\]\s*$", "", title).strip(),
        "ndc": ndc,
        "ndc9": ndc9,
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
    # Nothing vanishes silently: every record carries a scope_exclusion_reason (or None).
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

    master_path = os.path.join(args.output_dir, "tinysafe_dailymed_v2_master.json")
    src_counts = {}
    for r in records:
        src_counts[r["inactive_source"]] = src_counts.get(r["inactive_source"], 0) + 1
    master = {
        "metadata": {
            "scraper_version": "2.2",
            "search_method": "ingredient_unii",
            "unii_searched": UNII,
            "total_products": len(records),
            "inactive_source_breakdown": src_counts,
            "mineral_type_breakdown": _count(records, "mineral_type"),
            "with_spf": sum(1 for r in records if r.get("spf")),
            "with_ndc": sum(1 for r in records if r.get("ndc")),
            "chemical_filter": sum(1 for r in records if r.get("contains_chemical_filter")),
            "baby_labeled": sum(1 for r in records if r.get("baby_labeled")),
            "ingredients_verified_breakdown": _count(records, "ingredients_verified"),
            "water_resistance_breakdown": _count(records, "water_resistance_minutes"),
            "active_strength_unresolved": sum(1 for r in records
                                              for a in r.get("active_ingredients", [])
                                              if a.get("percent_unresolved")),
            "table_hid_a_risk_ingredient": sum(1 for r in records
                                               if (r.get("table_vs_text") or {}).get("text_only_risk")),
        },
        "products": records,
    }
    json.dump(master, open(master_path, "w"), ensure_ascii=False, indent=1)
    print(f"[F] master → {master_path} ({len(records)})", flush=True)

    mineral = [r for r in records if r.get("scope_exclusion_reason") is None]
    mineral_path = os.path.join(args.output_dir, "tinysafe_dailymed_v2_mineral_sun.json")
    json.dump({"metadata": {"count": len(mineral),
                            "filter": "sunscreen + (ZnO or TiO2) + no chemical UV filter + ingredient list present",
                            "note": "scope_exclusion_reason on the master file explains every omission"},
               "products": mineral}, open(mineral_path, "w"), ensure_ascii=False, indent=1)
    print(f"[F] mineral sunscreen → {mineral_path} ({len(mineral)})", flush=True)

    # quick health report
    empty = src_counts.get("empty", 0)
    ver = _count(records, "ingredients_verified")
    needs_pct = sum(1 for r in records for a in r.get("active_ingredients", [])
                    if a.get("percent_unresolved"))
    implaus = sum(1 for r in records for a in r.get("active_ingredients", [])
                  if a.get("percent_implausible"))
    hidden = [r["product_name"][:44] for r in records
              if (r.get("table_vs_text") or {}).get("text_only_risk")]
    wr = _count(records, "water_resistance_minutes")
    print(f"\n--- INGREDIENT COMPLETENESS (the number Track A exists for) ---")
    print(f"ingredients_verified: {ver}")
    print(f"  spl_text_used = structured table was hiding ingredients")
    print(f"active strengths with unresolvable units: {needs_pct}")
    print(f"active percents above the 25% FDA cap (flagged, not dropped): {implaus}")
    print(f"products whose TEXT discloses a risk ingredient the TABLE omits: {len(hidden)}")
    for h in hidden[:20]:
        print(f"    {h}")
    print(f"water_resistance_minutes: {wr}")
    print(f"scope_exclusion_reason: {_count(records, 'scope_exclusion_reason')}")
    print(f"\n--- HEALTH ---")
    print(f"inactive source: {src_counts}")
    print(f"inactive MISSING (empty): {empty} ({round(100*empty/max(len(records),1))}%)")
    print(f"with SPF: {master['metadata']['with_spf']} | baby_labeled: {master['metadata']['baby_labeled']}")
    no_ndc = len(records) - master['metadata']['with_ndc']
    print(f"with NDC: {master['metadata']['with_ndc']} | NDC missing: {no_ndc} ({round(100*no_ndc/max(len(records),1))}%)")


def _count(records, field):
    out = {}
    for r in records:
        out[r.get(field)] = out.get(r.get(field), 0) + 1
    return out


if __name__ == "__main__":
    main()
