#!/usr/bin/env python3
"""Broad Spectrum claim and FDA Skin Cancer/Skin Aging Alert from label IMAGES,
for labels whose text did not show either (the front panel is often only an image).
Same tests as scripts/label_claims.py, on Tesseract text of the label's images
(front panel first, then up to 4 more). Runs on GitHub Actions, sharded.
Output: data/views/label_claims_ocr/shard_N.jsonl
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import label_ocr as O  # noqa: E402
from label_claims import ALERT, BOILER, BS  # noqa: E402

OUTDIR = os.path.join(ROOT, "data/views/label_claims_ocr")


def read(job):
    sid, ver = job
    x = O.get(f"{O.BASE}/services/v2/spls/{sid}.xml")
    if not x:
        return {"setid": sid, "spl_version": ver, "error": "xml fetch failed"}
    secs, media = O.sections(ET.fromstring(x))
    pdp = [i for k, _, imgs in secs if k == "pdp" for i in imgs]
    rest = [i for i in media.values() if i not in pdp]
    txt, n = [], 0
    for name, alt in (pdp + rest)[:6]:
        if not re.search(r"\.(jpe?g|png|gif|tiff?)$", name, re.I):
            continue
        b = O.get(f"{O.BASE}/image.cfm?setid={sid}&name={urllib.parse.quote_plus(name)}")
        if b:
            txt.append(O.ocr(b))
            n += 1
    t = re.sub(r"\s+", " ", " ".join(txt))
    return {"setid": sid, "spl_version": ver, "images_read": n,
            "broad_spectrum": bool(BS.search(BOILER.sub(" ", t))), "aging_alert": bool(ALERT.search(t))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    a = ap.parse_args()
    claims = {json.loads(l)["setid"]: json.loads(l) for l in open(os.path.join(ROOT, "data/views/label_claims.jsonl"))}
    ver = {}
    for l in open(os.path.join(ROOT, "data/master/us_master.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r.get("in_scope") and r.get("status") == "active":
            ver[r["setid"]] = r.get("spl_version")
    todo = sorted((s, v) for s, v in ver.items()
                  if s not in claims or not (claims[s].get("broad_spectrum") or claims[s].get("aging_alert")))
    mine = [j for i, j in enumerate(todo) if i % a.shards == a.shard]
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"shard_{a.shard}.jsonl")
    done = {}
    if os.path.exists(path):
        for l in open(path):
            d = json.loads(l)
            if not d.get("error"):
                done[(d["setid"], d.get("spl_version"))] = d
    fresh = [j for j in mine if j not in done]
    print(f"shard {a.shard}: {len(mine)} labels, {len(fresh)} to read", flush=True)
    out = list(done.values())

    def flush():
        with open(path, "w") as f:
            for d in sorted(out, key=lambda d: d["setid"]):
                f.write(json.dumps(d) + "\n")
    with ThreadPoolExecutor(3) as ex:
        for i, d in enumerate(ex.map(read, fresh), 1):
            out.append(d)
            if i % 100 == 0:
                flush()
                print(i, flush=True)
    flush()


if __name__ == "__main__":
    main()
