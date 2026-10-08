#!/usr/bin/env python3
"""
scripts/spl_parse.py — read EVERYTHING we need from one FDA SPL XML file, and
check the manufacturer's structured tables against the label text printed in
the same file.

parse_spl(xml) -> {
  spl_version, effective_date, labeler, document_type,
  products: [ {index, name, ndc_product, dosage_form, monograph_id,
               marketing_category, actives[], inactives[], parts[]} ],
  printed:  { actives: [{name, percent}], inactives: [names in printed order],
              inactive_text, warnings, directions, other_info, sections{} },
  flags:    { under_6_months_ask_doctor, water_resistant_minutes,
              broad_spectrum_claim, spf_printed }
}
check_label(parsed) -> [issue, ...]   structured vs printed disagreements

Standard library only. Every function is tested on real files in
tests/fixtures/spl (tests/test_spl_parse.py).
"""
import re
import xml.etree.ElementTree as ET

NS = {"v3": "urn:hl7-org:v3"}
UNII_SYS = "2.16.840.1.113883.4.9"
ACTIVE_CLASSES = {"ACTIB", "ACTIM", "ACTIR"}
LOINC = {
    "55106-9": "active", "55105-1": "purpose", "34067-9": "uses", "34071-1": "warnings",
    "34068-7": "directions", "60561-8": "other_info", "51727-6": "inactive",
    "53413-1": "questions", "50570-1": "do_not_use", "50566-9": "stop_use",
    "50565-1": "keep_out_of_reach", "50567-7": "when_using", "51945-4": "principal_display_panel",
}


def _t(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _attr(el, path, attr):
    x = el.find(path, NS) if el is not None else None
    return x.get(attr) if x is not None else None


def _qty(ing):
    q = ing.find("v3:quantity", NS)
    if q is None:
        return None, None, None, None
    n, d = q.find("v3:numerator", NS), q.find("v3:denominator", NS)
    return (n.get("value") if n is not None else None, n.get("unit") if n is not None else None,
            d.get("value") if d is not None else None, d.get("unit") if d is not None else None)


_UNIT = {"G": 1.0, "MG": 1e-3, "UG": 1e-6, "MCG": 1e-6, "KG": 1e3, "ML": 1.0, "L": 1e3}


def _pct(nv, nu, dv, du):
    try:
        nu, du = (nu or "").upper(), (du or "").upper()
        if nu in _UNIT and du in _UNIT and float(dv) > 0:
            return round(100 * float(nv) * _UNIT[nu] / (float(dv) * _UNIT[du]), 4)
    except (TypeError, ValueError):
        pass
    return None


def _ingredients(prod):
    acts, inacts = [], []
    for ing in prod.findall("v3:ingredient", NS):
        sub = ing.find("v3:ingredientSubstance", NS)
        if sub is None:
            continue
        code = sub.find("v3:code", NS)
        unii = code.get("code") if code is not None and code.get("codeSystem") == UNII_SYS else None
        row = {"name": _t(sub.find("v3:name", NS)).upper(), "unii": unii}
        if ing.get("classCode") in ACTIVE_CLASSES:
            nv, nu, dv, du = _qty(ing)
            row.update({"strength": nv, "strength_unit": nu, "denominator": dv, "denominator_unit": du,
                        "percent_structured": _pct(nv, nu, dv, du)})
            acts.append(row)
        elif ing.get("classCode") == "IACT":
            inacts.append(row)
    return acts, inacts


def _product(mp, index):
    inner = mp.find("v3:manufacturedProduct", NS)
    p = inner if inner is not None else mp
    acts, inacts = _ingredients(p)
    parts = []
    for part in p.findall("v3:part", NS):
        pp = part.find("v3:partProduct", NS)
        if pp is not None:
            a, i = _ingredients(pp)
            parts.append({"name": _t(pp.find("v3:name", NS)), "dosage_form": _attr(pp, "v3:formCode", "displayName"),
                          "actives": a, "inactives": i})
    appr = mp.find(".//v3:approval", NS)
    return {
        "index": index,
        "name": _t(p.find("v3:name", NS)),
        "ndc_product": _attr(p, "v3:code", "code"),
        "dosage_form": _attr(p, "v3:formCode", "displayName"),
        "monograph_id": _attr(appr, "v3:id", "extension") if appr is not None else None,
        "marketing_category": _attr(appr, "v3:code", "displayName") if appr is not None else None,
        "actives": acts, "inactives": inacts, "parts": parts,
    }


# ---- printed text ---------------------------------------------------------
_PCT = re.compile(r"([A-Za-z][A-Za-z0-9 ,'/\-]{2,60}?)\s*[\(\.\:\s]*\s*(\d+(?:\.\d+)?)\s*%")
# headings as printed, including misspellings and bilingual Canadian headings
_HEAD = re.compile(r"^\s*(?:(?:inactive|non[- ]medicinal|other)\s+)?ingr\w*?(?:ients?|edients?|dients?)?"
                   r"(?:\s*/\s*ingr[ée]dients\s+non\s+m[ée]dicinaux)?\s*[:\-]?\s*", re.I)
_TRAILER = re.compile(r"\b(?:made in|manufactured (?:by|for)|distributed by|dist\. by|questions\??|other information|"
                      r"keep out of reach|for external use)\b.*$", re.I | re.S)
_JUNK = re.compile(r"^(?:etc\.?|\d+(?:\.\d+)?|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})$", re.I)


def split_ingredient_list(text):
    """Split a printed list on commas/semicolons that are not inside brackets."""
    text = text or ""
    # a heading after a product name ("Brand X Baby Inactive ingredients ...")
    m = re.search(r"(?:inactive|non[- ]medicinal|other)(?:\s+or\s+non[- ]medicinal)?\s+ingr\w*\s*[:\-]?", text[:220], re.I)
    if m and "," not in text[:m.start()]:  # only a heading that follows a product name, not a list
        text = text[m.end():]
    text = _HEAD.sub("", text).strip()
    text = re.sub(r"^\s*/?\s*ingr[ée]dients\s+non\s+m\s?[ée]dicinaux\s*[:\-]?\s*", "", text, flags=re.I)  # bilingual heading
    # a second-language copy that follows in the same section
    text = re.split(r"\bingr[ée]dients\s+non\s+m\s?[ée]dicinaux\b|\bINGREDIENTES\b", text, flags=re.I)[0]
    text = _TRAILER.sub("", text).strip().rstrip(".")
    if re.match(r"^\s*see\s+(?:ingredients|label|carton|package)", text, re.I):
        return []
    text = re.sub(r",(?=\d)", "\u2063", text)  # 1,2-hexanediol stays one item
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        sep = ch in ";•●▪■·" or (ch == "," and not (cur and cur[-1].isdigit()))
        if sep and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    items = []
    for x in out:
        x = x.replace("\u2063", ",")
        x = re.sub(r"\s*\.?\s*\*+\s*(?:certified|organic|natural|derived|from)\b.*$", "", x, flags=re.I)  # footnotes
        x = re.sub(r"\s*\.?\s*(?:\(\d\)\s*)?certified\s+organic\w*\s+ingredients?\b.*$", "", x, flags=re.I)
        x = re.sub(r"^\W*=?\s*certified\s+organic\s*", "", x, flags=re.I)
        x = re.sub(r"\s+(?:inactive|other)\s+ingredients?\s*$", "", x, flags=re.I)
        x = re.sub(r"\s+", " ", x).strip(" .*•·■")
        x = re.sub(r"^and\s+", "", x, flags=re.I)
        x = _HEAD.sub("", x) if items == [] else x
        if x and len(x) <= 120 and not _JUNK.match(x):
            items.append(x)
    return items


# Active names a sunscreen label may print, with the canonical name we use.
ACTIVE_VOCAB = {
    "ZINC OXIDE": "ZINC OXIDE", "TITANIUM DIOXIDE": "TITANIUM DIOXIDE", "TITANIUM OXIDE": "TITANIUM DIOXIDE",
    "AVOBENZONE": "AVOBENZONE", "BUTYL METHOXYDIBENZOYLMETHANE": "AVOBENZONE",
    "OXYBENZONE": "OXYBENZONE", "BENZOPHENONE-3": "OXYBENZONE",
    "OCTINOXATE": "OCTINOXATE", "ETHYLHEXYL METHOXYCINNAMATE": "OCTINOXATE", "OCTYL METHOXYCINNAMATE": "OCTINOXATE",
    "HOMOSALATE": "HOMOSALATE", "OCTISALATE": "OCTISALATE", "ETHYLHEXYL SALICYLATE": "OCTISALATE", "OCTYL SALICYLATE": "OCTISALATE",
    "OCTOCRYLENE": "OCTOCRYLENE", "ENSULIZOLE": "ENSULIZOLE", "PHENYLBENZIMIDAZOLE SULFONIC ACID": "ENSULIZOLE",
    "MERADIMATE": "MERADIMATE", "MENTHYL ANTHRANILATE": "MERADIMATE", "DIOXYBENZONE": "DIOXYBENZONE",
    "SULISOBENZONE": "SULISOBENZONE", "CINOXATE": "CINOXATE", "PADIMATE O": "PADIMATE O",
    "AMINOBENZOIC ACID": "AMINOBENZOIC ACID", "TROLAMINE SALICYLATE": "TROLAMINE SALICYLATE",
    "BEMOTRIZINOL": "BEMOTRIZINOL", "BIS-ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE": "BEMOTRIZINOL",
    "ECAMSULE": "ECAMSULE", "TEREPHTHALYLIDENE DICAMPHOR SULFONIC ACID": "ECAMSULE", "MEXORYL SX": "ECAMSULE",
    "DROMETRIZOLE TRISILOXANE": "DROMETRIZOLE TRISILOXANE", "MEXORYL XL": "DROMETRIZOLE TRISILOXANE",
    "ETHYLHEXYL TRIAZONE": "ETHYLHEXYL TRIAZONE", "OCTYL TRIAZONE": "ETHYLHEXYL TRIAZONE",
    "BISOCTRIZOLE": "BISOCTRIZOLE", "METHYLENE BIS-BENZOTRIAZOLYL TETRAMETHYLBUTYLPHENOL": "BISOCTRIZOLE",
    "DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE": "DIETHYLAMINO HYDROXYBENZOYL HEXYL BENZOATE",
    "ENZACAMENE": "ENZACAMENE", "4-METHYLBENZYLIDENE CAMPHOR": "ENZACAMENE",
    "AMILOXATE": "AMILOXATE", "ISOAMYL P-METHOXYCINNAMATE": "AMILOXATE",
    "BENZOPHENONE": "BENZOPHENONE",
}


def canon_active(name):
    n = norm(name)
    return ACTIVE_VOCAB.get(n, SYN.get(n, n))


def printed_actives(text, extra_names=()):
    """Find each known active name in the printed Active ingredient text and the
    percentage printed right after it (None if the label prints no number)."""
    t = re.sub(r"\s+", " ", text or "")
    t = re.sub(r"(Sunscreen|SUNSCREEN|Purposes?|PURPOSES?)(?=[A-Z])", r"\1 ", t)  # 'SunscreenHomosalate'
    vocab = dict(ACTIVE_VOCAB)
    for n in extra_names:
        vocab.setdefault(norm(n), norm(n))
    found = {}
    for name in sorted(vocab, key=len, reverse=True):
        pat = re.escape(name).replace("\\ ", r"[\s\-]*").replace("\\-", r"[\s\-]*")
        for m in re.finditer(r"(?<![A-Za-z])" + pat + r"(?![A-Za-z])", t, re.I):
            if any(a <= m.start() < b for a, b, _ in found.values()):
                continue
            tail = t[m.end():m.end() + 30]
            pm = re.match(r"[^%A-Za-z]{0,12}?(\d+(?:\.\d+)?)\s*%", tail)
            canon = vocab[name]
            if canon not in found:
                found[canon] = (m.start(), m.end(), float(pm.group(1)) if pm else None)
            break
    return [{"name": k, "percent": v[2]} for k, v in sorted(found.items(), key=lambda kv: kv[1][0])]


def parse_spl(xml):
    root = ET.fromstring(xml)
    doc = {
        "spl_version": _attr(root, "v3:versionNumber", "value"),
        "effective_date": _attr(root, "v3:effectiveTime", "value"),
        "document_type": _attr(root, "v3:code", "displayName"),
        "labeler": _t(root.find("v3:author/v3:assignedEntity/v3:representedOrganization/v3:name", NS)),
    }
    products = []
    for sec in root.iter("{urn:hl7-org:v3}section"):
        if _attr(sec, "v3:code", "code") == "48780-1":
            for subj in sec.findall("v3:subject", NS):
                mp = subj.find("v3:manufacturedProduct", NS)
                if mp is not None:
                    products.append(_product(mp, len(products)))
    sections = {}
    for sec in root.iter("{urn:hl7-org:v3}section"):
        title = _t(sec.find("v3:title", NS))
        txt = _t(sec.find("v3:text", NS))
        key = LOINC.get(_attr(sec, "v3:code", "code"))
        lead = (title + " " + txt).strip().lower()
        if key is None:  # unclassified sections that carry Drug Facts headings
            if re.match(r"active ingredients?\b", lead):
                key = "active"
            elif re.match(r"inactive ingredients?\b|ingredients?\s*:", lead):
                key = "inactive"
        if not key:
            continue
        if not txt:  # content sometimes sits in nested sub-sections
            txt = _t(sec)
            txt = txt[len(title):].strip() if title and txt.startswith(title) else txt
        body = txt if (not title or txt.lower().startswith(title.lower())) else (title + " " + txt).strip()
        if body and body not in sections.get(key, []):
            sections.setdefault(key, []).append(body)
    # one printed list per label; a second-language copy (e.g. Spanish) is not a second list
    inactive_texts = [t for t in sections.get("inactive", []) if not re.match(r"\s*ingredientes\b", t, re.I)]
    inactive_texts = [t for t in inactive_texts if split_ingredient_list(t)]
    printed_inactives = split_ingredient_list(inactive_texts[0]) if len(inactive_texts) == 1 else None
    # flags read the whole label: Directions often sit in unclassified sections
    all_text = re.sub(r"\s+", " ", " ".join(_t(sec.find("v3:text", NS)) for sec in root.iter("{urn:hl7-org:v3}section")))
    front = " ".join(sections.get("principal_display_panel", [])) + " " + " ".join(p["name"] for p in products)
    wr = re.search(r"water\s+resistant\s*\(\s*(40|80)\s*minutes", all_text, re.I)
    spf = None
    spf = re.search(r"\b(?:SPF|FPS)\s*(\d{1,3})\b", front, re.I)
    doc["products"] = products
    doc["printed"] = {
        "actives": printed_actives(" ".join(sections.get("active", [])),
                                   [a["name"] for p in products for a in p["actives"]]),
        "actives_complete": None,
        "active_text": sections.get("active", []),
        "inactives": printed_inactives,
        "inactive_text": inactive_texts,
        "warnings": " ".join(sections.get("warnings", [])),
        "directions": " ".join(sections.get("directions", [])),
        "other_info": " ".join(sections.get("other_info", [])),
    }
    act_text = " ".join(sections.get("active", []))
    n_pct = len(re.findall(r"\d+(?:\.\d+)?\s*%", act_text))
    # any amount printed without a % sign ("Ethyl Methoxycinnamate - 7.5") means
    # a line we may not have tied to an active: treat the list as not fully read
    bare = re.sub(r"\d+(?:\.\d+)?\s*%|\bSPF\s*\d+|\(in each[^)]*\)|\d+\s*(?:minutes|hours|months|years|ml|g|oz|fl)\b", " ", act_text, flags=re.I)
    n_bare = len(re.findall(r"(?<![A-Za-z\-/])\d+(?:\.\d+)?(?![A-Za-z\-/])", bare))
    got = sum(1 for a in doc["printed"]["actives"] if a["percent"] is not None)
    doc["printed"]["actives_complete"] = bool(act_text) and n_pct > 0 and got == n_pct and n_bare == 0
    doc["flags"] = {
        "under_6_months_ask_doctor": bool(re.search(r"(children|infants?)\s+under\s+6\s+months[^.]{0,40}?(ask|consult)\s+a\s+(doctor|physician)", all_text, re.I)),
        "water_resistant_minutes": int(wr.group(1)) if wr else None,
        # the claim, not the FDA boilerplate "use a sunscreen with a Broad Spectrum SPF value of 15"
        "broad_spectrum_claim": bool(re.search(r"\bbroad\s+spectrum\b", front, re.I)),
        "spf_printed": int(spf.group(1)) if spf else None,
    }
    return doc


# ---- structured vs printed ------------------------------------------------
SYN = {
    "AQUA": "WATER", "EAU": "WATER", "PURIFIED WATER": "WATER", "DEIONIZED WATER": "WATER",
    "PARFUM": "FRAGRANCE", "PERFUME": "FRAGRANCE", "AROMA": "FLAVOR",
    "ETHYLHEXYL SALICYLATE": "OCTISALATE", "OCTYL SALICYLATE": "OCTISALATE",
    "ETHYLHEXYL METHOXYCINNAMATE": "OCTINOXATE", "OCTYL METHOXYCINNAMATE": "OCTINOXATE",
    "BUTYL METHOXYDIBENZOYLMETHANE": "AVOBENZONE", "BENZOPHENONE-3": "OXYBENZONE", "BENZOPHENONE 3": "OXYBENZONE",
    "PHENYLBENZIMIDAZOLE SULFONIC ACID": "ENSULIZOLE", "TITANIUM OXIDE": "TITANIUM DIOXIDE",
    "ZINC DIOXIDE": "ZINC OXIDE", "ZINC OXIDE NANO": "ZINC OXIDE",
    "C12-15 ALKYL BENZOATE": "ALKYL (C12-15) BENZOATE", "CAPRYLIC/CAPRIC TRIGLYCERIDE": "MEDIUM-CHAIN TRIGLYCERIDES",
    "TOCOPHEROL": "TOCOPHEROL", "VITAMIN E": "TOCOPHEROL",
}
FRAGRANCE_WORDS = re.compile(r"\b(FRAGRANCE|PARFUM|PERFUME|FLAVOU?R|AROMA)\b", re.I)


def norm(name):
    s = (name or "").upper()
    s = re.sub(r"\.(ALPHA|BETA|GAMMA|DELTA|D|L|DL)\.\-?", "", s)
    s = re.sub(r"\b(USP|NF|EP|ANHYDROUS|CI \d+)\b", " ", s)
    s = re.sub(r"[^A-Z0-9/()\- ]", " ", s)
    s = re.sub(r"\s*([/\-])\s*", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return SYN.get(s, s)


INACTIVE_SYN = {
    "CYCLOPENTASILOXANE": "CYCLOMETHICONE 5", "CYCLOHEXASILOXANE": "CYCLOMETHICONE 6",
    "TRIETHANOLAMINE": "TROLAMINE", "DISODIUM EDTA": "EDETATE DISODIUM", "TETRASODIUM EDTA": "EDETATE SODIUM",
    "GLYCERYL STEARATE": "GLYCERYL MONOSTEARATE", "CETEARYL ALCOHOL": "CETOSTEARYL ALCOHOL",
    "SILICA": "SILICON DIOXIDE", "CAPRYLIC/CAPRIC TRIGLYCERIDES": "MEDIUM-CHAIN TRIGLYCERIDES",
    "CAPRYLIC/CAPRIC TRIGLYCERIDE": "MEDIUM-CHAIN TRIGLYCERIDES", "BEESWAX": "YELLOW WAX", "CERA ALBA": "WHITE WAX",
    "SD ALCOHOL 40-B": "ALCOHOL", "ALCOHOL DENAT": "ALCOHOL", "ALCOHOL DENAT.": "ALCOHOL",
    "BHT": "BUTYLATED HYDROXYTOLUENE", "BHA": "BUTYLATED HYDROXYANISOLE", "ALUMINA": "ALUMINUM OXIDE",
    "VP/HEXADECENE COPOLYMER": "VINYLPYRROLIDONE/HEXADECENE COPOLYMER", "PVP/HEXADECENE COPOLYMER": "VINYLPYRROLIDONE/HEXADECENE COPOLYMER",
    "VP/EICOSENE COPOLYMER": "VINYLPYRROLIDONE/EICOSENE COPOLYMER", "SODIUM HYALURONATE": "HYALURONATE SODIUM",
    "TOCOPHERYL ACETATE": "ALPHA-TOCOPHEROL ACETATE", "VITAMIN E": "TOCOPHEROL", "SHEA BUTTER": "SHEA BUTTER",
    "BUTYROSPERMUM PARKII BUTTER": "SHEA BUTTER", "ALOE BARBADENSIS LEAF JUICE": "ALOE VERA LEAF",
    "C12-15 ALKYL BENZOATE": "ALKYL (C12-15) BENZOATE", "C12 15 ALKYL BENZOATE": "ALKYL (C12-15) BENZOATE",
    "ISOHEXADECANE": "ISOHEXADECANE", "XANTHAN GUM": "XANTHAN GUM", "PROPANEDIOL": "PROPANEDIOL",
}


def _key(name):
    """Loose key: drop bracket text, map known INCI/USAN synonyms, sort tokens."""
    n = norm(name)
    n = INACTIVE_SYN.get(re.sub(r"\s*\([^)]*\)", "", n).strip(), n)
    s = re.sub(r"\([^)]*\)", " ", n)
    s = re.sub(r"\b(TOCOPHEROL)\b.*", r"\1", s) if "TOCOPHEROL" in s and "ACETATE" not in s else s
    return " ".join(sorted(re.sub(r"[^A-Z0-9 ]", " ", s).split()))


def match_inactives(printed, structured):
    """One-to-one match of printed names to structured names: exact key, then
    spaceless key, then token subset. Returns (matched pairs, unmatched printed,
    unmatched structured)."""
    left = list(range(len(structured)))
    sk = [_key(x) for x in structured]
    pairs, un_p = [], []
    for p in printed:
        k = _key(p)
        hit = next((i for i in left if sk[i] == k), None)
        if hit is None:
            hit = next((i for i in left if sk[i].replace(" ", "") == k.replace(" ", "")), None)
        if hit is None:
            kt = set(k.split())
            hit = next((i for i in left if kt and (kt <= set(sk[i].split()) or set(sk[i].split()) <= kt)), None)
        if hit is None:
            un_p.append(p)
        else:
            left.remove(hit); pairs.append((p, structured[hit]))
    return pairs, un_p, [structured[i] for i in left]


def check_label(doc, us_max=None):
    """Return issues where the structured tables and the printed label disagree.
    Only single-product labels are compared item by item; multi-product
    listings are flagged instead (their printed text mixes products)."""
    issues = []
    prods = [p for p in doc["products"]]
    if len(prods) != 1:
        issues.append({"type": "multi_product", "detail": f"{len(prods)} products in one listing"})
        return issues
    p = prods[0]
    complete = doc["printed"].get("actives_complete")
    pa = {canon_active(a["name"]): a["percent"] for a in doc["printed"]["actives"]}
    sa = {canon_active(a["name"]): a for a in p["actives"]}
    if not complete:
        issues.append({"type": "printed_actives_not_fully_read",
                       "detail": "not every printed % could be tied to a known active; active checks skipped"})
        pa = {}
    for n, pct in pa.items():
        if n not in sa:
            where = "inactive table" if any(norm(i["name"]) == n for i in p["inactives"]) else "nowhere"
            issues.append({"type": "printed_active_missing_from_structured", "name": n, "percent": pct, "structured_location": where})
        else:
            sp = sa[n].get("percent_structured")
            # only mass/mass fractions are comparable (mg/mL depends on density);
            # grams-per-pack filings round; a real error is large (24.08 vs 3, 10x)
            mass = {"G", "MG", "UG", "MCG", "KG"}
            ww = (sa[n].get("strength_unit") or "").upper() in mass and (sa[n].get("denominator_unit") or "").upper() in mass
            if ww and pct is not None and sp is not None and abs(sp - pct) > max(0.2, 0.1 * pct):
                issues.append({"type": "percent_mismatch", "name": n, "printed": pct, "structured": sp})
    for n, a in sa.items():
        if complete and pa and n not in pa:
            issues.append({"type": "structured_active_not_printed", "name": n, "structured": a.get("percent_structured")})
        if us_max and n in us_max:
            v = pa.get(n, a.get("percent_structured"))
            if v is not None and v > us_max[n] + 0.01:
                issues.append({"type": "above_us_max", "name": n, "percent": v, "us_max": us_max[n]})
    pi = doc["printed"]["inactives"]
    if pi is not None:
        names = [i["name"] for i in p["inactives"]] + [a["name"] for a in p["actives"]]
        _, unmatched, _ = match_inactives(pi, names)
        frag_printed = [x for x in pi if FRAGRANCE_WORDS.search(x)]
        frag_struct = [i for i in p["inactives"] if FRAGRANCE_WORDS.search(i["name"])]
        if frag_printed and not frag_struct:
            issues.append({"type": "fragrance_printed_not_structured", "printed": frag_printed})
        if unmatched:
            issues.append({"type": "printed_inactives_unmatched", "count": len(unmatched), "items": unmatched,
                           "printed_count": len(pi), "structured_count": len(p["inactives"])})
    return issues


if __name__ == "__main__":
    import json, sys
    d = parse_spl(open(sys.argv[1], encoding="utf-8").read())
    print(json.dumps({k: d[k] for k in ("spl_version", "effective_date", "labeler", "flags")}, indent=1))
    print(json.dumps([{k: p[k] for k in ("name", "dosage_form", "monograph_id", "ndc_product")} for p in d["products"]], indent=1))
    print("printed actives:", d["printed"]["actives"])
    print("printed inactives:", d["printed"]["inactives"])
    print("issues:", json.dumps(check_label(d), indent=1))


# ---- one record's worth of label fields -----------------------------------
# UNII per canonical active, taken from 13,326 DailyMed records (2026-10-08).
ACTIVE_UNII = {
    "AVOBENZONE": "G63QQF2NOX", "HOMOSALATE": "V06SV4M95S", "OCTISALATE": "4X49Y0596W",
    "TITANIUM DIOXIDE": "15FIX9V2JP", "OCTOCRYLENE": "5A68WGF6WM", "ZINC OXIDE": "SOI2LOH54Z",
    "OCTINOXATE": "4Y5P7MUD51", "OXYBENZONE": "95OOS7VE0Y", "ENSULIZOLE": "9YQ9DI1W42",
    "PADIMATE O": "Z11006CMUZ", "MERADIMATE": "J9QGD60OUZ", "AMINOBENZOIC ACID": "TL2TJE8QTX",
    "BEMOTRIZINOL": "PWZ1720CBH", "ECAMSULE": "M94R1PM439", "DROMETRIZOLE TRISILOXANE": "HC22845I1X",
    "SULISOBENZONE": "1W6L629B4K",
}
US_MAX = {"AVOBENZONE": 3, "OXYBENZONE": 6, "OCTINOXATE": 7.5, "HOMOSALATE": 15, "OCTISALATE": 5,
          "OCTOCRYLENE": 10, "ENSULIZOLE": 4, "ZINC OXIDE": 25, "TITANIUM DIOXIDE": 25, "MERADIMATE": 5,
          "DIOXYBENZONE": 3, "SULISOBENZONE": 10, "CINOXATE": 3, "PADIMATE O": 8, "BEMOTRIZINOL": 6}


def label_fields(xml):
    """Everything the canonical record should carry from one SPL, plus the
    printed-label correction of the actives when the label is unambiguous."""
    doc = parse_spl(xml)
    issues = check_label(doc, US_MAX)
    p0 = doc["products"][0] if doc["products"] else {}
    out = {
        "spl_version": doc["spl_version"], "effective_date": doc["effective_date"],
        "labeler": doc["labeler"] or None, "product_count": len(doc["products"]),
        "dosage_form": p0.get("dosage_form"), "ndc_product": p0.get("ndc_product"),
        "monograph_id": p0.get("monograph_id"), "marketing_category": p0.get("marketing_category"),
        "printed_actives": doc["printed"]["actives"],
        "printed_inactives": doc["printed"]["inactives"],          # the full ingredient list, label order
        "label_flags": doc["flags"], "label_checks": issues,
    }
    if len(doc["products"]) > 1:
        out["products"] = [{k: p[k] for k in ("name", "dosage_form", "ndc_product", "monograph_id")}
                           | {"actives": [a["name"] for a in p["actives"]], "inactive_count": len(p["inactives"])}
                           for p in doc["products"]]
    # Correct the actives from the printed label only when it is unambiguous:
    # one product, every printed active has a percentage and a known UNII, and
    # the structured table disagrees on which actives or by a large margin.
    pa = doc["printed"]["actives"]
    disagree = any(i["type"] in ("printed_active_missing_from_structured", "structured_active_not_printed",
                                 "percent_mismatch") for i in issues)
    if (len(doc["products"]) == 1 and pa and disagree and doc["printed"].get("actives_complete")
            and all(a["percent"] is not None and a["name"] in ACTIVE_UNII for a in pa)):
        # NOT applied automatically (2026-10-08 smoke run: real labels spell
        # actives too many ways). Confirmed proposals go to data/corrections/.
        out["label_actives_proposal"] = [
            {"name": a["name"], "unii": ACTIVE_UNII[a["name"]], "percent_ww": a["percent"],
             "percent_basis": "drug_facts_panel", "percent_source": "printed_label_correction"} for a in pa]
    return out
