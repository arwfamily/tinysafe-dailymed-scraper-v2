#!/usr/bin/env python3
"""Weekly package-artwork verification (the steps a Claude session runs after the Monday scrape;
see scripts/verify/RUNBOOK.md).

A label's evidence tier comes from people reading its package artwork (data/corrections):
  A  read twice by independent readers who agree   (artwork_reads + confirm_reads "confirmed")
  B  read once, matching the filing               (artwork_reads)
  C  the FDA filing only
Reads are tied to the label's spl_version: a new version starts again at C. This script picks
the labels that need reading, builds reading packs, and merges the readers' answers, with the
same evidence rules as the 2026-10-24 full pass (v3.12):
  read1    one transcription of the artwork; only fields that agree with the filing are used
  confirm  a second, independent check of what the site shows; "confirmed" (and sure) gives A
  third    a third reader, told neither earlier answer, settles what the first two disagreed on

Subcommands (paths relative to the repo; WORK is a scratch folder outside it):
  targets [--cap N] [--tag T]       write data/views/adult_batches/batch_T.txt
  packs read1|confirm|third WORK [--images DIR]
  merge read1|confirm|third WORK
  report OLD_DB NEW_DB [--out F]    labels whose version changed and lost a warning
"""
import argparse, collections, datetime, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
COR = os.path.join(ROOT, "data/corrections")
TODAY = datetime.date.today().isoformat()


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def master():
    return {r["setid"]: r for r in jl(os.path.join(ROOT, "data/master/us_master.jsonl"))}


def by_sid(name):
    return {r["setid"]: r for r in jl(os.path.join(COR, name))}


def upsert(name, rows):
    """Replace a correction file's entries for these setids (a newer read of the same label)."""
    p = os.path.join(COR, name)
    old = [r for r in jl(p) if r["setid"] not in {x["setid"] for x in rows}]
    with open(p, "w", encoding="utf-8") as fh:
        for r in old + rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def current(entry, rec):
    return entry and rec and str(entry.get("spl_version")) == str(rec.get("spl_version"))


# ---------------------------------------------------------------- targets
def targets(a):
    M = master(); ART = by_sid("artwork_reads.jsonl"); CF = by_sid("confirm_reads.jsonl")
    NA = by_sid("no_artwork.jsonl")
    need = []
    for sid, r in M.items():
        if r.get("status") != "active" or not r.get("in_scope"):
            continue
        if current(NA.get(sid), r):
            continue                           # this version has no readable artwork: not retried
        art = ART.get(sid)
        if not current(art, r):
            need.append((0, sid))              # never read at this version: read1 first
        elif art.get("readable") and not art.get("second_read") and not current(CF.get(sid), r):
            need.append((1, sid))              # read once: the second, independent check
    need.sort()
    sids = [s for _, s in need][:a.cap]
    tag = a.tag or "w" + TODAY.replace("-", "")
    p = os.path.join(ROOT, f"data/views/adult_batches/batch_{tag}.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("\n".join(sids) + "\n")
    c = collections.Counter(k for k, _ in need)
    print(json.dumps({"tag": tag, "file": os.path.relpath(p, ROOT), "targets": len(sids),
                      "need_read1": c[0], "need_confirm": c[1]}))


# ---------------------------------------------------------------- packs
def images_of(d):
    out = {}
    for p in glob.glob(os.path.join(d, "**/label_images/*/"), recursive=True) + glob.glob(os.path.join(d, "*/")):
        sid = p.rstrip("/").split("/")[-1]
        fs = sorted(f for f in glob.glob(p + "*") if f.lower().endswith((".jpg", ".jpeg", ".png")))
        if fs and re.match(r"^[0-9a-f-]{36}$", sid):
            out.setdefault(sid, fs)
    return out


def write_packs(work, stage, rows, prefix):
    d = os.path.join(work, stage)
    os.makedirs(os.path.join(d, "packs"), exist_ok=True); os.makedirs(os.path.join(d, "out"), exist_ok=True)
    names = []
    for i in range(0, len(rows), 12):
        n = f"{prefix}{i // 12:03d}"
        json.dump(rows[i:i + 12], open(os.path.join(d, "packs", n + ".json"), "w"), ensure_ascii=False)
        names.append(n)
    open(os.path.join(d, "queue.txt"), "w").write("".join(n + "\n" for n in names))
    print(json.dumps({"stage": stage, "products": len(rows), "packs": len(names), "dir": d}))


def packs(a):
    work = os.path.abspath(a.work)
    M = master()
    if a.stage == "read1":
        imgs = images_of(a.images)
        tag_file = sorted(glob.glob(os.path.join(ROOT, "data/views/adult_batches/batch_w*.txt")))[-1] if not a.targets else a.targets
        sids = open(tag_file).read().split()
        ART = by_sid("artwork_reads.jsonl")
        rows, none = [], []
        for s in sids:
            r = M.get(s)
            if not r or current(ART.get(s), r):
                continue
            if s not in imgs:
                none.append(s); continue
            rows.append({"setid": s, "spl_version": str(r.get("spl_version")), "images": imgs[s][:6]})
        json.dump(none, open(os.path.join(work, "no_images.json"), "w"))
        write_packs(work, "read1", rows, "r")
        print(json.dumps({"no_images": len(none)}))
    elif a.stage == "confirm":
        imgs = images_of(a.images)
        db = json.load(open(os.path.join(ROOT, "data/site/sunnytime_db.json"))); N = db["names"]
        CF = by_sid("confirm_reads.jsonl")
        rows = []
        for p in db["p"]:
            s = p["id"]; r = M.get(s)
            if p.get("st", "active") != "active" or p.get("ev") != "B" or s not in imgs or current(CF.get(s), r):
                continue
            rows.append({"setid": s, "spl_version": str(r.get("spl_version")), "images": imgs[s][:6], "shown": {
                "name": p["n"], "spf": p["s"], "broad_spectrum": p.get("bs"), "actives": p["z"],
                "inactives_in_order": [N[i] for i in p["i"]], "multi_product_note": p.get("mp")}})
        write_packs(work, "confirm", rows, "c")
    elif a.stage == "third":
        imgs = images_of(a.images)
        ART = by_sid("artwork_reads.jsonl"); T3 = by_sid("third_reads.jsonl")
        nz = lambda x: re.sub(r"[^A-Z0-9]", "", x.upper())  # noqa: E731
        rows = []
        for v in jl(os.path.join(work, "confirm", "merged.jsonl")):
            s = v["setid"]; r = M.get(s); art = ART.get(s) or {}
            if v["decision"] != "differs" or v.get("wrong_product") or (v.get("variants") or 1) > 1 or s not in imgs:
                continue
            if current(T3.get(s), r):
                continue
            q = {}
            if v.get("broad_spectrum") is True and not r.get("broad_spectrum") and art.get("broad_spectrum") is not True:
                q["broad_spectrum"] = True
            ai = {nz(x) for x in art.get("inactives") or []}
            nm = [re.sub(r"\s*\(.*?(duplicate|listed|appears|missing|not shown).*?\)\s*$", "", x, flags=re.I).strip()
                  for x in v.get("on_artwork_not_shown") or []]
            nm = [x for x in nm if x and nz(x) not in ai and len(x) < 120]
            if nm:
                q["names"] = nm[:15]
            if q:
                rows.append({"setid": s, "spl_version": v.get("spl_version"), "images": imgs[s][:6],
                             "product": (r or {}).get("name"), "questions": q})
        write_packs(work, "third", rows, "t")


# ---------------------------------------------------------------- merge
def outputs(work, stage):
    rows = {}
    for f in sorted(glob.glob(os.path.join(work, stage, "out", "*.json"))):
        for x in json.load(open(f)):
            rows[x["setid"]] = x
    return rows


def acts_norm(x):
    out = []
    for it in x or []:
        n, p = (it.get("name"), it.get("percent", it.get("pct"))) if isinstance(it, dict) else (list(it) + [None, None])[:2]
        if isinstance(p, str):
            try: p = float(p.strip("% "))
            except ValueError: p = None
        if n: out.append([n, p])
    return out


def agree_acts(read, filed):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from us_master import filter_canon
    a = {(filter_canon(n) or n.upper()): p for n, p in acts_norm(read)}
    b = {(filter_canon(x["name"]) or x["name"].upper()): x.get("percent") for x in filed or []}
    return a.keys() == b.keys() and all(a[k] is None or b[k] is None or abs(a[k] - b[k]) <= 0.05 for k in a)


def merge(a):
    work = os.path.abspath(a.work)
    M = master()
    if a.stage == "read1":
        out, na = [], []
        for s, x in outputs(work, "read1").items():
            r = M.get(s)
            if not r:
                continue
            ver = str(r.get("spl_version"))
            if not x.get("readable") or x.get("wrong_product"):
                na.append({"setid": s, "spl_version": ver, "read": TODAY,
                           "reason": "wrong_product" if x.get("wrong_product") else "unreadable", "notes": (x.get("notes") or "")[:500]})
                continue
            spray_read = bool(re.search(r"spray|aerosol|powder", x.get("form") or "", re.I))
            spray_rec = any(f[0] == "spray_powder" for f in r.get("flags") or [])
            e = {"setid": s, "spl_version": ver, "read": TODAY, "readable": True, "variants": x.get("variants") or 1,
                 # one read: a field that disagrees with the filing is not used (it waits for a
                 # second read); what agrees is the filing checked against the package
                 "spf": x.get("spf") if x.get("spf") in (None, r.get("spf")) else None,
                 "form": x.get("form") if spray_read == spray_rec else None,
                 "broad_spectrum": x.get("broad_spectrum"),
                 "actives": acts_norm(x.get("actives")) if agree_acts(x.get("actives"), r.get("actives")) else [],
                 "inactives": x.get("inactives"), "fragrance_free_claim": x.get("fragrance_free_claim"),
                 "scent_named": x.get("scent_named"), "allergen_statement": x.get("allergen_statement"),
                 "use_list": False, "filing_text_verified_current": False, "second_read": False,
                 "notes": (x.get("notes") or "")[:2000], "source": "weekly"}
            out.append(e)
        for s in json.load(open(os.path.join(work, "no_images.json"))) if os.path.exists(os.path.join(work, "no_images.json")) else []:
            r = M.get(s)
            if r:
                na.append({"setid": s, "spl_version": str(r.get("spl_version")), "read": TODAY, "reason": "no_images"})
        upsert("artwork_reads.jsonl", out); upsert("no_artwork.jsonl", na)
        print(json.dumps({"artwork_reads_added": len(out), "no_artwork": len(na)}))
    elif a.stage == "confirm":
        rows = []
        for s, v in outputs(work, "confirm").items():
            v["read"] = TODAY; rows.append(v)
        with open(os.path.join(work, "confirm", "merged.jsonl"), "w", encoding="utf-8") as fh:
            for v in rows:
                fh.write(json.dumps(v, ensure_ascii=False) + "\n")
        upsert("confirm_reads.jsonl", rows)
        print(json.dumps({"confirm_reads": len(rows), **collections.Counter(v["decision"] for v in rows)}))
    elif a.stage == "third":
        rows = []
        for s, v in outputs(work, "third").items():
            v["read"] = TODAY; rows.append(v)
        upsert("third_reads.jsonl", rows)
        print(json.dumps({"third_reads": len(rows)}))


# ---------------------------------------------------------------- report
def report(a):
    """The quality gate guards labels whose version did not change. A label whose filing changed
    can lose a warning legitimately (the brand took the ingredient out) or by a filing error; each
    such loss is listed for review."""
    old = json.load(open(a.old)); new = json.load(open(a.new))
    O = {p["id"]: p for p in old["p"]}
    lines = []
    for p in new["p"]:
        q = O.get(p["id"])
        if not q or str(q.get("v")) == str(p.get("v")) or p.get("st", "active") != "active":
            continue
        lost = sorted({f[0] for f in q["v3"]} - {f[0] for f in p["v3"]})
        if lost:
            gone = sorted({old["names"][i] for i in q["i"]} - {new["names"][i] for i in p["i"]})
            lines.append(f"- {p['n']} ({p['id']}, version {q.get('v')} -> {p.get('v')}): lost {', '.join(lost)}"
                         f"; names no longer listed: {', '.join(gone[:8]) or 'none'}")
    txt = f"# Warnings lost by labels whose filing changed ({TODAY})\n\n" + ("\n".join(lines) if lines else "None.") + "\n"
    if a.out:
        open(a.out, "w").write(txt)
    print(txt)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("targets"); t.add_argument("--cap", type=int, default=360); t.add_argument("--tag")
    for nm in ("packs", "merge"):
        x = sp.add_parser(nm); x.add_argument("stage", choices=["read1", "confirm", "third"]); x.add_argument("work")
        x.add_argument("--images", default=None); x.add_argument("--targets", default=None)
    r = sp.add_parser("report"); r.add_argument("old"); r.add_argument("new"); r.add_argument("--out")
    a = ap.parse_args()
    {"targets": targets, "packs": packs, "merge": merge, "report": report}[a.cmd](a)


if __name__ == "__main__":
    main()
