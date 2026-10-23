#!/usr/bin/env python3
"""Compare each label's package artwork (OCR text, data/views/label_ocr_text) with the
label text the brand filed (the printed list the Check shows), on what changes a parent's
answer: warning-level (T1/T2) ingredients, and the SPF.

A label is listed when the artwork's inactive-ingredients passage was read (40+ words)
and either:
  text_only  : a T1/T2 ingredient in the filed text has none of its distinctive words in
               the artwork passage (e.g. "Fragrance" in the text, not on the carton);
  art_only   : the artwork passage names a T1/T2 trigger the filed text does not have;
  spf        : the artwork prints one SPF and the Check shows another.
OCR misses words, so this is a list of candidates for a person to look at, not a verdict.

Output: data/views/artwork_compare.jsonl
"""
import glob
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

STOP = {"OIL", "EXTRACT", "ACID", "WATER", "SEED", "LEAF", "FRUIT", "FLOWER", "ROOT", "AND", "WITH", "THE"}
INACT = re.compile(r"(?:INACTIVE|OTHER)\s+INGRED\w*\s*:?(.{40,4000}?)(?=\b(?:OTHER INFORMATION|QUESTIONS|"
                   r"DIST(?:RIBUTED)?\.?\s+BY|MANUFACTURED|MADE IN|KEEP OUT|WARNINGS|DIRECTIONS)\b|\[\[|$)", re.I | re.S)
SPF = re.compile(r"\bSPF\s*-?\s*(\d{1,3})", re.I)


def words(s):
    return {w for w in re.findall(r"[A-Z]{4,}", s.upper()) if w not in STOP}


def main():
    import us_master as U
    eng, meta = U.engine_from_reference()
    tier = {k: v.get("t") for k, v in meta.items()}
    master = {}
    for line in open(U.MASTER, encoding="utf-8"):
        r = json.loads(line)
        if r.get("in_scope") and r.get("status") == "active":
            master[r["setid"]] = r
    ocr = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data/views/label_ocr_text/*.jsonl.gz"))):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            d = json.loads(line)
            r = master.get(d["setid"])
            if r and not d.get("error") and str(d.get("spl_version")) == str(r.get("spl_version")):
                ocr[d["setid"]] = d
    out, stats = [], {"labels": len(master), "artwork_read": len(ocr), "passage_read": 0, "listed": 0}
    for sid, d in ocr.items():
        r = master[sid]
        t = d.get("text") or ""
        passages = [m.group(1) for m in INACT.finditer(t)]
        art = " ".join(passages)
        pw = words(art)
        rec = {"setid": sid, "name": r["name"], "baby": bool(r.get("is_baby_kids"))}
        if len(art.split()) >= 40:
            stats["passage_read"] += 1
            printed = r["inactives"][:r.get("inactives_printed_n") or len(r["inactives"])]
            text_only = []
            for n in printed:
                fs = {f for f in eng.flags(n)[0] if tier.get(f) in ("T1", "T2")}
                w = words(n)
                if fs and w and not (w & pw):
                    text_only.append([n, sorted(fs)])
            have = set()
            for n in printed:
                have |= eng.flags(n)[0]
            art_only = []
            for chunk in re.split(r"[,;•·\n]", art):
                c = chunk.strip(" .*")
                if 3 <= len(c) <= 60:
                    fs = {f for f in eng.flags(c)[0] if tier.get(f) in ("T1", "T2")} - have
                    if fs:
                        art_only.append([c, sorted(fs)])
            if text_only:
                rec["text_only"] = text_only
            if art_only:
                rec["art_only"] = art_only
        spfs = sorted({int(m.group(1)) for m in SPF.finditer(t) if 2 <= int(m.group(1)) <= 100 and int(m.group(1)) != 15}
                      | ({15} if re.search(r"\bSPF\s*15\b(?!\s*(?:OR|AND)\s+(?:HIGHER|MORE))", t, re.I) else set()))
        if len(spfs) == 1 and r.get("spf") and spfs[0] != r["spf"]:
            rec["spf"] = {"check": r["spf"], "artwork": spfs[0]}
        if len(spfs) == 1 and not r.get("spf"):
            rec["spf_found"] = spfs[0]
        if any(k in rec for k in ("text_only", "art_only", "spf")):
            stats["listed"] += 1
        if len(rec) > 3:
            out.append(rec)
    with open(os.path.join(ROOT, "data/views/artwork_compare.jsonl"), "w", encoding="utf-8") as f:
        for rec in sorted(out, key=lambda x: (not x["baby"], x["setid"])):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
