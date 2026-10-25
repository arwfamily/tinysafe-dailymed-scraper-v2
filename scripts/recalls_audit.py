#!/usr/bin/env python3
"""Check that data/recalls/us_drug_recalls.jsonl holds every openFDA drug recall that concerns a
sunscreen: for each search term, openFDA's own total vs what the file holds, and every recall
whose description says sunscreen/SPF/sunblock that the file lacks. Writes
data/reports/recalls_audit.json. Needs network (GitHub Actions)."""
import json, os, re, time, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.fda.gov/drug/enforcement.json"
TERMS = ["sunscreen", "sun screen", "sunblock", "sun block", "spf", "broad spectrum", "avobenzone", "oxybenzone",
         "octinoxate", "homosalate", "octocrylene", "octisalate", "zinc oxide", "titanium dioxide", "uva", "tanning"]


def get(q, skip=0):
    url = API + "?" + urllib.parse.urlencode({"search": q, "limit": 1000, "skip": skip})
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "TinySafe-audit/1.0"}), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"results": [], "meta": {"results": {"total": 0}}}
            time.sleep(3 * (i + 1))
        except Exception:
            time.sleep(3 * (i + 1))
    raise RuntimeError(url)


def main():
    have = {json.loads(l)["recall_number"] for l in open(os.path.join(ROOT, "data/recalls/us_drug_recalls.jsonl"))}
    SUN = re.compile(r"sunscreen|sun screen|sunblock|sun block|\bspf\b|broad spectrum", re.I)
    out = {"terms": {}, "missing": []}
    seen = set()
    for t in TERMS:
        q = f'product_description:"{t}"'
        first = get(q)
        total = (first.get("meta") or {}).get("results", {}).get("total", 0)
        got, res, skip = 0, first.get("results") or [], 0
        while True:
            for r in res:
                got += 1
                rn = r["recall_number"]
                if rn in seen:
                    continue
                seen.add(rn)
                if SUN.search(r.get("product_description") or "") and rn not in have:
                    out["missing"].append({k: r.get(k) for k in ("recall_number", "recall_initiation_date", "recalling_firm",
                                                                  "product_description", "reason_for_recall", "classification", "status")})
            if len(res) < 1000 or skip + 1000 >= 26000:
                break
            skip += 1000
            res = get(q, skip).get("results") or []
            time.sleep(0.3)
        out["terms"][t] = {"openfda_total": total, "fetched": got}
        print(t, total, got, flush=True)
    out["file_count"] = len(have)
    out["missing_count"] = len(out["missing"])
    os.makedirs(os.path.join(ROOT, "data/reports"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "data/reports/recalls_audit.json"), "w"), indent=1, ensure_ascii=False)
    print("missing", len(out["missing"]))


if __name__ == "__main__":
    main()
