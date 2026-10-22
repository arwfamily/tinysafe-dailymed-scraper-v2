import json, sys, os
sys.path.insert(0, "scripts/cosing")
import fetch_cosing as F
out = {}
def t(q):
    F.QUERY = json.dumps({"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}, q]}})
    try: return F.page(1, 1)["totalResults"]
    except SystemExit as e: return str(e)
for lo, hi in [(0, 10000), (10000, 20000), (20000, 40000), (40000, 60000), (60000, 80000), (80000, 100000), (100000, 1000000), (1000000, 10**9)]:
    out[f"num {lo}-{hi}"] = t({"range": {"substanceId": {"gte": lo, "lt": hi}}})
for lo, hi in [("0", "1"), ("1", "2"), ("2", "3"), ("3", "4"), ("4", "5"), ("5", "6"), ("6", "7"), ("7", "8"), ("8", "9"), ("9", "A")]:
    out[f"str {lo}-{hi}"] = t({"range": {"substanceId": {"gte": lo, "lt": hi}}})
out["exists_sid"] = t({"exists": {"field": "substanceId"}})
for st in ["Active", "Deleted", "Replaced"]:
    out["status " + st] = t({"terms": {"status": [st]}})
# deep paging check
F.QUERY = json.dumps({"bool": {"must": [{"terms": {"itemType": ["ingredient"]}}]}})
out["p49_len"] = len(F.page(49)["results"]); out["p50_len"] = len(F.page(50)["results"])
d = F.page(3); out["sample_sids"] = [r["metadata"].get("substanceId") for r in d["results"][:10]]
os.makedirs("cosing", exist_ok=True); json.dump(out, open("cosing/probe.json", "w"), indent=1)
