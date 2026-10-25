#!/usr/bin/env python3
"""FDA drug recalls that concern sunscreens -> data/recalls/us_drug_recalls.jsonl

Source: openFDA drug enforcement reports (every FDA drug recall since 2004),
https://api.fda.gov/drug/enforcement.json. A record is kept when its product
description mentions a sunscreen (sunscreen, sun screen, sunblock, SPF, or a
UV-filter active). openFDA attaches the label's spl_set_id and product NDCs to
many records; those are what us_master.py matches on first.

One line per recall number: {recall_number, recall_initiation_date,
classification, status, recalling_firm, brand, product_description,
reason_for_recall, code_info, spl_set_id[], product_ndc[], url}

Needs network (GitHub Actions). Standard library only.
"""
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data/recalls/us_drug_recalls.jsonl")
API = "https://api.fda.gov/drug/enforcement.json"
TERMS = ['"sunscreen"', '"sun screen"', '"sunblock"', '"sun block"', '"spf"', '"broad spectrum"', '"uva"', '"tanning"', '"avobenzone"', '"oxybenzone"', '"octinoxate"',
         '"homosalate"', '"octocrylene"', '"octisalate"', '"zinc oxide"', '"titanium dioxide"']
UA = {"User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"}


def get(params):
    url = API + "?" + urllib.parse.urlencode(params, safe=':+"()')
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:                    # openFDA answers 404 for "no matches"
                return {"results": []}
            time.sleep(3 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(3 * (i + 1))
    raise RuntimeError("openFDA unreachable: " + url)


def main():
    key = os.environ.get("OPENFDA_API_KEY")
    rows = {}
    for t in TERMS:
        skip = 0
        while True:
            params = {"search": f"product_description:{t}", "limit": 1000, "skip": skip}
            if key:
                params["api_key"] = key
            res = get(params).get("results") or []
            for r in res:
                o = r.get("openfda") or {}
                rows[r["recall_number"]] = {
                    "recall_number": r["recall_number"], "recall_initiation_date": r.get("recall_initiation_date"),
                    "classification": r.get("classification"), "status": r.get("status"),
                    "recalling_firm": r.get("recalling_firm"), "brand": "; ".join(o.get("brand_name") or []),
                    "product_description": r.get("product_description"),
                    "reason_for_recall": r.get("reason_for_recall"), "code_info": r.get("code_info"),
                    "spl_set_id": o.get("spl_set_id") or [], "product_ndc": o.get("product_ndc") or [],
                    "url": "https://api.fda.gov/drug/enforcement.json?search=recall_number:%22"
                           + r["recall_number"] + "%22"}
            if len(res) < 1000 or skip >= 25000:
                break
            skip += 1000
            time.sleep(0.3)
        print(t, len(rows), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for rid in sorted(rows):
            f.write(json.dumps(rows[rid], ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} recalls -> {OUT}")


if __name__ == "__main__":
    main()
