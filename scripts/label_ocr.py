#!/usr/bin/env python3
"""
scripts/label_ocr.py — read label IMAGES as text (Tesseract OCR) where the
DailyMed label carries no text for what we need.

Two jobs:
  front   For every sunscreen label without a baby/kids decision whose
          principal display panel (PDP) has little or no text, OCR the PDP
          images and look for baby/kids words (Drug Facts phrases such as
          "keep out of reach of children" removed first). Hits go to the
          review queue; nothing is included on OCR alone.
  inactive For every baby/kids label whose printed inactive-ingredient list is
          not text, OCR all label images and keep the "Inactive ingredients"
          passage, so ingredient counts and weekly change tracking can use
          the printed label.

Cached by (setid, spl_version): a label is only re-read when DailyMed
publishes a new version. Image bytes are hashed so an unchanged image never
produces a change event.

Usage: python scripts/label_ocr.py --shard I --shards N
Writes data/views/ocr/shard_<I>.jsonl, one line per label read:
  {setid, spl_version, job: [front|inactive], pdp_text_chars, images: [{name,
   sha1, role, alt}], front_ocr_baby_words, front_alt_baby_words,
   inactive_ocr, ocr_engine}
Needs network (DailyMed) and the `tesseract` binary (apt: tesseract-ocr).
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from classify import BABY_RE, BABY_FALSE_POSITIVE  # noqa: E402
from spl_parse import _FRONT_NOT_BABY  # noqa: E402
from printed_changes import printed_list  # noqa: E402

ROOT = os.path.dirname(HERE)
CANON = os.path.join(ROOT, "data", "canonical", "us_sunscreens.jsonl")
DECISIONS = os.path.join(ROOT, "claims", "baby_decisions.csv")
VIEW = os.path.join(ROOT, "data", "views", "baby_sunscreens.jsonl")
TEXT = os.path.join(ROOT, "data", "views", "baby_label_text.jsonl")
OUTDIR = os.path.join(ROOT, "data", "views", "ocr")
BASE = "https://dailymed.nlm.nih.gov/dailymed"
UA = {"User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"}
V3 = "{urn:hl7-org:v3}"
PDP_MIN_TEXT = 40          # a PDP with less text than this is read from its images
ENGINE = "tesseract"


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            time.sleep(4 * (i + 1))
    return None


def baby_words(text):
    t = BABY_FALSE_POSITIVE.sub(" ", _FRONT_NOT_BABY.sub(" ", text or ""))
    return sorted({m.group(0).upper() for m in BABY_RE.finditer(t)})


def sections(root):
    """[(kind, text, [image refs])] for every section; kind 'pdp' or 'other'."""
    out = []
    media = {}
    for om in root.iter(V3 + "observationMedia"):
        ref = om.find(f"{V3}value/{V3}reference")
        if ref is not None and ref.get("value"):
            alt = om.find(V3 + "text")
            media[om.get("ID")] = (ref.get("value"), "".join(alt.itertext()).strip() if alt is not None else "")
    for sec in root.iter(V3 + "section"):
        code = sec.find(V3 + "code")
        title = "".join(sec.find(V3 + "title").itertext()) if sec.find(V3 + "title") is not None else ""
        body = sec.find(V3 + "text")
        txt = re.sub(r"\s+", " ", "".join(body.itertext())).strip() if body is not None else ""
        refs = [rm.get("referencedObject") for rm in sec.iter(V3 + "renderMultiMedia")]
        imgs = [media[r] for r in refs if r in media]
        pdp = (code is not None and code.get("code") == "51945-4") or re.search(
            r"PRINCIPAL DISPLAY|PACKAGE LABEL|CARTON|DISPLAY PANEL", title.upper())
        out.append(("pdp" if pdp else "other", txt, imgs))
    return out, media


def ocr(img_bytes):
    """Tesseract on a grayscale, contrast-stretched copy scaled so the long side
    is about 3000 px (small artwork is upscaled; large photos are reduced)."""
    from PIL import Image, ImageOps
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "img.png")
        try:
            im = Image.open(io.BytesIO(img_bytes)).convert("L")
            s = 2000 / max(im.size)
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
            ImageOps.autocontrast(im).save(p)
        except Exception:
            return ""
        try:
            r = subprocess.run(["tesseract", p, "stdout", "--psm", "3", "-l", "eng"],
                               capture_output=True, timeout=180)
            return r.stdout.decode("utf-8", "replace")
        except Exception:
            return ""


def inactive_passage(text):
    m = re.search(r"(?:INACTIVE|OTHER)\s+INGRED\w*\s*:?(.{20,2500}?)(?=\b(?:OTHER INFORMATION|QUESTIONS|DIST(?:RIBUTED)?\.?\s+BY|"
                  r"MANUFACTURED|MADE IN|KEEP OUT|WARNINGS|DIRECTIONS)\b|$)", text, re.I | re.S)
    return ("Inactive ingredients: " + re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


def read_label(job):
    setid, ver, kinds = job
    x = get(f"{BASE}/services/v2/spls/{setid}.xml")
    if not x:
        return {"setid": setid, "spl_version": ver, "error": "xml fetch failed"}
    root = ET.fromstring(x)
    secs, media = sections(root)
    pdp_text = " ".join(t for k, t, _ in secs if k == "pdp")
    pdp_imgs = [i for k, _, imgs in secs if k == "pdp" for i in imgs]
    rec = {"setid": setid, "spl_version": ver, "job": sorted(kinds), "pdp_text_chars": len(pdp_text),
           "images": [], "ocr_engine": ENGINE}
    targets = []
    if "front" in kinds:
        if len(pdp_text) >= PDP_MIN_TEXT:
            rec["front_skipped"] = "pdp has text"
        else:
            targets += [(n, a, "pdp") for n, a in pdp_imgs]
            rec["front_alt_baby_words"] = baby_words(" ".join(a + " " + n for n, a in pdp_imgs))
    if "inactive" in kinds:
        targets += [(n, a, "label") for n, a in media.values() if (n, a, "pdp") not in targets]
    seen, front_txt, all_txt = set(), [], []
    for name, alt, role in targets:
        if name in seen or not re.search(r"\.(jpe?g|png|gif|tiff?)$", name, re.I):
            continue
        seen.add(name)
        b = get(f"{BASE}/image.cfm?setid={setid}&name={urllib.parse.quote_plus(name)}")
        if not b:
            rec["images"].append({"name": name, "role": role, "error": "fetch failed"})
            continue
        t = ocr(b)
        rec["images"].append({"name": name, "role": role, "alt": alt, "sha1": hashlib.sha1(b).hexdigest(),
                              "chars": len(t)})
        all_txt.append(t)
        if role == "pdp":
            front_txt.append(t)
    if "front" in kinds and "front_skipped" not in rec:
        rec["front_ocr_baby_words"] = baby_words(" ".join(front_txt))
    if "inactive" in kinds:
        rec["inactive_ocr"] = max((inactive_passage(t) for t in all_txt), key=len, default="")
    return rec


def jobs():
    decided = {r["setid"] for r in csv.DictReader(open(DECISIONS, encoding="utf-8"))}
    baby = {json.loads(l)["setid"] for l in open(VIEW, encoding="utf-8") if l.strip()}
    text = {}
    if os.path.exists(TEXT):
        for l in open(TEXT, encoding="utf-8"):
            d = json.loads(l)
            text[d["setid"]] = d
    out = {}
    for l in open(CANON, encoding="utf-8"):
        r = json.loads(l)
        sid, ver = r["setid"], r.get("spl_version")
        kinds = set()
        if r.get("is_sunscreen") and sid not in decided and not (r.get("label_flags") or {}).get("front_panel_baby_words"):
            kinds.add("front")
        # Image-only inactive lists of baby labels are transcribed from the
        # images (scripts/fetch_label_images.py); Tesseract drops small print.
        if sid in baby and printed_list(text.get(sid, {})) is None and os.environ.get("OCR_INACTIVE"):
            kinds.add("inactive")
        if kinds:
            out[sid] = (sid, ver, kinds)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"shard_{a.shard}.jsonl")
    cache = {}
    for f in os.listdir(OUTDIR):
        if f.endswith(".jsonl"):
            for l in open(os.path.join(OUTDIR, f), encoding="utf-8"):
                d = json.loads(l)
                if not d.get("error"):
                    cache[(d["setid"], d.get("spl_version"), tuple(d.get("job") or []))] = d
    todo = sorted(jobs().values())
    mine = [j for i, j in enumerate(todo) if i % a.shards == a.shard]
    if a.limit:
        mine = mine[:a.limit]
    fresh = [j for j in mine if (j[0], j[1], tuple(sorted(j[2]))) not in cache]
    print(f"[ocr] shard {a.shard}/{a.shards}: {len(mine)} labels, {len(fresh)} to read", flush=True)
    keep = [cache[(j[0], j[1], tuple(sorted(j[2])))] for j in mine if (j[0], j[1], tuple(sorted(j[2]))) in cache]
    new = []

    def flush():
        with open(path, "w", encoding="utf-8") as f:
            for d in sorted(keep + new, key=lambda d: d["setid"]):
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    # results are written every 200 labels, so a run cut off by a time limit
    # keeps what it read and the next run continues from the cache
    with ThreadPoolExecutor(3) as ex:
        for i, d in enumerate(ex.map(read_label, fresh), 1):
            new.append(d)
            if i % 200 == 0:
                flush()
                print(f"[ocr] {i}/{len(fresh)}", flush=True)
    flush()
    errs = sum(1 for d in new if d.get("error"))
    hits = sum(1 for d in keep + new if d.get("front_ocr_baby_words") or d.get("front_alt_baby_words"))
    print(f"[ocr] wrote {path}: {len(keep) + len(new)} labels ({errs} errors), {hits} with baby/kids words on the front")


if __name__ == "__main__":
    main()
