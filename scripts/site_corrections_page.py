#!/usr/bin/env python3
"""arwhouse.com/sunscreen-check/corrections: every correction to the Sunscreen Check.

Reader reports: data/corrections/reader_reports.jsonl, one JSON object per line:
  {"date": "YYYY-MM-DD", "product": "...", "setid": "...", "reported_by": "parent|brand",
   "what": "what was wrong", "fix": "what we changed (or 'no change: ...')"}
Audits: data/verification/audit_history.jsonl (monthly independent audit).

Usage: site_corrections_page.py <arwhouse checkout>
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STYLE = open(os.path.join(HERE, "site_rules_page.py"), encoding="utf-8").read()


def e(s):
    return html.escape(str(s or ""), quote=True)


def rows(p):
    p = os.path.join(ROOT, p)
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if os.path.exists(p) else []


def main():
    site = sys.argv[1]
    rep = sorted(rows("data/corrections/reader_reports.jsonl"), key=lambda r: r["date"], reverse=True)
    aud = [r for r in rows("data/verification/audit_history.jsonl") if r.get("checked", 0) >= 300]
    rep_html = ("".join(f'<li><b>{e(r["date"])} · {e(r["product"])}</b> Reported by a {e(r.get("reported_by", "reader"))}: {e(r["what"])} '
                        f'<span class="why">{e(r["fix"])}</span></li>' for r in rep)
                or "<li>No reader reports yet. This log started on October 26, 2026.</li>")
    aud_html = "".join(f'<li><b>{e(r["date"])}</b> {r["checked"]} randomly picked labels re-read against the package: '
                       f'{r["labels_with_high"]} ({r["rate"] * 100:.1f}%) had at least one error before review. '
                       f'<span class="why">{e(r.get("note_public") or r.get("note"))}</span></li>' for r in reversed(aud))
    css = STYLE[STYLE.index("<style>"):STYLE.index("</style>") + 8].replace("{{", "{").replace("}}", "}")
    page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Corrections to the Sunscreen Check · ARW House</title>
<meta name="description" content="Every correction to the Sunscreen Check, from reader reports and from our monthly independent audits.">
<link rel="canonical" href="https://arwhouse.com/sunscreen-check/corrections">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&display=swap" rel="stylesheet">
{css}
</head>
<body>
<div class="wrap">
<nav><a class="word" href="/">ARW House</a><a class="back" href="/sunscreen-check">← Back to Sunscreen Check</a></nav>
<h1>Corrections.</h1>
<p class="lead">When something on the Sunscreen Check is wrong, we fix it and list it here. Anyone, parent or brand, can report an error from a product card or at <a href="mailto:angela@arwhouse.com">angela@arwhouse.com</a>, with a photo of the package or a link.</p>
<div class="box"><p><b>How a report is handled.</b> Two readers check the evidence within 7 days. One report alone never changes a card. A brand's request to remove an item is accepted only with evidence that the ingredient is not in the product.</p></div>
<h2>From reader reports</h2>
<ul>{rep_html}</ul>
<h2>From our monthly audits</h2>
<p class="sub">Each month an independent reviewer re-reads 300 randomly picked labels against the package artwork filed with the FDA. Errors confirmed on review are corrected.</p>
<ul>{aud_html}</ul>
<footer><a href="/sunscreen-check/how-we-check">How the Check works</a> · ARW House</footer>
</div>
</body>
</html>
'''
    out = os.path.join(site, "sunscreen-check/corrections/index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(page)
    print("wrote", out)


if __name__ == "__main__":
    main()
