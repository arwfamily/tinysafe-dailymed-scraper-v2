#!/usr/bin/env python3
"""
scripts/printed_changes.py — weekly, after scripts/baby_label_text.py.

The formula fingerprint (snapshot_and_history.py) reads the ingredient list the
labeler FILED with the FDA. Filings often omit items the printed label lists
(fragrance above all), so a change made only on the printed Drug Facts would be
missed. This script compares each baby/kids label's PRINTED inactive list with
the last one seen and logs the difference as its own event type,
`printed_list_changed`, never as `reformulated`.

Guards against false events:
  * a baseline is recorded the first time a label is seen; no event then;
  * only complete lists are compared (>= MIN_ITEMS items, read as text);
  * a change of this script's PARSER_VERSION re-baselines silently;
  * items are compared after normalisation (case, spacing, punctuation, the
    same synonyms the label parser uses), as a set: re-ordering alone is
    logged separately as `order_only`, not as an ingredient change;
  * a removed and an added item with near-identical spellings are still
    reported as a change, annotated `possible_spelling` for the reviewer: a
    typo fix and methylparaben -> ethylparaben look alike, so nothing is hidden.

Writes data/state/baby_printed_lists.json (state),
       data/history/baby_printed_changes.jsonl (events, append-only),
       and appends a section to this week's data/reports/<date>.md/.json.
Standard library only.
"""
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from spl_parse import split_ingredient_list, norm  # noqa: E402

ROOT = os.path.dirname(HERE)
TEXT = os.path.join(ROOT, "data", "views", "baby_label_text.jsonl")
VIEW = os.path.join(ROOT, "data", "views", "baby_sunscreens.jsonl")
STATE = os.path.join(ROOT, "data", "state", "baby_printed_lists.json")
EVENTS = os.path.join(ROOT, "data", "history", "baby_printed_changes.jsonl")
REPORTS = os.path.join(ROOT, "data", "reports")
PARSER_VERSION = 1
MIN_ITEMS = 8


def printed_list(d):
    """The printed inactive list of one archived label, or None if the label
    does not carry it as complete text."""
    secs = d.get("sections") or {}
    txt = " ".join(v for k, v in secs.items() if re.search(r"INACTIVE|^INGREDIENTS|^OTHER INGREDIENTS", k.upper()))
    if not txt:
        m = re.search(r"(?:INACTIVE|OTHER) INGREDIENTS?[^|]{40,}", d.get("text") or "", re.I)
        txt = m.group(0) if m else ""
    items = split_ingredient_list(txt) if txt else []
    items = [norm(x) for x in items if norm(x)]
    return items if len(items) >= MIN_ITEMS else None


def possible_spellings(removed, added):
    out = []
    for r in removed:
        for a in added:
            if difflib.SequenceMatcher(None, r, a).ratio() >= 0.8:
                out.append([r, a])
    return out


def main():
    run_date = None
    titles = {}
    if os.path.exists(VIEW):
        for line in open(VIEW, encoding="utf-8"):
            r = json.loads(line)
            titles[r["setid"]] = r.get("title")
            run_date = max(run_date or "", r.get("last_seen") or "")
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    events, baselined = [], 0
    for line in open(TEXT, encoding="utf-8"):
        d = json.loads(line)
        sid = d["setid"]
        if sid not in titles:
            continue  # queued or excluded labels are archived for review only
        items = printed_list(d)
        if items is None:
            continue
        prev = state.get(sid)
        state[sid] = {"items": items, "spl_version": d.get("spl_version"),
                      "effective_date": d.get("effective_date"), "parser": PARSER_VERSION, "seen": run_date}
        if not prev or prev.get("parser") != PARSER_VERSION:
            baselined += 1
            continue
        old, new = prev["items"], items
        if old == new:
            continue
        removed = sorted(set(old) - set(new))
        added = sorted(set(new) - set(old))
        spelling = possible_spellings(removed, added)
        kind = "printed_list_changed" if (removed or added) else "order_only"
        events.append({"observed_on": run_date, "setid": sid, "title": titles.get(sid), "change": kind,
                       "added": added, "removed": removed, "possible_spelling": spelling,
                       "spl_version": [prev.get("spl_version"), d.get("spl_version")],
                       "effective_date": [prev.get("effective_date"), d.get("effective_date")],
                       "dailymed": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={sid}"})
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
    os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
    with open(EVENTS, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # weekly report
    real = [e for e in events if e["change"] == "printed_list_changed"]
    md_path = os.path.join(REPORTS, f"{run_date}.md")
    js_path = os.path.join(REPORTS, f"{run_date}.json")
    if os.path.exists(md_path):
        lines = ["", "## Printed ingredient list changes (baby/kids labels)",
                 "Compared with the printed Drug Facts list of the previous week. Not a formula claim: "
                 "a printed change can be a correction of the label rather than of the product."]
        lines += [f"- [{e['title']}]({e['dailymed']}) — added: {', '.join(e['added']) or '—'}; "
                  f"removed: {', '.join(e['removed']) or '—'}"
                  + (f" (possible spelling fix: {'; '.join(a + ' → ' + b for a, b in e['possible_spelling'])})"
                     if e["possible_spelling"] else "") for e in real] or ["- none"]
        other = [e for e in events if e["change"] != "printed_list_changed"]
        if other:
            lines.append(f"- also {len(other)} labels re-ordered their list without adding or removing anything")
        body = open(md_path, encoding="utf-8").read().split("\n## Printed ingredient list changes")[0].rstrip("\n")
        open(md_path, "w", encoding="utf-8").write(body + "\n" + "\n".join(lines) + "\n")
    if os.path.exists(js_path):
        rep = json.load(open(js_path, encoding="utf-8"))
        rep["printed_list_changes"] = events
        json.dump(rep, open(js_path, "w"), indent=1, ensure_ascii=False)
    print(f"[printed_changes] {run_date}: {len(real)} printed-list changes, "
          f"{len(events) - len(real)} order-only, {baselined} labels baselined")


if __name__ == "__main__":
    main()
