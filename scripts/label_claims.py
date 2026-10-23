#!/usr/bin/env python3
"""Read the full text of every in-scope label once and record its sun-protection
claims (runs on GitHub Actions; the dev container cannot reach DailyMed).

  broad_spectrum : the label claims Broad Spectrum. The Drug Facts boilerplate
                   "use a sunscreen with a Broad Spectrum SPF value of 15 or higher"
                   does not count.
  aging_alert    : the label carries the FDA "Skin Cancer/Skin Aging Alert", which a
                   sunscreen must print when it is NOT broad spectrum or is SPF 2-14
                   (21 CFR 201.327). Definitive.
Output: label_claims/claims.jsonl, label_claims/failed.json
"""
import concurrent.futures as cf
import html
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dailymed_scraper as D  # noqa: E402

BOILER = re.compile(r"broad[\s-]*spectrum\s+SPF\s+(?:value\s+)?(?:of\s+)?15\s+(?:or\s+)?(?:higher|more|greater)", re.I)
BS = re.compile(r"broad[\s-]*spectrum", re.I)
ALERT = re.compile(r"skin\s+cancer\s*/\s*skin\s+aging\s+alert", re.I)
# "SPF 30", "30 SPF", "50+SPF"; never "SPF 100% mineral" (a percentage) or "SPF 15 mg"
SPF = re.compile(r"\bSPF\s*-?\s*(\d{1,3})(?!\s*%|\d|\s*(?:mg|ml|g)\b)|\b(\d{1,3})\s*\+?\s*SPF\b(?!\s*-?\s*\d{1,3}\b(?!\s*%))", re.I)
SPRAY = re.compile(r"\b(?:spray(?:ing)?\s+(?:liberally|evenly|generously|on|into|directly|until)|hold\s+(?:the\s+)?(?:can|container|bottle)\s+\d|do\s+not\s+spray|aerosol|continuous\s+spray|lotion\s+spray|sunscreen\s+spray|non[\s-]*aerosol|mist\s+spray|spray\s+mist|pump\s+spray|spray\s+bottle|contents\s+under\s+pressure)", re.I)
POWDER = re.compile(r"\b(?:loose\s+powder|mineral\s+powder|powder\s+sunscreen|brush\s+(?:on|onto|over)|tap\s+(?:the\s+)?brush|swirl\s+(?:the\s+)?brush)", re.I)
FREE = re.compile(r"\b(?:fragrance[\s-]*free|free\s+of\s+(?:added\s+)?fragrances?|no\s+(?:added\s+)?fragrances?|unscented|without\s+fragrance|0%\s+fragrance)\b", re.I)
FRAG_LISTED = re.compile(r"inactive\s+ingredients?\s*:?.{0,3000}?\b(?:fragrance|parfum|perfume|aroma)\b(?!\s*[-\s]*free)", re.I | re.S)
TEAR = re.compile(r"\btear[\s-]*free\b", re.I)
# the claim, or the Drug Facts direction every water-resistant label must print
WR = re.compile(r"water\s+resistant\s*\(?\s*(40|80)\s+minutes|after\s+(40|80)\s+minutes\s+of\s+swimming", re.I)


def text_of(xml):
    t = re.sub(r"<[^>]+>", " ", xml or "")
    return re.sub(r"\s+", " ", html.unescape(t))


# "Allergens: soybeans (glycerin)" -- a label's own allergen statement
ALLERGENS = re.compile(r"\ballergens?\s*:\s*([^.;|]{3,120})", re.I)
# a scent named on the label ("Fun Melon Fragrance", "Coconut Vanilla scent"), not "fragrance free"
SCENT = re.compile(r"\b((?:[A-Z][a-z]+\s){1,3})(?:[Ff]ragrance|FRAGRANCE|[Ss]cent(?:ed)?|SCENT(?:ED)?)\b(?![\s-]*(?i:free))")
ACT = re.compile(r"active\s+ingredients?\b(.{0,600}?)(?=\bpurposes?\b|\buses?\b|\bwarnings?\b|$)", re.I | re.S)
# the Drug Facts "Purpose" and "Uses" sections (is this product a sunscreen at all?)
PURPOSE = re.compile(r"\bpurposes?\b\s*:?(.{0,200}?)(?=\buses?\b|\bwarnings?\b|\bdirections\b|$)", re.I | re.S)
USES = re.compile(r"\buses?\b\s*:?(.{0,400}?)(?=\bwarnings?\b|\bdirections\b|\bdo not use\b|$)", re.I | re.S)


def actives_text(t):
    """Each printed Active ingredient(s) section (up to 3), joined by ' || '."""
    return " || ".join(m.group(1).strip()[:600] for m in list(ACT.finditer(t))[:3]) or None


MKT = re.compile(r"<marketingAct>(.*?)</marketingAct>", re.S)


def marketing(xml):
    """Each product's marketing status in the SPL: [status, start, end] (end set once
    the brand has told the FDA it stopped marketing the product)."""
    out = []
    for m in MKT.finditer(xml or ""):
        b = m.group(1)
        st = re.search(r'statusCode\s+code="(\w+)"', b)
        lo = re.search(r'<low\s+value="(\d+)"', b)
        hi = re.search(r'<high\s+value="(\d+)"', b)
        out.append([st.group(1) if st else None, lo.group(1) if lo else None, hi.group(1) if hi else None])
    return out[:20]


def claims(sid):
    for i in range(3):
        try:
            xml = D.http_xml(f"{D.BASE}/spls/{sid}.xml")
            if xml:
                t = text_of(xml)
                rest = BOILER.sub(" ", t)
                # SPF: the label's own number, not the boilerplate "SPF value of 15 or higher"
                spfs = [int(m.group(1) or m.group(2)) for m in SPF.finditer(BOILER.sub(" ", t)) if 2 <= int(m.group(1) or m.group(2)) <= 100]
                wr = [int(m.group(1) or m.group(2)) for m in WR.finditer(t)]
                return {"setid": sid, "broad_spectrum": bool(BS.search(rest)), "aging_alert": bool(ALERT.search(t)),
                        "spf": max(spfs) if spfs else None, "spray": bool(SPRAY.search(t)), "powder": bool(POWDER.search(t)),
                        "water_resistant_minutes": max(wr) if wr else None,
                        "fragrance_free_claim": bool(FREE.search(t)), "fragrance_in_list": bool(FRAG_LISTED.search(t)),
                        "tear_free_claim": bool(TEAR.search(t)), "chars": len(t),
                        # every SPF the label prints (more than one: one filing, several products)
                        "spfs": sorted(set(spfs)),
                        # the printed Active ingredient(s) section, for the printed strengths
                        "actives_text": actives_text(t),
                        "purpose": " || ".join(m.group(1).strip()[:200] for m in list(PURPOSE.finditer(t))[:3]) or None,
                        "uses": " || ".join(m.group(1).strip()[:400] for m in list(USES.finditer(t))[:2]) or None,
                        "marketing": marketing(xml),
                        "_text": t[:40000],
                        "allergen_statement": "; ".join(m.group(1).strip() for m in ALLERGENS.finditer(t))[:300] or None,
                        "scent_claims": sorted({m.group(1).strip() for m in SCENT.finditer(t)
                                                if not re.search(r"(?i)\b(no|free|without|added|natural|unscented)\b",
                                                                 m.group(1))})[:5] or None}
        except Exception as e:  # noqa: BLE001
            print("retry", sid, e, flush=True)
        time.sleep(5 * (i + 1))
    return None


def incremental():
    """Weekly, inside the scrape: read only labels that are new or have a new version
    (data/canonical is this week's register), and keep the rest."""
    path = os.path.join(ROOT, "data/views/label_claims.jsonl")
    have = {json.loads(x)["setid"]: json.loads(x) for x in open(path)} if os.path.exists(path) else {}
    cur = {}
    for line in open(os.path.join(ROOT, "data/canonical/us_sunscreens.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        cur[r["setid"]] = r.get("spl_version")
    todo = [s for s, v in cur.items() if s not in have or str(have[s].get("spl_version")) != str(v)]
    print(f"label claims: {len(todo)} new or changed labels to read", flush=True)
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for sid, r in zip(todo, ex.map(claims, todo)):
            if r:
                r.pop("_text", None)
                r["spl_version"] = cur[sid]
                have[sid] = r
    with open(path, "w") as f:
        for sid in sorted(have):
            if sid in cur:
                f.write(json.dumps(have[sid]) + "\n")


VER = {}


def main():
    if "--incremental" in sys.argv:
        return incremental()
    want = []
    for line in open(os.path.join(ROOT, "data/master/us_master.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("in_scope") and r.get("status") == "active":
            want.append(r["setid"])
            VER[r["setid"]] = r.get("spl_version")
    os.makedirs("label_claims", exist_ok=True)
    out, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for n, (sid, r) in enumerate(zip(want, ex.map(claims, want)), 1):
            (out.append(r) if r else failed.append(sid))
            if n % 500 == 0:
                print(n, "done", len(failed), "failed", flush=True)
    import gzip
    with open("label_claims/claims.jsonl", "w") as f, gzip.open("label_claims/text.jsonl.gz", "wt", encoding="utf-8") as g:
        for r in out:
            t = r.pop("_text", "")
            r["spl_version"] = VER.get(r["setid"])
            f.write(json.dumps(r) + "\n")
            g.write(json.dumps({"setid": r["setid"], "spl_version": r["spl_version"], "text": t}) + "\n")
    json.dump(failed, open("label_claims/failed.json", "w"))
    print(f"read {len(out)} of {len(want)}")


if __name__ == "__main__":
    main()
