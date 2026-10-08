#!/usr/bin/env python3
"""
scripts/baby_label_text.py — archive the full printed text of every baby/kids
label (data/views/baby_sunscreens.jsonl) so each published number can be
audited against the label itself, not only against the parsed fields.

Output: data/views/baby_label_text.jsonl, one line per label:
  {setid, spl_version, effective_date, title, text, sections: {title: text}}
`text` is every section title and body in document order, whitespace-collapsed.
Standard library only.
"""
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEW = os.path.join(ROOT, "data", "views", "baby_sunscreens.jsonl")
OUT = os.path.join(ROOT, "data", "views", "baby_label_text.jsonl")
BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
UA = {"User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"}
V3 = "{urn:hl7-org:v3}"


def fetch(setid):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{BASE}/spls/{setid}.xml", headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def flat(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def extract(setid):
    x = fetch(setid)
    if not x:
        return {"setid": setid, "error": "fetch failed"}
    root = ET.fromstring(x)
    parts, sections = [], {}
    for sec in root.iter(V3 + "section"):
        t = flat(sec.find(V3 + "title"))
        b = flat(sec.find(V3 + "text"))
        if t or b:
            parts.append((t + " " + b).strip())
            if b:
                sections.setdefault(t or "(untitled)", b)
    ver = root.find(V3 + "versionNumber")
    eff = root.find(V3 + "effectiveTime")
    return {"setid": setid, "spl_version": ver.get("value") if ver is not None else None,
            "effective_date": eff.get("value") if eff is not None else None,
            "title": flat(root.find(V3 + "title")), "text": " | ".join(parts), "sections": sections}


def main():
    ids = [json.loads(l)["setid"] for l in open(VIEW, encoding="utf-8") if l.strip()]
    ids += [a for a in sys.argv[1:]]
    ids = sorted(set(ids))
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(extract, ids))
    bad = [r["setid"] for r in rows if r.get("error")]
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[label_text] {len(rows) - len(bad)}/{len(rows)} labels archived; failed: {bad[:10]}")
    if len(bad) > 0.01 * len(rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
