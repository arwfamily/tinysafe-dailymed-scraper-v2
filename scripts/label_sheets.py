#!/usr/bin/env python3
"""Contact sheets of label artwork, for a person to read what the label text leaves out
(the SPF, a Broad Spectrum claim, the product form).

For each setid in data/views/sheet_targets.txt: download the label images from DailyMed,
take the six largest, and lay them out on one JPEG of at most 1500 x 1500 px
(label_sheets/<setid>.jpg). Runs in GitHub Actions; the sheets go to the
`label-sheets` branch. index: label_sheets/index.json {setid: {n_images, spl_version}}.
"""
import io
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "label_sheets")
UA = {"User-Agent": "TinySafe-research/1.0 (contact: support@tinysafe.app)"}
MAX = 1500


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def sheet(ims):
    from PIL import Image
    ims = sorted(ims, key=lambda im: -im.width * im.height)[:6]
    n = len(ims)
    cols = 1 if n == 1 else 2 if n <= 4 else 3
    rows = (n + cols - 1) // cols
    cw, ch = MAX // cols, MAX // rows
    canvas = Image.new("RGB", (cw * cols, ch * rows), "white")
    for k, im in enumerate(ims):
        s = min(cw / im.width, ch / im.height)
        t = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        canvas.paste(t, ((k % cols) * cw, (k // cols) * ch))
    return canvas


def main():
    from PIL import Image
    want = open(os.path.join(ROOT, "data/views/sheet_targets.txt")).read().split()
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    for n, sid in enumerate(want, 1):
        if sid in index:
            continue
        m = get(f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{sid}/media.json")
        data = json.loads(m)["data"] if m else {}
        ims = []
        for x in data.get("media", []):
            if not re.search(r"image/", x.get("mime_type", "")):
                continue
            b = get(x["url"])
            if b:
                try:
                    ims.append(Image.open(io.BytesIO(b)).convert("RGB"))
                except Exception:
                    pass
        if ims:
            sheet(ims).save(os.path.join(OUT, f"{sid}.jpg"), quality=82)
        index[sid] = {"n_images": len(ims), "spl_version": data.get("spl_version")}
        if n % 100 == 0:
            print(n, "done", flush=True)
            json.dump(index, open(idx_path, "w"))
        time.sleep(0.2)
    json.dump(index, open(idx_path, "w"))
    print(f"[sheets] {len(index)} labels")


if __name__ == "__main__":
    main()
