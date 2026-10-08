#!/usr/bin/env python3
"""
scripts/baby_track.py — weekly, after snapshot_and_history.py.

1. Keeps the baby/kids decision ledger current (claims/baby_decisions.csv).
   Every candidate the classifier flags gets exactly one decision:
     include  (stage auto)     baby/kids word in the PRODUCT NAME, product type
                               sunscreen, no kit/gift-set words. This is the rule
                               the 2026-10-08 review applied to 411 labels with
                               no exceptions.
     exclude  (stage auto)     the classifier's own false-positive phrases.
     queue                     anything else (brand-only signal, unresolved zinc,
                               lip/colour cosmetics, kits). Not counted until a
                               person decides; listed in claims/baby_queue.csv.
   Earlier decisions are never overwritten by the rule.
2. Writes the baby subset of the full dataset: data/views/baby_sunscreens.jsonl
3. Writes the weekly change report for ALL labels and for baby labels:
   data/reports/<run_date>.json and .md (new, reformulated with the exact
   ingredients added/removed, delisted).

Standard library only.
"""
import csv
import glob
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical", "us_sunscreens.jsonl")
HISTORY = os.path.join(ROOT, "data", "history", "us_formulation_history.jsonl")
LEDGER = os.path.join(ROOT, "claims", "baby_decisions.csv")
QUEUE = os.path.join(ROOT, "claims", "baby_queue.csv")
VIEW = os.path.join(ROOT, "data", "views", "baby_sunscreens.jsonl")
REPORTS = os.path.join(ROOT, "data", "reports")
RULE = "auto-rule v1: baby/kids word in product name, sunscreen, not a kit"
KIT = re.compile(r"\b(KIT|GIFT|SET|BUNDLE|DUO|TRIO|COMBO|VALUE PACK|TRAVEL PACK)\b", re.I)
FIELDS = ["setid", "decision", "stage", "reason", "decided_on", "title", "dailymed_url"]


def load_ledger():
    if os.path.exists(LEDGER):
        return {r["setid"]: r for r in csv.DictReader(open(LEDGER, encoding="utf-8"))}
    # first run: seed from the hand review
    seed = sorted(glob.glob(os.path.join(ROOT, "claims", "baby_review_*.csv")))[-1]
    day = re.search(r"(\d{4}-\d{2}-\d{2})", seed).group(1)
    out = {}
    for r in csv.DictReader(open(seed, encoding="utf-8")):
        out[r["setid"]] = {"setid": r["setid"], "decision": r["decision"], "stage": r["stage"],
                           "reason": r["reason"], "decided_on": day, "title": r["title"],
                           "dailymed_url": r.get("dailymed_url", "")}
    return out


def rule(r):
    sig, pt, title = r.get("baby_signal"), r.get("product_type"), r.get("title", "")
    if sig == "false_positive_phrase":
        return "exclude", "auto", "baby word is part of another phrase (classifier false-positive list)"
    if pt in ("skin_protectant", "calamine", "no_uv_filter"):
        return "exclude", "auto", f"not a sunscreen (classifier product type: {pt})"
    if (r.get("product_count") or 1) > 1:
        return "queue", "pending", f"{r['product_count']} products in one listing"
    if sig == "product_name" and pt == "sunscreen" and not KIT.search(title):
        return "include", "auto", RULE
    why = {"brand_name": "baby signal from brand only", "brand_list_review": "brand on the baby-brand list; check the product itself",
           "product_name": f"baby word in name but product type is {pt}" if pt != "sunscreen" else "looks like a kit or set"}
    return "queue", "pending", why.get(sig, f"signal {sig}")


def names(event, keys):
    """Map fingerprint keys (U:UNII / N:name) to ingredient names using the event's own lists."""
    m = {}
    for a in (event.get("active_ingredients") or []) + (event.get("inactive_ingredients") or []):
        if isinstance(a, dict):
            if a.get("unii"):
                m["U:" + a["unii"].upper()] = a.get("name")
            m["N:" + (a.get("name") or "").upper()] = a.get("name")
    return [m.get(k, k) for k in keys]


def main():
    recs = {}
    for l in open(CANON, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            recs[r["setid"]] = r
    ledger = load_ledger()
    run_date = max(r.get("last_seen") or "" for r in recs.values())

    new_decisions = []
    for sid, r in sorted(recs.items()):
        if r.get("baby_signal", "none") == "none" or sid in ledger:
            continue
        d, stage, reason = rule(r)
        ledger[sid] = {"setid": sid, "decision": d, "stage": stage, "reason": reason, "decided_on": run_date,
                       "title": r["title"], "dailymed_url": r["dailymed_url"]}
        new_decisions.append(ledger[sid])

    with open(LEDGER, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(ledger, key=lambda s: (ledger[s]["title"], s)):
            w.writerow({x: ledger[k].get(x, "") for x in FIELDS})
    queue = [v for v in ledger.values() if v["decision"] == "queue"]
    with open(QUEUE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for v in sorted(queue, key=lambda v: v["title"]):
            w.writerow(v)

    # baby subset of the full dataset (live labels only)
    os.makedirs(os.path.dirname(VIEW), exist_ok=True)
    baby_ids = {k for k, v in ledger.items() if v["decision"] == "include"}
    with open(VIEW, "w", encoding="utf-8") as f:
        for sid in sorted(baby_ids):
            if sid in recs:
                f.write(json.dumps({**recs[sid], "baby_decision": ledger[sid]}, ensure_ascii=False) + "\n")

    # weekly change report
    events = [json.loads(l) for l in open(HISTORY, encoding="utf-8") if l.strip()]
    first_by_setid = {}
    for e in events:
        first_by_setid.setdefault(e["setid"], e)
    week = [e for e in events if e["observed_on"] == run_date]
    prev_event = {}
    for e in events:
        if e["observed_on"] < run_date and e["change"] in ("new", "reformulated"):
            prev_event[e["setid"]] = e

    def item(e):
        out = {"setid": e["setid"], "change": e["change"], "product": e.get("product_name"),
               "dailymed": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={e['setid']}",
               "baby": e["setid"] in baby_ids}
        if e["change"] == "reformulated":
            out["added"] = names(e, e.get("keys_added") or [])
            out["removed"] = names(prev_event.get(e["setid"], first_by_setid.get(e["setid"], {})), e.get("keys_removed") or [])
            out["confidence"] = e.get("confidence")
        return out

    items = [item(e) for e in week]
    counts = defaultdict(int)
    bcounts = defaultdict(int)
    for it in items:
        counts[it["change"]] += 1
        if it["baby"]:
            bcounts[it["change"]] += 1
    report = {"run_date": run_date, "all_labels": dict(counts), "baby_labels": dict(bcounts),
              "baby_population_live": sum(1 for s in baby_ids if s in recs),
              "new_baby_decisions": new_decisions, "review_queue": len(queue), "changes": items}
    os.makedirs(REPORTS, exist_ok=True)
    json.dump(report, open(os.path.join(REPORTS, f"{run_date}.json"), "w"), indent=1, ensure_ascii=False)

    md = [f"# Weekly DailyMed sunscreen report — {run_date}", "",
          f"All labels: {dict(counts) or 'no changes'}  ",
          f"Baby/kids labels: {dict(bcounts) or 'no changes'} · live baby/kids labels: {report['baby_population_live']} · review queue: {len(queue)}", ""]
    refs = [it for it in items if it["change"] == "reformulated"]
    md.append("## Formula changes")
    md += [f"- {'**[BABY]** ' if it['baby'] else ''}[{it['product']}]({it['dailymed']}) — added: {', '.join(it['added']) or '—'}; removed: {', '.join(it['removed']) or '—'}" for it in refs] or ["- none"]
    md.append("\n## New baby/kids candidates")
    md += [f"- {d['decision']} ({d['stage']}): {d['title']} — {d['reason']}" for d in new_decisions] or ["- none"]
    md.append("\n## Delisted baby/kids labels")
    md += [f"- [{it['product']}]({it['dailymed']})" for it in items if it["change"] == "delisted" and it["baby"]] or ["- none"]
    open(os.path.join(REPORTS, f"{run_date}.md"), "w").write("\n".join(md) + "\n")
    print(f"[baby_track] {run_date}: {len(new_decisions)} new decisions, queue {len(queue)}, "
          f"baby live {report['baby_population_live']}, changes all={dict(counts)} baby={dict(bcounts)}")


if __name__ == "__main__":
    main()
