#!/usr/bin/env python3
"""Merge two independent readings of label text / label images into ledger rows.

Readers write JSON arrays (one object per label: setid, found, inactives,
legibility?, mismatch?, note?) as  <res>/TA_*.json + <res>/TB_*.json  (text) and
<res>/IA_*.json + <res>/IB_*.json  (images). Agreement rules (same as the
2026-10-19 full check):

  both found nothing             no_list_on_label_images (images) / needs_image (text: queue images)
  either reader saw another product   label_image_mismatch
  lists match item for item      confirmed
  differ by 1-2 items            confirmed if every leftover item is legible and either in the label
                                 text or in the filing/current list, or only a split difference;
                                 partial when illegible words were left out
  differ by more                 needs_review (nothing applied)
  Korean/CJK-only label          non_english_label (the English filing is kept)

Usage: python3 scripts/two_read_merge.py RES_DIR BATCH_DIR [--write]   (BATCH_DIR holds ib/*.json and tb/*.json)
"""
import collections
import datetime
import difflib
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import inactive_union as U  # noqa: E402
import ledger as L  # noqa: E402
from us_master import MASTER, akeys_of  # noqa: E402

CJK = re.compile(r"[ㄱ-힣一-鿿぀-ヿ]")


def m1(x, y):
    kx, ky = U.key(re.sub(r"\s*\[\?\]?", "", x)), U.key(re.sub(r"\s*\[\?\]?", "", y))
    return kx == ky or (min(len(kx), len(ky)) >= 5 and difflib.SequenceMatcher(None, kx, ky).ratio() >= 0.9) \
        or U.same(x, y)


def clean(lst, ak):
    out = []
    for x in U.resplit(lst or []):
        if U.is_active(x, ak):
            continue
        if not any(U.key(x) == U.key(o) for o in out):
            out.append(x)
    return out


def load(res, prefix, valid):
    out = {}
    for f in glob.glob(os.path.join(res, f"{prefix}_*.json")):
        for r in json.load(open(f, encoding="utf-8")):
            sid = r.get("setid", "")
            if sid not in valid:                        # a reader mistyped the id by a character
                best = max(valid, key=lambda v: difflib.SequenceMatcher(None, sid, v).ratio())
                if difflib.SequenceMatcher(None, sid, best).ratio() > 0.9:
                    sid = best
            out[sid] = r
    return out


def merge(res, batches):
    master = {}
    for line in open(MASTER, encoding="utf-8"):
        r = json.loads(line)
        master[r["setid"]] = r
    batch = {}
    for f in glob.glob(os.path.join(batches, "ib", "*.json")) + glob.glob(os.path.join(batches, "tb", "*.json")):
        for x in json.load(open(f, encoding="utf-8")):
            batch[x["setid"]] = x
    valid = set(batch)
    out = {}
    for kind, (pa, pb) in {"text": ("TA", "TB"), "img": ("IA", "IB")}.items():
        A, B = load(res, pa, valid), load(res, pb, valid)
        for sid in set(A) | set(B):
            a, b = A.get(sid), B.get(sid)
            src = "label_image_two_reads" if kind == "img" else "spl_text_two_reads"
            if not a or not b:
                out[sid] = {"status": "missing_read", "source": src}
                continue
            m = master.get(sid) or {}
            ak = akeys_of(m.get("actives") or [])
            raw_all = (a.get("inactives") or []) + (b.get("inactives") or [])
            if raw_all and sum(bool(CJK.search(x)) for x in raw_all) > 0.3 * len(raw_all):
                out[sid] = {"status": "non_english_label", "source": src}
                continue
            if kind == "img" and (a.get("mismatch") or b.get("mismatch")):
                out[sid] = {"status": "label_image_mismatch", "source": src,
                            "note": ((a.get("note") or "") + " | " + (b.get("note") or ""))[:300]}
                continue
            la = clean(a.get("inactives"), ak) if a.get("found") else []
            lb = clean(b.get("inactives"), ak) if b.get("found") else []
            if not la and not lb:
                if kind == "text":
                    out[sid] = {"status": "needs_image", "source": src}
                else:
                    unread = "unreadable" in ((a.get("legibility") or "") + (b.get("legibility") or ""))
                    out[sid] = {"status": "image_unreadable" if unread else "no_list_on_label_images",
                                "source": src, "note": (a.get("note") or "")[:200]}
                continue
            if not la or not lb:
                out[sid] = {"status": "needs_review", "source": src, "A": la, "B": lb}
                continue
            used, agreed = set(), []
            for x in la:
                for j, y in enumerate(lb):
                    if j not in used and m1(x, y):
                        used.add(j)
                        agreed.append(x)
                        break
            if len(agreed) < max(len(la), len(lb)) - 2:
                out[sid] = {"status": "needs_review", "source": src, "A": la, "B": lb}
                continue
            ref = (m.get("inactives") or []) + [x for x in (batch.get(sid) or {}).get("db_list") or []]
            raw = (batch.get(sid) or {}).get("label_text", "").upper()
            for x in la + lb:
                if any(m1(x, y) for y in agreed) or "[?" in x:
                    continue
                legible = len(re.sub(r"[^A-Za-z]", "", x)) >= 6
                in_text = raw and all(w in raw for w in re.sub(r"[^A-Z0-9]+", " ", x.upper()).split() if len(w) >= 3)
                if legible and (in_text or any(U.same(x, y) for y in ref) or kind == "img"):
                    agreed.append(x)
            left = [x for x in la + lb if not any(m1(x, y) for y in agreed)
                    and len(re.sub(r"[^A-Za-z]", "", x)) >= 3]          # a stray "1" is not an ingredient
            out[sid] = {"status": "partial" if left else "confirmed", "source": src, "inactives": agreed,
                        "n_read_a": len(la), "n_read_b": len(lb)}
            if left:
                out[sid]["one_reader_only"] = left
    return out, batch, master


def main():
    res, batches = sys.argv[1], sys.argv[2]
    out, batch, master = merge(res, batches)
    print(dict(collections.Counter(v["status"] for v in out.values())))
    if "--write" not in sys.argv:
        return
    today = datetime.date.today().isoformat()
    rows = []
    for sid, v in out.items():
        if v["status"] in ("missing_read", "needs_image"):
            continue
        ver = (master.get(sid) or {}).get("spl_version")
        row = {"setid": sid, "spl_version": str(ver), "checked": today, "origin": "two_reads"}
        row.update({k: v[k] for k in ("status", "source", "inactives", "one_reader_only", "note") if k in v})
        rows.append(row)
    L.append(rows)
    left = {s: v["status"] for s, v in out.items() if v["status"] in ("missing_read", "needs_image")}
    json.dump(left, open(os.path.join(res, "_not_settled.json"), "w"), indent=0)
    print(f"{len(rows)} ledger rows; {len(left)} not settled -> {res}/_not_settled.json")


if __name__ == "__main__":
    main()
