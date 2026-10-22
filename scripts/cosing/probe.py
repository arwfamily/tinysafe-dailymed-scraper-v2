import json, sys
sys.path.insert(0, "scripts/cosing")
import fetch_cosing as F
out = {}
variants = {
  "base": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}]}},
  "status_active": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, {"terms": {"status": ["Active"]}}]}},
  "prefix_A": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, {"prefix": {"inciName": "A"}}]}},
  "wild_A": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, {"wildcard": {"inciName": "A*"}}]}},
  "range_sid": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, {"range": {"substanceId": {"gte": 0, "lt": 50000}}}]}},
  "fn_emollient": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, {"terms": {"functionName": ["EMOLLIENT"]}}]}},
  "perf_Y": {"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, {"terms": {"perfuming": ["Y"]}}]}},
}
for k, q in variants.items():
    F.QUERY = json.dumps(q)
    try:
        d = F.page(1, 1)
        out[k] = d.get("totalResults")
    except SystemExit as e:
        out[k] = str(e)
for t in ["A*", "a", "ZINC"]:
    F.QUERY = json.dumps(variants["base"])
    F.URL = F.URL.replace("text=*", "text=" + t) if "text=*" in F.URL else F.URL
    out["text_" + t] = F.page(1, 1).get("totalResults")
    F.URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey={k}&text=*&pageSize={n}&pageNumber={p}"
import os; os.makedirs("cosing", exist_ok=True)
json.dump(out, open("cosing/probe.json", "w"), indent=1); print(out)
