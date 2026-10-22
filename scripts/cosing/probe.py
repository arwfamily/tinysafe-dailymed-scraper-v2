import json, sys, os
sys.path.insert(0, "scripts/cosing")
import fetch_cosing as F
out = {}
def t(q):
    F.QUERY = json.dumps({"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, q]}})
    try: return F.page(1, 1)["totalResults"]
    except SystemExit as e: return str(e)
for lo, hi in [(0, 10**9), (80000, 90000), (90000, 100000), (99000, 100000), (70000, 80000)]:
    out[f"num {lo}-{hi}"] = t({"range": {"substanceId": {"gte": lo, "lt": hi}}})
for lo, hi in [("9", "9~"), ("9", "99999"), ("90000", "99999"), ("1", "9~"), ("0", "z")]:
    out[f"str {lo}-{hi}"] = t({"range": {"substanceId": {"gte": lo, "lte": hi}}})
for f in ["inciName", "casNo"]:
    out["exists " + f] = t({"exists": {"field": f}})
for fn in ["SKIN CONDITIONING", "EMOLLIENT", "Emollient", "emollient", "SKIN CONDITIONING - EMOLLIENT"]:
    out["fn " + fn] = t({"terms": {"functionName": [fn]}})
out["ref_range"] = t({"range": {"reference": {"gte": "0", "lt": "8"}}})
os.makedirs("cosing", exist_ok=True); json.dump(out, open("cosing/probe.json", "w"), indent=1)
