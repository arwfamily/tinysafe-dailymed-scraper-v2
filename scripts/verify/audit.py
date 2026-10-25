#!/usr/bin/env python3
"""Monthly independent audit of what the site shows (2026-10-25).

A fresh random sample of active labels, never audited before, is checked by independent
readers against the FDA label text and the filed package images (BRIEF_audit.md). The tally
goes to data/verification/audit_history.jsonl so the error rate is measured over time.

  python3 scripts/verify/audit.py sample WORK [--n 300]     # builds WORK/<setid>/ + WORK/partNN.json
  (one reader per part: "Follow scripts/verify/BRIEF_audit.md exactly. Your part file:
   WORK/partNN.json. Output: WORK/out_partNN.json")
  python3 scripts/verify/audit.py tally WORK                 # appends the result to the history

Strata: 1/3 baby/kids labels, 1/3 labels with a recall or a safety alert, 1/3 any label.
"""
import argparse, datetime, gzip, json, math, os, random, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
HIST = os.path.join(ROOT, "data/verification/audit_history.jsonl")
AUDITED = os.path.join(ROOT, "data/verification/audited_setids.json")
REPO = "arwfamily/tinysafe-dailymed-scraper-v2"
SAFETY = ("age_limit", "adult_active", "spray_powder", "fragrance", "not_broad_spectrum", "insect_repellent")


def gh(args, raw=False):
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    cmd = ["gh", "api"] + (["-H", "Accept: application/vnd.github.raw"] if raw else []) + args
    return subprocess.check_output(cmd, env=env, stderr=subprocess.DEVNULL)


def sample(a):
    work = os.path.abspath(a.work); os.makedirs(work, exist_ok=True)
    d = json.load(open(os.path.join(ROOT, "data/site/sunnytime_db.json"))); N = d["names"]; meta = d["meta"]
    act = [p for p in d["p"] if p.get("st", "active") == "active"]
    done = set(json.load(open(AUDITED))) if os.path.exists(AUDITED) else set()
    pool = [p for p in act if p["id"] not in done]
    rnd = random.Random(a.seed or int(datetime.date.today().strftime("%Y%m%d")))
    k = a.n // 3
    bk = [p for p in pool if p.get("bk")]
    spec = [p for p in pool if not p.get("bk") and (p.get("r") or any(f[0] in SAFETY for f in p["v3"]))]
    pick = rnd.sample(bk, min(k, len(bk))); s1 = {p["id"] for p in pick}
    rest = [p for p in spec if p["id"] not in s1]; pick += rnd.sample(rest, min(k, len(rest))); s1 = {p["id"] for p in pick}
    rest = [p for p in pool if p["id"] not in s1]; pick += rnd.sample(rest, min(a.n - len(pick), len(rest)))
    rel = {}
    for l in open(os.path.join(ROOT, "data/releases/us/latest/us_all.jsonl")):
        x = json.loads(l); rel[x["setid"]] = x
    ids = {p["id"] for p in pick}; T = {}
    for l in gzip.open(os.path.join(ROOT, "data/views/label_text_all.jsonl.gz"), "rt"):
        x = json.loads(l)
        if x["setid"] in ids:
            T[x["setid"]] = x
    IM = json.load(open(os.path.join(ROOT, "data/views/label_image_names.json")))
    items = []
    for p in pick:
        s = p["id"]; r = rel.get(s, {})
        fact = {"name": p["n"], "brand": p.get("b"), "spf": p.get("s"), "broad_spectrum_shown": p.get("bs"),
                "actives": p["z"], "actives_percent_withheld": bool(p.get("pw")), "mineral_type": p.get("m"),
                "filter_type": p.get("ft"), "baby_kids": bool(p.get("bk")), "inactive_ingredients": [N[i] for i in p["i"]],
                "warnings": [[f[0], meta.get(f[0], {}).get("l"), f[1]] for f in p["v3"]],
                "recalls_shown": [{"recall_number": x["recall_number"], "status": x["status"], "date": x.get("date"),
                                   "reason": x.get("reason")} for x in r.get("recalls") or []],
                "photo_shown": bool(p.get("im")), "evidence_tier": p.get("ev"), "spl_version": p.get("v")}
        d0 = os.path.join(work, s); os.makedirs(d0, exist_ok=True)
        json.dump(fact, open(os.path.join(d0, "site_shows.json"), "w"), indent=1, ensure_ascii=False)
        open(os.path.join(d0, "label_text.txt"), "w").write((T.get(s) or {}).get("text") or "(no label text)")
        br = (IM.get(s) or {}).get("fetched_from"); imgs = []
        if br:
            try:
                for f in json.loads(gh([f"repos/{REPO}/contents/label_images/{s}?ref={br}"]))[:3]:
                    pth = os.path.join(d0, f["name"])
                    open(pth, "wb").write(gh([f"repos/{REPO}/contents/{f['path']}?ref={br}"], raw=True))
                    imgs.append(pth)
            except Exception:
                pass
        items.append({"setid": s, "dir": d0, "images": imgs})
    for k in range(a.parts):
        json.dump(items[k::a.parts], open(os.path.join(work, f"part{k:02d}.json"), "w"), indent=1)
    print(json.dumps({"sampled": len(items), "with_images": sum(1 for i in items if i["images"]),
                      "tiers": {t: sum(1 for p in pick if p.get("ev") == t) for t in "ABC"}, "parts": a.parts}))


def tally(a):
    work = os.path.abspath(a.work); n = 0; hi = []; by = {}
    for k in range(100):
        f = os.path.join(work, f"out_part{k:02d}.json")
        if not os.path.exists(f):
            continue
        for o in json.load(open(f)):
            n += 1
            for e in o.get("errors") or []:
                key = f"{e.get('field')}|{e.get('severity')}"; by[key] = by.get(key, 0) + 1
            if any(e.get("severity") == "high" for e in o.get("errors") or []):
                hi.append(o["setid"])
    p = len(hi) / n if n else 0
    # Wilson 95% interval for the share of labels with a high-severity error
    z = 1.96; den = 1 + z * z / n if n else 1
    c = (p + z * z / (2 * n)) / den if n else 0
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den if n else 0
    row = {"date": datetime.date.today().isoformat(), "checked": n, "labels_with_high": len(hi),
           "rate": round(p, 4), "ci95": [round(max(0, c - w), 4), round(c + w, 4)], "by_field": by, "high_setids": hi}
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    done = set(json.load(open(AUDITED))) if os.path.exists(AUDITED) else set()
    for k in range(100):
        f = os.path.join(work, f"part{k:02d}.json")
        if os.path.exists(f):
            done |= {i["setid"] for i in json.load(open(f))}
    json.dump(sorted(done), open(AUDITED, "w"))
    print(json.dumps({k: row[k] for k in ("checked", "labels_with_high", "rate", "ci95")}))


ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
s1 = sp.add_parser("sample"); s1.add_argument("work"); s1.add_argument("--n", type=int, default=300)
s1.add_argument("--parts", type=int, default=14); s1.add_argument("--seed", type=int)
s2 = sp.add_parser("tally"); s2.add_argument("work")
a = ap.parse_args()
{"sample": sample, "tally": tally}[a.cmd](a)
