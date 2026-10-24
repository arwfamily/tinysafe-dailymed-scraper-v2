#!/usr/bin/env python3
"""Pick one package image per label for the Sunscreen Check result card.

The images are the package artwork the brand filed with the FDA (DailyMed media). The site
shows the picked image straight from DailyMed (image.cfm), so nothing is re-hosted, and only
while the label is still at the version the image was picked for.

Inputs: label_images/index.json of every label-images* branch (git), and, when given, a folder
with the downloaded images (their sizes help skip flat dielines and Drug Facts panels).
Output: data/views/product_image.json {setid: {"v": spl_version, "name": media name, "w": .., "h": ..}}

  python scripts/product_images.py [--local DIR ...]
"""
import argparse, glob, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data/views/product_image.json")

GOOD = re.compile(r"front|pdp|principal|primary|display|hero|outer|carton|tube|bottle|jar|stick|can\b|pack(?!age insert)", re.I)
BAD = re.compile(r"back|drug ?facts|facts|insert|screenshot|page|dieline|die ?line|proof|leaflet|ingredient|side|bottom|top|"
                 r"barcode|upc|spec|artwork ?\d+ ?of|panel ?[2-9]|_[2-9]\b|-0?[2-9]\.", re.I)


def indexes():
    out = {}
    br = subprocess.check_output(["git", "-C", ROOT, "branch", "-r"], text=True).split()
    for b in [x for x in br if "label-images" in x]:
        try:
            d = json.loads(subprocess.check_output(["git", "-C", ROOT, "show", f"{b}:label_images/index.json"],
                                                   text=True, stderr=subprocess.DEVNULL))
        except Exception:  # noqa: BLE001
            continue
        for sid, v in d.items():
            imgs = [i for i in v.get("images") or [] if i.get("file")]
            if imgs:
                out[sid] = imgs          # a later branch (newer fetch) wins
    return out


def sizes(dirs):
    from PIL import Image
    out = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "**/label_images/*/*.jpg"), recursive=True):
            sid = f.split("/")[-2]
            try:
                with Image.open(f) as im:
                    out[(sid, os.path.basename(f))] = im.size
            except Exception:  # noqa: BLE001
                pass
    return out


def score(img, wh):
    n = img["name"]
    s = 0
    if GOOD.search(n): s += 3
    if BAD.search(n): s -= 4
    if wh:
        w, h = wh; ar = w / h if h else 9
        if ar > 2.2 or ar < 0.42: s -= 3          # a flat dieline or a long strip
        if max(w, h) < 300: s -= 2                # a thumbnail-sized fragment
    return s


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--local", nargs="*", default=[]); a = ap.parse_args()
    M = {}
    for l in open(os.path.join(ROOT, "data/master/us_master.jsonl"), encoding="utf-8"):
        r = json.loads(l); M[r["setid"]] = r
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    idx = indexes(); wh = sizes(a.local) if a.local else {}
    out = dict(old)
    for sid, imgs in idx.items():
        r = M.get(sid)
        if not r:
            continue
        best = max(imgs, key=lambda i: (score(i, wh.get((sid, os.path.basename(i["file"])))), -imgs.index(i)))
        if score(best, wh.get((sid, os.path.basename(best["file"])))) < -3:
            continue                               # nothing that looks like the package front
        prev = old.get(sid)
        # an image picked earlier for this version stays; a new version takes the newest fetch
        if prev and str(prev.get("v")) == str(r.get("spl_version")) and prev.get("name") in {i["name"] for i in imgs}:
            continue
        size = wh.get((sid, os.path.basename(best["file"])))
        out[sid] = {"v": str(r.get("spl_version")), "name": best["name"], **({"w": size[0], "h": size[1]} if size else {})}
    json.dump(out, open(OUT, "w"), indent=0, sort_keys=True)
    print(f"[images] {len(out)} labels with a package image ({len(idx)} indexed)")


if __name__ == "__main__":
    main()
