#!/usr/bin/env python3
"""Collect the package-image file names DailyMed lists for each label, from the image indexes on
the label-images* branches, into data/views/label_image_names.json:
  {setid: {"names": [front-first file names], "fetched_from": branch}}
The site shows the first as the product photo (https://dailymed.nlm.nih.gov/dailymed/image.cfm?
setid=...&name=...); a name that no longer exists on DailyMed simply shows no photo.
Front first: a name that says front/PDP/principal/carton/box/tube/bottle/label comes before one
that says drug facts/back/side/ingredients; otherwise DailyMed's order is kept."""
import json, os, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data/views/label_image_names.json")
FRONT = re.compile(r"front|pdp|principal|display|carton|box|tube|bottle|jar|stick|can\b|pouch|label|01\b|_1\b", re.I)
BACK = re.compile(r"drug.?facts|back|side|ingredient|df\b|panel.?2|insert|barcode", re.I)


def git(*a):
    return subprocess.check_output(["git", "-C", ROOT, *a], text=True)


def main():
    refs = [l.split("\t")[1].strip() for l in git("ls-remote", "origin", "refs/heads/label-images*").splitlines()]
    out = {}
    if os.path.exists(OUT):
        out = json.load(open(OUT))
    # older branches first, so a later fetch of the same label wins
    for ref in sorted(refs, key=lambda r: (not re.search(r"bw\d", r), r)):
        br = ref.split("refs/heads/")[1]
        try:
            git("fetch", "-q", "origin", f"+{ref}:refs/remotes/origin/{br}")
            idx = json.loads(git("show", f"origin/{br}:label_images/index.json"))
        except Exception:
            continue
        for sid, v in idx.items():
            names = [i["name"] for i in v.get("images") or [] if i.get("file")]
            if not names:
                continue
            names.sort(key=lambda n: (0 if FRONT.search(n) and not BACK.search(n) else 2 if BACK.search(n) else 1))
            out[sid] = {"names": names[:6], "fetched_from": br}
    json.dump(out, open(OUT, "w"), indent=0, ensure_ascii=False)
    print(json.dumps({"labels_with_images": len(out)}))


if __name__ == "__main__":
    main()
