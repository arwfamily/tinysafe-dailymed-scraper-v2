#!/usr/bin/env python3
"""The Sunscreen Check's ingredient dictionary: for each label name, which CosIng
ingredient it is, its main job in a sunscreen, and how we know.

Sources, in order (the first that applies wins):
  reviewed  the INCI is one of the most-used ingredients whose main job two
            independent reads agreed on (or the lead decided a disagreement):
            data/reference/cosing/jobs_reviewed.json
  cosing    the INCI's CosIng functions, by the fixed rule in roles.py
  plant     a plant material the label does not specify (e.g. "GUAVA"): two reads
            agreed on the plant, no single INCI applies -> skin conditioning
  read      no CosIng entry; two reads agreed on the job
  none      not matched: the site falls back to its name pattern, shown as unverified

The name -> INCI step: exact CosIng name (EU or US INCI) or a reading of it
(match.py), else two independent reads that agreed (name_reads_merged.json).
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import match as M  # noqa: E402
import roles as RO  # noqa: E402

REF = os.path.join(ROOT, "data/reference/cosing")
CAT = {"emollient": "emollient", "emulsifier": "emulsifier", "humectant": "humectant", "thickener": "thickener",
       "film former": "film_former", "preservative": "preservative", "antioxidant": "antioxidant",
       "chelating": "chelating", "pH adjuster": "ph", "colorant": "colorant", "fragrance": "fragrance",
       "solvent": "solvent", "skin conditioning": "skin_conditioning", "soothing": "skin_conditioning",
       "UV filter": "uv_filter", "silicone": "slip", "surfactant": "emulsifier", "plant-derived": "skin_conditioning",
       "other": "other"}


def load():
    jobs = json.load(open(os.path.join(REF, "jobs_reviewed.json")))
    reads = json.load(open(os.path.join(REF, "name_reads_merged.json")))["accepted"]
    by = M.index()
    return jobs, reads, by


def entry(name, jobs, reads, by):
    rec, how = M.lookup(name)
    via = "cosing_name" if rec else None
    plant = None
    cat = None
    if not rec:
        r = reads.get(name)
        if r:
            if r["kind"] == "INCI" and r.get("inci"):
                rec = by.get(M.k(r["inci"])) or by.get(M.k(re.sub(r"\([^()]*\)", "", r["inci"])))
                via = "two_reads" if rec else None
            elif r["kind"] == "PLANT":
                plant, via = r.get("plant"), "two_reads"
            elif r["kind"] == "NO_COSING":
                cat, via = CAT.get(r.get("category")), "two_reads"
            elif r["kind"] == "NOT_INGREDIENT":
                return {"job": None, "src": "not_ingredient"}
    if rec:
        inci = rec["inci"]
        j = jobs.get(inci)
        if j:
            return {"inci": inci, "job": j["job"], "src": "reviewed", "via": via,
                    "origin": RO.origin(inci), "fn": rec["functions"]}
        job, fn = RO.job(rec["functions"], name, inci)
        if job:
            return {"inci": inci, "job": job, "src": "cosing", "via": via, "origin": RO.origin(inci),
                    "fn": rec["functions"]}
        return {"inci": inci, "job": None, "src": "none", "via": via, "fn": rec["functions"]}
    if plant:
        return {"plant": plant, "job": "skin_conditioning", "src": "plant", "via": via, "origin": "plant"}
    if cat:
        return {"job": cat, "src": "read", "via": via}
    return {"job": None, "src": "none"}


def build(names):
    jobs, reads, by = load()
    return {n: entry(n, jobs, reads, by) for n in names}


def main():
    import collections
    db = json.load(open(sys.argv[1]))
    out = build(db["names"])
    use = collections.Counter()
    for p in db["p"]:
        if p.get("st") == "active":
            for i in set(p["i"]):
                use[db["names"][i]] += 1
    tot = sum(use.values())
    c = collections.Counter()
    for n, u in use.items():
        c[out[n]["src"]] += u
    print({k: f"{100 * v / tot:.1f}%" for k, v in c.most_common()})
    json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
