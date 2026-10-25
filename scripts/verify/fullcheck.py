#!/usr/bin/env python3
"""Every published label against its own FDA label text, field by field (2026-10-24).
Lists each label where what the site shows and what the label text prints disagree, so a reader can
settle it from the package. Nothing is changed here.

  python3 scripts/verify/fullcheck.py data/site/sunnytime_db.json --out WORK/fullcheck.json
"""
import argparse, collections, gzip, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import us_master as U  # noqa: E402
from inactive_union import same_display  # noqa: E402

END = re.compile(r"\b(Other information|Other Information|OTHER INFORMATION|Questions|QUESTIONS|Directions|DIRECTIONS|Warnings|WARNINGS|"
                 r"Principal Display|PRINCIPAL DISPLAY|Package Label|PACKAGE LABEL|Purpose|PURPOSE|Uses\b|USES\b|Keep out|KEEP OUT|"
                 r"Distributed|DISTRIBUTED|Manufactured|MANUFACTURED|Made in|MADE IN|Label \d|\bLabel\b)")


def text_inactives(t):
    m = re.search(r"Inactive [Ii]ngredients?\s*:?\s*", t or "")
    if not m:
        return None
    rest = t[m.end():m.end() + 4000]
    e = END.search(rest)
    sec = rest[:e.start()] if e else rest[:1500]
    parts = [p.strip(" .;:*") for p in re.split(r"(?<!\d),\s*|,\s+(?![^()]*\))|,(?!\d)(?![^()]*\))", sec)]
    parts = [re.sub(r"(?i)^(may contain|\+/-)\s*:?\s*", "", p).strip() for p in parts]
    return [p for p in parts if 2 < len(p) < 80 and not re.match(r"(?i)^(and|may contain|\+/-)$", p)
            and not re.search(r"(?i)\b(www\.|inc\b|llc|ltd|suite|floor|road|street|ave\b|ny \d|ca \d|ontario|adverse|stop use|"
                              r"principal|display panel|label|trademark|distributed|made in)\b", p)
            and not re.search(r"\d+(\.\d+)?\s*%", p)]


def text_actives(t):
    m = re.search(r"Active [Ii]ngredients?", t or "")
    if not m:
        return {}
    seg = t[m.end():m.end() + 500]
    seg = re.split(r"Purpose|PURPOSE|Uses|USES|Inactive", seg)[0]
    out = {}
    seg = re.sub(r"(\d)\.\s*%", r"\1%", seg)
    for mm in re.finditer(r"([A-Za-z][A-Za-z \-]{3,45}?)\s*[(\[]?\s*(\d{1,2}(?:\.\d{1,3})?)\s*%", seg):
        k = U.filter_canon(mm.group(1))
        if k and k not in out:
            out[k] = float(mm.group(2))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("db"); ap.add_argument("--out", required=True); a = ap.parse_args()
    d = json.load(open(a.db)); N = d["names"]
    act = {p["id"]: p for p in d["p"] if p.get("st") == "active"}
    T = {}
    for l in gzip.open(os.path.join(ROOT, "data/views/label_text_all.jsonl.gz"), "rt"):
        x = json.loads(l)
        if x["setid"] in act and str(x.get("spl_version")) == str(act[x["setid"]].get("v")):
            T[x["setid"]] = x.get("text") or ""
    issues = collections.defaultdict(list)
    for s, p in act.items():
        t = T.get(s)
        if t is None:
            issues["no_current_label_text"].append(s); continue
        f = {x[0] for x in p["v3"]}
        # actives and strengths
        ta = text_actives(t)
        za = {(U.filter_canon(n) or n.upper()): pc for n, pc in p["z"]}
        zu = {k: v for k, v in za.items() if k in U.US_MAX or U.filter_canon(k)}
        if ta and not p.get("mp"):
            if set(ta) != set(zu):
                issues["actives_differ"].append({"id": s, "n": p["n"], "site": zu, "text": ta})
            elif not p.get("pw"):
                bad = {k: (zu[k], ta[k]) for k in ta if zu[k] is not None and abs(zu[k] - ta[k]) > 0.051}
                if bad:
                    issues["strength_differs"].append({"id": s, "n": p["n"], "site_vs_text": bad})
        # SPF
        spfs = {int(x) for x in re.findall(r"\bSPF\s*-?\s*(\d{1,3})\b", t, re.I) if 2 <= int(x) <= 100}
        if spfs and p.get("s") not in spfs and len(spfs) == 1 and not p.get("mp"):
            issues["spf_not_in_text"].append({"id": s, "n": p["n"], "site": p.get("s"), "text": sorted(spfs)})
        # inactives printed in the text but not shown
        ti = text_inactives(t)
        shown = [N[i] for i in p["i"]]
        if ti and len(ti) >= 3 and not p.get("mp"):
            miss = [x for x in ti if not any(x.upper() == y.upper() or same_display(x, y) or same_display(y, x) for y in shown)
                    and not U.is_active(x, U.akeys_of([{"name": n} for n, _ in p["z"]]))]
            if miss:
                issues["text_inactive_not_shown"].append({"id": s, "n": p["n"], "missing": miss[:12], "n_missing": len(miss)})
            if re.search(r"\b(fragrance|parfum)\b", " ".join(ti), re.I) and "fragrance" not in f \
                    and not re.search(r"fragrance[- ]free|no fragrance|without fragrance", " ".join(ti), re.I):
                issues["fragrance_in_text_no_warning"].append({"id": s, "n": p["n"]})
        # age limit
        al = U.age_limit(t)
        if al and "age_limit" not in f:
            issues["age_limit_text_no_warning"].append({"id": s, "n": p["n"], "text": al})
    out = {k: v for k, v in issues.items()}
    json.dump(out, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"labels": len(act), "with_text": len(T), **{k: len(v) for k, v in out.items()}}))


if __name__ == "__main__":
    main()
