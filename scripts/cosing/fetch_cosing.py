#!/usr/bin/env python3
"""Download every CosIng ingredient record (EU Commission, DG GROW) through the
CosIng web site's public search API and keep the fields the site needs:
INCI name (EU and US), CAS/EC, functions, status, annex/restriction, perfuming flag.

Runs in GitHub Actions (the dev container cannot reach ec.europa.eu).
Output: cosing/cosing_ingredients.jsonl + cosing/manifest.json
"""
import json, os, sys, time, urllib.request, uuid, datetime

KEY = "285a77fd-1257-4271-8507-f0c6b2961203"   # public key embedded in the CosIng web page
URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey={k}&text=*&pageSize={n}&pageNumber={p}"
QUERY = json.dumps({"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}]}})
KEEP = ["inciName", "inciUsaName", "innName", "phEurName", "chemicalName", "chemicalDescription", "casNo", "ecNo",
        "functionName", "status", "annexNo", "refNo", "cosmeticRestriction", "maximumConcentration",
        "otherRestrictions", "wordingOfConditions", "perfuming", "substanceId", "nameOfCommonIngredientsGlossary"]


def page(p, n=200):
    b = "----" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"query\"\r\nContent-Type: application/json\r\n\r\n"
            f"{QUERY}\r\n--{b}--\r\n").encode()
    req = urllib.request.Request(URL.format(k=KEY, n=n, p=p), data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}",
                                          "User-Agent": "arwhouse.com sunscreen ingredient check (research)"})
    for i in range(5):
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:  # noqa: BLE001
            print("retry", p, e, file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise SystemExit(f"page {p} failed")


def main():
    os.makedirs("cosing", exist_ok=True)
    first = page(1)
    total = first["totalResults"]
    pages = -(-total // 200)
    seen, rows = set(), []
    for p in range(1, pages + 1):
        d = first if p == 1 else page(p)
        for r in d["results"]:
            m = r["metadata"]
            sid = (m.get("substanceId") or [None])[0] or r.get("reference")
            if sid in seen:
                continue
            seen.add(sid)
            rows.append({k: (m.get(k) or []) for k in KEEP})
        time.sleep(0.5)
    with open("cosing/cosing_ingredients.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump({"source": "European Commission CosIng (ec.europa.eu/growth/tools-databases/cosing)",
               "fetched": datetime.datetime.utcnow().isoformat() + "Z", "total_reported": total,
               "records": len(rows)}, open("cosing/manifest.json", "w"), indent=1)
    print(total, len(rows))


if __name__ == "__main__":
    main()
