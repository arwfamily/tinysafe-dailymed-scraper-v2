#!/usr/bin/env python3
"""
scripts/fetch_label_images.py — download the label images of baby/kids labels
whose printed inactive-ingredient list is not text, so the list can be
transcribed from the image (data/corrections/printed_lists_from_images.jsonl).

Writes label_images/<setid>/<image name> (downscaled to at most 2400 px on the
long side, JPEG) and label_images/index.json {setid: {spl_version, title,
images: [{name, file, sha1_original}]}}. Run in GitHub Actions (needs network);
the images go to the `label-images` branch, not main.
"""
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from printed_changes import printed_list  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "label_images")
UA = {"User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"}


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            time.sleep(4 * (i + 1))
    return None


def main():
    from PIL import Image
    text = {json.loads(l)["setid"]: json.loads(l) for l in open(os.path.join(ROOT, "data/views/baby_label_text.jsonl"), encoding="utf-8")}
    view = [json.loads(l) for l in open(os.path.join(ROOT, "data/views/baby_sunscreens.jsonl"), encoding="utf-8")]
    targets = [r for r in view if printed_list(text.get(r["setid"], {})) is None]
    targets += [{"setid": s, "title": "", "spl_version": None} for s in sys.argv[1:]]
    index = {}
    for r in targets:
        sid = r["setid"]
        m = get(f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{sid}/media.json")
        media = (json.loads(m)["data"]["media"] if m else [])
        imgs = []
        os.makedirs(os.path.join(OUT, sid), exist_ok=True)
        for x in media:
            if not re.search(r"image/", x.get("mime_type", "")):
                continue
            b = get(x["url"])
            if not b:
                imgs.append({"name": x["name"], "error": "fetch failed"})
                continue
            im = Image.open(io.BytesIO(b)).convert("RGB")
            s = 2400 / max(im.size)
            if s < 1:
                im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
            fn = re.sub(r"[^A-Za-z0-9._-]", "_", x["name"]).rsplit(".", 1)[0] + ".jpg"
            im.save(os.path.join(OUT, sid, fn), quality=88)
            imgs.append({"name": x["name"], "file": f"{sid}/{fn}", "sha1_original": hashlib.sha1(b).hexdigest()})
        index[sid] = {"title": r.get("title"), "spl_version": r.get("spl_version"), "images": imgs}
        time.sleep(0.3)
    json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=1)
    print(f"[images] {len(index)} labels, {sum(len(v['images']) for v in index.values())} images")


if __name__ == "__main__":
    main()
