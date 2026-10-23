#!/usr/bin/env python3
"""OCR text of every in-scope label's package artwork (up to 8 images), so the
printed artwork can be compared with the label text the brand filed (2026-10-23:
of 37 labels whose filed text and artwork disagree, the artwork matched the product
on sale in 14 of 20 that could be settled). Runs on GitHub Actions, sharded.
Output: data/views/label_ocr_text/shard_N.jsonl.gz  {setid, spl_version, images_read, text}
"""
import argparse
import gzip
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

OUTDIR = os.path.join(ROOT, "data/views/label_ocr_text")


def read(job):
    sid, ver = job
    x = O.get(f"{O.BASE}/services/v2/spls/{sid}.xml")
    if not x:
        return {"setid": sid, "spl_version": ver, "error": "xml fetch failed"}
    secs, media = O.sections(ET.fromstring(x))
    pdp = [i for k, _, imgs in secs if k == "pdp" for i in imgs]
    rest = [i for i in media.values() if i not in pdp]
    txt, n = [], 0
    for name, alt in (pdp + rest)[:8]:
        if not re.search(r"\.(jpe?g|png|gif|tiff?)$", name, re.I):
            continue
        b = O.get(f"{O.BASE}/image.cfm?setid={sid}&name={urllib.parse.quote_plus(name)}")
        if b:
            txt.append(f"[[{name}]] " + O.ocr(b))
            n += 1
    return {"setid": sid, "spl_version": ver, "images_read": n, "text": re.sub(r"[ \t]+", " ", "\n".join(txt))[:40000]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    a = ap.parse_args()
    ver = {}
    for l in open(os.path.join(ROOT, "data/master/us_master.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r.get("in_scope") and r.get("status") == "active":
            ver[r["setid"]] = r.get("spl_version")
    # baby and kids labels first, so they are done even if a shard times out
    baby = {json.loads(l)["setid"] for l in open(os.path.join(ROOT, "data/master/us_master.jsonl"), encoding="utf-8")
            if json.loads(l).get("is_baby_kids")}
    todo = sorted(ver.items(), key=lambda j: (j[0] not in baby, j[0]))
    mine = [j for i, j in enumerate(todo) if i % a.shards == a.shard]
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"shard_{a.shard}.jsonl.gz")
    done = {}
    if os.path.exists(path):
        for l in gzip.open(path, "rt", encoding="utf-8"):
            d = json.loads(l)
            if not d.get("error"):
                done[(d["setid"], d.get("spl_version"))] = d
    fresh = [j for j in mine if j not in done]
    print(f"shard {a.shard}: {len(mine)} labels, {len(fresh)} to read", flush=True)
    out = list(done.values())

    def flush():
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for d in sorted(out, key=lambda d: d["setid"]):
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with ThreadPoolExecutor(3) as ex:
        for i, d in enumerate(ex.map(read, fresh), 1):
            out.append(d)
            if i % 100 == 0:
                flush()
                print(i, flush=True)
    flush()


if __name__ == "__main__":
    main()
