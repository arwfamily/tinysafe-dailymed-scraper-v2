#!/usr/bin/env python3
"""Fetch, for every label in data/views/thin_check_targets.json, what DailyMed has:

  - the current SPL XML: every section's text, the 'Inactive ingredient' section
    (LOINC 51727-6), and any other passage that starts an ingredient list
    ("Ingredients:", "Other ingredients:", "Inactive ingredients" inside the
    package-label or 'other information' section);
  - the label images (downscaled JPEG, long side <= 2000 px).

These are the labels whose inactive list is 7 items or fewer, or whose printed
list could not be read. Output goes to thin_check/ (pushed to the `thin-check`
branch by .github/workflows/thin_check.yml, not to main):

  thin_check/<setid>.json   {setid, spl_version, title, inactive_section,
                             ingredient_passages, images:[{name,file}], error}
  thin_check/img/<setid>/<name>.jpg

Needs network (GitHub Actions); standard library + Pillow.
"""
import io
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "thin_check")
UA = {"User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"}
NS = {"v3": "urn:hl7-org:v3"}
API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
NO_IMAGES = False
PASSAGE = re.compile(r"((?:inactive|other|non-?medicinal)?\s*ingredients?\s*[:：][^\n]{20,3000})", re.I)


def get(url):
    for i in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            # DailyMed answers 429 when pushed: back off much longer than for a network blip
            time.sleep((20 if "429" in str(e) else 3) * (i + 1))
    raise last


def text_of(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def sections(root):
    out = []
    for sec in root.iter("{urn:hl7-org:v3}section"):
        code = sec.find("v3:code", NS)
        title = sec.find("v3:title", NS)
        out.append({"code": code.get("code") if code is not None else None,
                    "title": text_of(title) if title is not None else "",
                    "text": text_of(sec.find("v3:text", NS)) if sec.find("v3:text", NS) is not None else ""})
    return out


def one(setid):
    rec = {"setid": setid, "images": [], "error": None}
    try:
        xml = get(f"{API}/spls/{setid}.xml")
        root = ET.fromstring(xml)
        ver = root.find("v3:versionNumber", NS)
        rec["spl_version"] = ver.get("value") if ver is not None else None
        t = root.find("v3:title", NS)
        rec["title"] = text_of(t) if t is not None else ""
        secs = sections(root)
        rec["inactive_section"] = " | ".join(s["text"] for s in secs if s["code"] == "51727-6" and s["text"])
        passages = []
        for s in secs:
            if s["code"] == "51727-6":
                continue
            for m in PASSAGE.finditer(s["text"]):
                before = s["text"][max(0, m.start() - 10):m.start()].lower()
                if re.search(r"(?<!in)active\s*$", before):      # "Active ingredients:" is not the inactive list
                    continue
                passages.append({"section": s["title"] or s["code"], "text": m.group(1)})
        rec["ingredient_passages"] = passages[:6]
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"spl: {e}"[:300]
    if NO_IMAGES:
        return rec
    try:
        media = json.loads(get(f"{API}/spls/{setid}/media.json"))
        from PIL import Image
        os.makedirs(os.path.join(OUT, "img", setid), exist_ok=True)
        for m in (media.get("data") or {}).get("media", [])[:12]:
            name, url = m.get("name"), m.get("url")
            if not url or not re.search(r"\.(jpe?g|png|gif)$", name or "", re.I):
                continue
            try:
                im = Image.open(io.BytesIO(get(url))).convert("RGB")
                im.thumbnail((2000, 2000))
                fn = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.splitext(name)[0]) + ".jpg"
                im.save(os.path.join(OUT, "img", setid, fn), "JPEG", quality=85)
                rec["images"].append({"name": name, "file": f"img/{setid}/{fn}"})
            except Exception as e:  # noqa: BLE001
                rec["images"].append({"name": name, "error": str(e)[:120]})
    except Exception as e:  # noqa: BLE001
        rec["error"] = (rec["error"] or "") + f" media: {e}"[:200]
    return rec


def main():
    import argparse
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="data/views/thin_check_targets.json")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--threads", type=int, default=1)
    a = ap.parse_args()
    global NO_IMAGES
    NO_IMAGES = a.no_images
    targets = json.load(open(os.path.join(ROOT, a.targets), encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)

    def work(t):
        rec = one(t["setid"])
        rec["db"] = t
        with open(os.path.join(OUT, t["setid"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        time.sleep(0.2)
        return 1
    done = 0
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        for _ in ex.map(work, targets):
            done += 1
            if done % 200 == 0:
                print(f"{done}/{len(targets)}", flush=True)
    print(f"done {done}")


if __name__ == "__main__":
    main()
