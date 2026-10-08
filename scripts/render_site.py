#!/usr/bin/env python3
"""
scripts/render_site.py — render the arwhouse.com/evidence pages from
site/evidence.json and content/notes.json. Runs in CI right after
build_evidence.py, so the pages are rebuilt every week with the data.

Nothing on these pages is typed by hand except fixed labels. Every number
and every sentence about an ingredient comes from evidence.json (which only
holds verified claims) or from a note in content/notes.json that carries its
own primary source.

  python scripts/render_site.py           # write site/evidence/**
  python scripts/render_site.py --check   # also fail on contract breaks

Standard library only.
"""
import datetime
import html
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(ROOT, "site", "evidence.json")
NOTES = os.path.join(ROOT, "content", "notes.json")
OUT = os.path.join(ROOT, "site", "evidence")
SITE = "https://arwhouse.com"
BASE = "/evidence"
REPO = "https://github.com/arwfamily/tinysafe-dailymed-scraper-v2"

FINDING_TITLES = {
    "butyloctyl-salicylate": "Butyloctyl salicylate in mineral baby sunscreens",
}
JUR_NAME = {"US": "United States", "EU": "European Union", "AU": "Australia"}
JUR_BODY = {"US": "FDA", "EU": "European Commission", "AU": "TGA"}
ROLE = {"uv_filter_mineral": "Mineral UV filter", "uv_filter_organic": "Organic UV filter"}
# Phrases that must never reach a page (SITE_DATA_CONTRACT.md wording rules).
FORBIDDEN = [
    "absorbs uv", "absorb uv", "uv-absorbing", "hidden uv", "registered with the fda",
    "sold in the us", "hand-reviewed", "reviewed one by one", "product by product",
    "chemical uv filter", "boosts spf", "reef safe", "safest", "best sunscreen",
]
DRUG_FACTS = {"title": "21 CFR 201.66 — Format and content requirements for OTC drug product labeling (Drug Facts)",
              "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-C/part-201/subpart-C/section-201.66"}

E = lambda s: html.escape(str(s), quote=True)


# ---------------------------------------------------------------- pieces
ARCH = ('<svg class="arch" viewBox="0 0 64 96" fill="none" aria-hidden="true">'
        '<path d="M9 94V36a23 23 0 0 1 46 0v58" stroke="currentColor" stroke-width="6" '
        'stroke-linecap="square"/><circle cx="44" cy="60" r="3.4" fill="currentColor"/></svg>')
DOOR = ('<svg class="door" viewBox="0 0 10 14" aria-hidden="true"><path d="M1.5 13.5V6a3.5 3.5 0 0 1 7 0v7.5" '
        'fill="none" stroke="currentColor" stroke-width="1.3"/></svg>')


FAVICON = ARCH.replace('currentColor', '%23141613').replace(' class="arch"', ' xmlns="http://www.w3.org/2000/svg"')


def fmt_pct(x):
    if x is None:
        return None
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s + "%"


def fmt_date(iso):
    try:
        d = datetime.date.fromisoformat(iso[:10])
    except (TypeError, ValueError):
        return iso
    return d.strftime("%B %-d, %Y")


def short_source(jur, src):
    t = src.get("title", "")
    if jur == "US":
        m = re.search(r"OTC0000\d+", t)
        if m:
            return f"FDA order {m.group(0)}"
        if "Monograph M020" in t:
            return "FDA M020"
        if "Anthelios" in t:
            return "Ecamsule approval (news report)"
        return "FDA"
    if jur == "EU":
        return "EU Annex VI"
    if jur == "AU":
        return "TGA 2026"
    return t[:30]


def src_chip(label, url, title=""):
    return (f'<a class="chip" href="{E(url)}" title="{E(title)}" rel="noopener" target="_blank">'
            f'{DOOR}<span>{E(label)}</span></a>')


def glyph(status):
    # ink-only status marks; colour-blind safe, print safe
    shapes = {
        "permitted": '<circle cx="8" cy="8" r="5.5" fill="currentColor"/>',
        "permitted_with_conditions": ('<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                      '<path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor"/>'),
        "listed_no_numeric_limit": ('<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                    '<circle cx="8" cy="8" r="2" fill="currentColor"/>'),
        "approved_product_only": ('<rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                  '<circle cx="8" cy="8" r="2" fill="currentColor"/>'),
        "removal_finalized_not_yet_effective": ('<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
                                                '<path d="M4 12L12 4" stroke="currentColor" stroke-width="1.4"/>'),
        "removed": ('<circle cx="8" cy="8" r="5.5" fill="currentColor"/>'
                    '<path d="M4 12L12 4" stroke="var(--paper)" stroke-width="1.6"/>'),
        "not_listed": '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="2 2"/>',
    }
    return f'<svg class="g" viewBox="0 0 16 16" aria-hidden="true">{shapes[status]}</svg>'


STATUS_WORD = {
    "permitted": "Permitted",
    "permitted_with_conditions": "Permitted, with conditions",
    "listed_no_numeric_limit": "Listed, no numeric limit",
    "approved_product_only": "Only in FDA-approved products",
    "removal_finalized_not_yet_effective": "Removal final, not yet in effect",
    "removed": "Removed",
    "not_listed": "Not listed",
}


def cell_value(l):
    st = l["status"]
    if st in ("permitted", "permitted_with_conditions", "removal_finalized_not_yet_effective") and l["max_percent"] is not None:
        return fmt_pct(l["max_percent"])
    return {"listed_no_numeric_limit": "No limit set", "approved_product_only": "NDA only",
            "removed": "Removed", "not_listed": "Not listed"}.get(st, "—")


def units(n, total, cols, label):
    """A field of small arch doors, one per formulation; filled = counted."""
    w, h, gx, gy = 10, 14, 4, 5
    rows = -(-total // cols)
    vw, vh = cols * (w + gx) - gx, rows * (h + gy) - gy
    parts = []
    for i in range(total):
        x, y = (i % cols) * (w + gx), (i // cols) * (h + gy)
        d = f"M{x+1} {y+13.5}V{y+6}a4 4 0 0 1 8 0v{7.5}"
        if i < n:
            parts.append(f'<path d="{d}z" class="on"/>')
        else:
            parts.append(f'<path d="{d}" class="off"/>')
    return (f'<svg class="units" viewBox="-1 -1 {vw+2} {vh+2}" role="img" aria-label="{E(label)}">'
            + "".join(parts) + "</svg>")


def jsonld(obj):
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>")


def person():
    return {"@type": "Person", "name": "Angela Lee", "jobTitle": "Founder",
            "worksFor": {"@type": "Organization", "name": "ARW House", "url": SITE}}


def org():
    return {"@type": "Organization", "name": "ARW House", "url": SITE}


CSS = r"""
:root{--paper:#FAFAF7;--ink:#141613;--grey:#6E766A;--line:rgba(20,22,19,.12);--soft:rgba(20,22,19,.045);
--serif:"Instrument Serif",Georgia,serif;--sans:"DM Sans",-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#171A16;--ink:#F1F0EA;--grey:#A3A99D;--line:rgba(241,240,234,.14);--soft:rgba(241,240,234,.05)}}
:root[data-theme="dark"]{--paper:#171A16;--ink:#F1F0EA;--grey:#A3A99D;--line:rgba(241,240,234,.14);--soft:rgba(241,240,234,.05)}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:400 17px/1.65 var(--sans);-webkit-font-smoothing:antialiased;font-feature-settings:"tnum" 1}
a{color:inherit;text-decoration-thickness:1px;text-underline-offset:3px}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
@media(min-width:720px){.wrap{padding:0 32px}}
.top{display:flex;align-items:baseline;justify-content:space-between;gap:16px;padding:22px 0 18px;border-bottom:1px solid var(--line)}
.word{font-family:var(--serif);font-size:26px;text-decoration:none;display:inline-flex;align-items:baseline;gap:9px;white-space:nowrap}
.word .arch{height:.74em;width:auto}
.word em{font-style:normal;color:var(--grey)}
.top{flex-wrap:wrap}.top nav{display:flex;gap:18px;font-size:14px}
.top nav a{text-decoration:none;color:var(--grey)}.top nav a:hover,.top nav a[aria-current]{color:var(--ink)}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--grey);margin:0 0 14px}
h1,h2,h3{font-family:var(--serif);font-weight:400;letter-spacing:-.01em;margin:0}
h1{font-size:clamp(40px,7vw,72px);line-height:1.02;max-width:16ch}
h2{font-size:clamp(28px,4vw,38px);line-height:1.1;margin-bottom:14px}
h3{font-size:22px;line-height:1.2}
.hero{padding:56px 0 40px}
.lede{font-size:19px;max-width:58ch;margin:22px 0 0}
.byline{font-size:14px;color:var(--grey);margin:22px 0 0}
.crumb{font-size:14px;color:var(--grey);margin:28px 0 0}.crumb a{color:var(--grey)}
section{padding:44px 0;border-top:1px solid var(--line)}
.ledger{display:grid;grid-template-columns:repeat(2,1fr);gap:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
@media(min-width:720px){.ledger{grid-template-columns:repeat(4,1fr)}}
.ledger div{padding:20px 16px 18px 0}
.fig{font-family:var(--serif);font-size:clamp(44px,6vw,64px);line-height:1}
.fig small{font-size:.42em;color:var(--grey);margin-left:4px}
.figcap{font-size:13px;color:var(--grey);margin-top:6px;max-width:22ch}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;line-height:1;color:var(--grey);text-decoration:none;
border:1px solid var(--line);border-radius:999px;padding:4px 8px 4px 6px;white-space:nowrap;vertical-align:middle}
.chip:hover{color:var(--ink);border-color:var(--ink)}
.door{width:8px;height:11px}
.g{width:15px;height:15px;flex:none}
table.matrix{width:100%;border-collapse:collapse;font-size:15px}
.matrix th{font-weight:500;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--grey);text-align:left;padding:10px 8px;border-bottom:1px solid var(--ink)}
.matrix td{padding:12px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.matrix td:first-child{padding-left:0}
.matrix .name a{font-family:var(--serif);font-size:20px;text-decoration:none}
.matrix .name a:hover{text-decoration:underline}
.matrix .name span{display:block;font-size:12px;color:var(--grey)}
.v{display:flex;align-items:center;gap:7px;font-variant-numeric:tabular-nums}
.v + .chip{margin-top:6px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;color:var(--grey);margin:0 0 18px;padding:0;list-style:none}
.legend li{display:flex;align-items:center;gap:6px}
@media(max-width:640px){
 .matrix thead{display:none}.matrix,.matrix tbody,.matrix tr,.matrix td{display:block;width:100%}
 .matrix tr{padding:14px 0;border-bottom:1px solid var(--line)}.matrix td{border:0;padding:4px 0}
 .matrix td[data-j]{display:flex;align-items:center;justify-content:space-between;gap:10px}
 .matrix td[data-j]::before{content:attr(data-j);font-size:12px;letter-spacing:.1em;color:var(--grey);width:34px}
 .matrix td[data-j] .v{flex:1}.v + .chip{margin-top:0}}
.card{border:1px solid var(--line);border-radius:28px;padding:26px}
@media(min-width:720px){.card{padding:34px}}
.finding{display:grid;gap:26px}
@media(min-width:820px){.finding{grid-template-columns:1.05fr 1fr;align-items:center}}
.units{width:100%;max-width:440px;height:auto;display:block}
.units .on{fill:var(--ink);stroke:var(--ink);stroke-width:1.2}
.units .off{fill:none;stroke:var(--grey);stroke-width:1;opacity:.55}
.sentence{font-family:var(--serif);font-size:clamp(22px,2.6vw,28px);line-height:1.3;margin:0}
.fine{font-size:13px;color:var(--grey);margin:12px 0 0}
.framing{font-size:15px;border-left:2px solid var(--ink);padding:2px 0 2px 14px;margin:18px 0 0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
.more{display:inline-block;margin-top:18px;font-size:15px}
.answer{font-family:var(--serif);font-size:clamp(22px,2.8vw,30px);line-height:1.3;max-width:34ch;margin:0}
.jur{display:grid;gap:14px}
@media(min-width:820px){.jur{grid-template-columns:repeat(3,1fr)}}
.jur .card{padding:24px;display:flex;flex-direction:column;gap:10px}
.jur h3{font-family:var(--sans);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--grey);font-weight:500}
.jur .big{font-family:var(--serif);font-size:56px;line-height:1}
.jur .st{display:flex;align-items:center;gap:7px;font-size:14px}
.jur ul{margin:0;padding-left:18px;font-size:14px}
.jur .notes{font-size:14px;color:var(--grey);margin:0}
.jur .srcline{margin-top:auto;padding-top:12px;border-top:1px solid var(--line);font-size:12.5px;color:var(--grey)}
.jur .srcline a{color:var(--ink)}
.notebox{background:var(--soft);border-radius:28px;padding:26px}
.notebox h3{margin-bottom:8px}
.notebox p{margin:0;max-width:62ch}
details{border-top:1px solid var(--line);padding:16px 0}
details:last-of-type{border-bottom:1px solid var(--line)}
summary{cursor:pointer;font-family:var(--serif);font-size:21px;list-style:none;display:flex;justify-content:space-between;gap:16px}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";font-family:var(--sans);color:var(--grey)}
details[open] summary::after{content:"–"}
details p{margin:10px 0 0;max-width:64ch}
.pn{display:flex;justify-content:space-between;gap:16px;font-size:15px}
.cols{display:grid;gap:28px}@media(min-width:820px){.cols{grid-template-columns:1fr 1fr}}
.prose p,.prose li{max-width:64ch}
.srclist{list-style:none;padding:0;margin:0;font-size:15px}
.srclist li{padding:12px 0;border-bottom:1px solid var(--line)}
.srclist span{display:block;font-size:13px;color:var(--grey)}
footer{border-top:1px solid var(--line);margin-top:24px;padding:28px 0 48px;font-size:13px;color:var(--grey)}
footer .word{font-size:20px;color:var(--ink)}
footer p{margin:10px 0 0;max-width:72ch}
"""


def shell(path, title, description, body, ld, current=""):
    canon = SITE + path
    nav = [("Library", BASE), ("Findings", f"{BASE}/findings/butyloctyl-salicylate"), ("Method", f"{BASE}/methodology")]
    cur = ' aria-current="page"'
    navh = "".join(f'<a href="{u}"{cur if current == n else ""}>{n}</a>' for n, u in nav)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(description)}">
<link rel="canonical" href="{E(canon)}">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(description)}">
<meta property="og:url" content="{E(canon)}"><meta property="og:type" content="article"><meta property="og:site_name" content="ARW House">
<meta name="author" content="Angela Lee">
<link rel="icon" href="data:image/svg+xml,{E(FAVICON)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}</style>
{''.join(jsonld(x) for x in ld)}
</head><body>
<div class="wrap">
<header class="top"><a class="word" href="/">{ARCH}ARW House <em>Evidence</em></a><nav>{navh}</nav></header>
{body}
<footer>
<a class="word" href="/">{ARCH}ARW House</a>
<p>ARW House also makes Sunnytime, a mineral baby sunscreen. These pages do not rank or recommend products, and they are not medical advice. For medical decisions about your child, talk to your pediatrician.</p>
<p>Corrections: angela@arwhouse.com · <a href="{BASE}/data.json">Download the data (JSON)</a> · <a href="{REPO}">Source code and raw data</a></p>
</footer>
</div></body></html>
"""


# ---------------------------------------------------------------- pages
def page_index(d, notes):
    pop = d["registry_population"]
    n_cells = sum(len(i["limits"]) for i in d["ingredients"])
    rows = []
    for i in d["ingredients"]:
        tds = []
        for l in i["limits"]:
            s = l["source"]
            tds.append(f'<td data-j="{l["jurisdiction"]}"><div class="v">{glyph(l["status"])}'
                       f'<span title="{E(STATUS_WORD[l["status"]])}">{E(cell_value(l))}</span></div>'
                       f'{src_chip(short_source(l["jurisdiction"], s), s["url"], s.get("title", "") + " — " + s.get("version", ""))}</td>')
        rows.append(f'<tr><td class="name"><a href="{BASE}/ingredients/{i["slug"]}">{E(i["name"])}</a>'
                    f'<span>{E(ROLE.get(i["role"], ""))}</span></td>{"".join(tds)}</tr>')
    legend = "".join(f"<li>{glyph(k)}{E(v)}</li>" for k, v in STATUS_WORD.items())
    f = d["findings"][0] if d["findings"] else None
    finding_html = ""
    if f:
        finding_html = f"""
<section><p class="eyebrow">Finding</p>
<div class="card finding">
 <div>{units(f["numerator"], f["denominator"], 21, f'{f["numerator"]} of {f["denominator"]}')}
  <p class="fine">Each door is one mineral baby or kids formula. Filled: contains butyloctyl salicylate.</p></div>
 <div><p class="sentence">{E(f["sentence"])}</p>
  <a class="more" href="{BASE}/findings/{f["finding"]}">Read the finding →</a></div>
</div></section>"""
    site_notes = "".join(
        f'<section><div class="notebox"><h3>{E(n["heading"])}</h3><p>{E(n["text"])}</p>'
        f'<div class="chips">{src_chip("FDA", n["source"]["url"], n["source"]["title"])}</div></div></section>'
        for n in notes if "site" in n["applies_to"])
    body = f"""
<div class="hero"><p class="eyebrow">Baby sunscreen · Evidence library</p>
<h1>Every sunscreen filter, checked at the source.</h1>
<p class="lede">{len(d["ingredients"])} UV filters. Their legal limits in the United States, the European Union and Australia. How often US baby and kids sunscreen labels list each one. Every number opens its source.</p>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<div class="ledger">
 <div><div class="fig">{len(d["ingredients"])}</div><div class="figcap">UV filters</div></div>
 <div><div class="fig">{n_cells}</div><div class="figcap">legal limits, each linked to its own source</div></div>
 <div><div class="fig">{pop["formulations"]}</div><div class="figcap">baby and kids sunscreen formulas read from FDA DailyMed</div></div>
 <div><div class="fig">{pop["mineral_only"]}</div><div class="figcap">of them use only mineral actives</div></div>
</div>
<section><h2>The limits</h2>
<p class="fine" style="margin:0 0 18px">Maximum concentration of each filter in a finished sunscreen. Tap a filter for conditions, notes and the full source.</p>
<ul class="legend">{legend}</ul>
<table class="matrix"><thead><tr><th>Filter</th><th>United States</th><th>European Union</th><th>Australia</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>
{finding_html}
{site_notes}
"""
    ld = [{"@context": "https://schema.org", "@type": "Dataset",
           "name": "Baby sunscreen ingredient evidence: UV filter limits (US, EU, Australia) and US baby and kids label counts",
           "description": (f"Maximum permitted concentrations for {len(d['ingredients'])} sunscreen UV filters in the United States, "
                           f"European Union and Australia, each linked to its regulatory source, plus counts of how many "
                           f"{pop['formulations']} US baby and kids sunscreen formulas in FDA DailyMed list each filter."),
           "url": SITE + BASE, "dateModified": d["built_on"], "creator": org(), "author": person(),
           "publisher": org(),
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                             "contentUrl": SITE + BASE + "/data.json"}],
           "isBasedOn": sorted({l["source"]["url"] for i in d["ingredients"] for l in i["limits"]})}]
    return shell(BASE, "Baby Sunscreen Ingredient Evidence — UV filter limits in the US, EU and Australia · ARW House",
                 f"Legal limits for {len(d['ingredients'])} sunscreen UV filters in the US, EU and Australia, and how often "
                 f"US baby and kids sunscreen labels list each one. Every number linked to its source.",
                 body, ld, "Library")


def page_ingredient(d, i, prev, nxt, notes):
    reg = i["registry"]
    cards = []
    for l in i["limits"]:
        s, st, j = l["source"], l["status"], l["jurisdiction"]
        big = cell_value(l)
        sub = "maximum concentration" if l["max_percent"] is not None else ""
        conds = ""
        if l["conditions"]:
            conds = "<ul>" + "".join(
                f'<li>{E(c.get("applies_to", ""))}: up to {E(fmt_pct(c.get("max_percent")))}</li>' if isinstance(c, dict) else f"<li>{E(c)}</li>"
                for c in l["conditions"]) + "</ul>"
        note = (l.get("notes") or "").strip()
        names = {i["name"].lower(), *(a.lower() for a in i["also_known_as"])}
        if note.lower().strip(". ") in names:  # EU rows that only repeat the name
            note = ""
        noteh = f'<p class="notes">{E(note)}</p>' if note else ""
        eff = ""
        if st == "removal_finalized_not_yet_effective":
            eff = (f'<p class="notes"><strong>Removal takes effect {E(fmt_date(l.get("effective_date", "")))}.</strong> '
                   f'{src_chip("FDA order OTC000008-1", l.get("status_source_url", ""), "Final administrative order")}</p>')
        if st == "removed":
            eff = f'<p class="notes">{src_chip("FDA removal order", l.get("status_source_url", ""), "Final administrative order")}</p>'
        cards.append(f"""<div class="card"><h3>{JUR_NAME[j]} · {JUR_BODY[j]}</h3>
<div class="big">{E(big)}</div><div class="fine" style="margin:0">{sub}</div>
<div class="st">{glyph(st)}{E(STATUS_WORD[st])}</div>{conds}{eff}{noteh}
<div class="srcline">{DOOR} <a href="{E(s["url"])}" rel="noopener" target="_blank">{E(s.get("title", ""))}</a><br>{E(s.get("version", ""))} · checked {E(s.get("data_as_of", ""))}</div></div>""")
    regh = ""
    for r in reg:
        s = r["source"]
        regh += f"""
<div class="card finding" style="margin-top:14px">
 <div><div class="fig">{r["numerator"]}<small>of {r["denominator"]}</small></div>
 {units(r["numerator"], r["denominator"], 30 if r["denominator"] > 200 else 21, f'{r["numerator"]} of {r["denominator"]}')}</div>
 <div><p class="sentence">{E(r["sentence"])}</p><p class="fine">{E(r["caveat"])}</p>
 <div class="chips">{src_chip("Registry data", s["url"])}{src_chip("Review file", s["list_url"])}{src_chip("Method", s["method_url"])}</div>
 <p class="fine">DailyMed snapshot {E(s["snapshot"])}.</p></div></div>"""
    if regh:
        regh = f'<section><p class="eyebrow">On US labels</p><h2>How often baby and kids sunscreens list it</h2>{regh}</section>'
    own = [n for n in notes if i["slug"] in n["applies_to"]] + [n for n in notes if "site" in n["applies_to"]]
    notesh = "".join(
        f'<div class="notebox" style="margin-top:14px"><h3>{E(n["heading"])}</h3><p>{E(n["text"])}</p>'
        f'<div class="chips">{src_chip("Source", n["source"]["url"], n["source"]["title"])}</div></div>' for n in own)
    faq = [(f"What is the maximum concentration of {i['name'].lower()} allowed in sunscreen?", i["summary"])]
    for r in reg:
        if r["id"].startswith("US-BABY-ACTIVE-"):
            faq.append((f"How many US baby and kids sunscreens list {i['name'].lower()} as an active ingredient?", r["sentence"]))
    faqh = "".join(f"<details><summary>{E(q)}</summary><p>{E(a)}</p></details>" for q, a in faq)
    aka = f'<p class="fine">Also listed as {E(", ".join(a.title() for a in i["also_known_as"]))}.</p>' if i["also_known_as"] else ""
    pn = (f'<div class="pn">' + (f'<a href="{BASE}/ingredients/{prev["slug"]}">← {E(prev["name"])}</a>' if prev else "<span></span>")
          + (f'<a href="{BASE}/ingredients/{nxt["slug"]}">{E(nxt["name"])} →</a>' if nxt else "<span></span>") + "</div>")
    body = f"""
<p class="crumb"><a href="{BASE}">Library</a> / {E(i["name"])}</p>
<div class="hero" style="padding-top:28px"><p class="eyebrow">{E(ROLE.get(i["role"], ""))}</p>
<h1>{E(i["name"])}</h1>{aka}
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<section><p class="eyebrow">The short answer</p><p class="answer">{E(i["summary"])}</p></section>
<section><p class="eyebrow">By jurisdiction</p><div class="jur">{"".join(cards)}</div></section>
{regh}
<section><p class="eyebrow">Worth knowing</p>{notesh}</section>
<section><h2>Questions</h2>{faqh}</section>
<section>{pn}</section>"""
    path = f"{BASE}/ingredients/{i['slug']}"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": f"{i['name']} in sunscreen: legal limits and US baby label data",
           "url": SITE + path, "dateModified": d["built_on"], "author": person(), "publisher": org(),
           "about": {"@type": "ChemicalSubstance", "name": i["name"], "alternateName": i["also_known_as"]},
           "citation": sorted({l["source"]["url"] for l in i["limits"]})},
          {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
    return path, shell(path, f"{i['name']} in sunscreen — limits in the US, EU and Australia · ARW House Evidence",
                       i["summary"] + (" " + reg[0]["sentence"] if reg else ""), body, ld)


def page_finding(d, f):
    pop = d["registry_population"]
    s, isrc = f["source"], f.get("ingredient_source") or {}
    title = FINDING_TITLES[f["finding"]]
    faq = [
        ("Does this mean these products break the law?", f["legal_framing"]),
        ("Why does it matter where it is listed?",
         "On a US sunscreen, the Active ingredients section of the Drug Facts label lists the product's active "
         "ingredients. Butyloctyl salicylate is not an FDA sunscreen active ingredient, so it appears under Inactive "
         "ingredients. Parents reading only the Active ingredients section will not see it there."),
        ("How were these products selected?",
         f"The population is {pop['definition']}. That is {pop['formulations']} unique formulations, of which "
         f"{pop['mineral_only']} use only mineral actives (zinc oxide and/or titanium dioxide)."),
    ]
    faqh = "".join(f"<details><summary>{E(q)}</summary><p>{E(a)}</p></details>" for q, a in faq)
    body = f"""
<p class="crumb"><a href="{BASE}">Library</a> / Findings</p>
<div class="hero" style="padding-top:28px"><p class="eyebrow">Finding · US labels</p>
<h1>{E(title)}</h1>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<section><div class="card finding">
 <div><div class="fig">{f["numerator"]}<small>of {f["denominator"]}</small></div>
 {units(f["numerator"], f["denominator"], 21, f'{f["numerator"]} of {f["denominator"]}')}
 <p class="fine">Each door is one mineral baby or kids formula. Filled: contains butyloctyl salicylate.</p></div>
 <div><p class="sentence">{E(f["sentence"])}</p>
 <div class="chips">{src_chip("Manufacturer source", isrc.get("url", ""), isrc.get("title", ""))}{src_chip("Registry data", s["url"])}{src_chip("Review file", s["list_url"])}{src_chip("Method", s["method_url"])}</div>
 <p class="framing">{E(f["legal_framing"])}</p>
 <p class="fine">{E(f["caveat"])}</p></div></div></section>
<section class="cols prose"><div><h2>How we counted</h2>
<p>Population: {E(pop["definition"])}. That is {pop["formulations"]} unique formulations, of which {pop["mineral_only"]} use only mineral actives (zinc oxide and/or titanium dioxide). DailyMed snapshot {E(pop["snapshot"])}.</p>
<p><a href="{E(s["list_url"])}">Every include and exclude decision, with its reason</a> · <a href="{E(s["method_url"])}">The counting script</a></p></div>
<div><h2>What this means</h2>
<p>On a US sunscreen, the Active ingredients section of the Drug Facts label lists the product's active ingredients. Butyloctyl salicylate is not an FDA sunscreen active ingredient, so it appears under Inactive ingredients. {src_chip("21 CFR 201.66", DRUG_FACTS["url"], DRUG_FACTS["title"])}</p>
<p>This finding documents how often that happens in mineral products for babies and kids. It is about how labels work, not about any brand.</p></div></section>
<section><h2>Questions</h2>{faqh}</section>"""
    path = f"{BASE}/findings/{f['finding']}"
    ld = [{"@context": "https://schema.org", "@type": "Dataset", "name": title,
           "description": f"{f['numerator']} of {f['denominator']} mineral baby and kids sunscreen formulas in FDA DailyMed contain butyloctyl salicylate, which is not an FDA sunscreen active ingredient and is listed among the inactive ingredients.",
           "url": SITE + path, "dateModified": d["built_on"], "creator": org(), "author": person(),
           "isBasedOn": [s["url"], s["list_url"], isrc.get("url", "")],
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE + BASE + "/data.json"}]},
          {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
    return path, shell(path, f"{title} · ARW House Evidence", f["sentence"], body, ld, "Findings")


def page_method(d, notes):
    pop = d["registry_population"]
    srcs = {}
    for i in d["ingredients"]:
        for l in i["limits"]:
            s = l["source"]
            srcs.setdefault(s["url"], (s.get("title", ""), s.get("version", ""), JUR_NAME[l["jurisdiction"]]))
            if l.get("status_source_url"):
                srcs.setdefault(l["status_source_url"], ("FDA Final Administrative Order OTC000008-1 (aminobenzoic acid and trolamine salicylate)", "", "United States"))
    for n in notes:
        srcs.setdefault(n["source"]["url"], (n["source"]["title"], n["source"].get("version", ""), ""))
    for f in d["findings"]:
        if f.get("ingredient_source"):
            srcs.setdefault(f["ingredient_source"]["url"], (f["ingredient_source"]["title"], "checked " + f["ingredient_source"].get("checked", ""), ""))
    srcs.setdefault(DRUG_FACTS["url"], (DRUG_FACTS["title"], "eCFR, current", "United States"))
    srch = "".join(f'<li><a href="{E(u)}" rel="noopener" target="_blank">{E(t)}</a><span>{E(" · ".join(x for x in (j, v) if x))}</span></li>'
                   for u, (t, v, j) in srcs.items())
    body = f"""
<div class="hero"><p class="eyebrow">Method</p><h1>How every number here is made.</h1>
<p class="lede">These pages are rebuilt every week from public regulatory texts and the FDA's DailyMed label database. No number is typed by hand.</p>
<p class="byline">By Angela Lee, Founder · ARW House · Updated {E(fmt_date(d["built_on"]))}</p></div>
<section class="cols prose"><div><h2>Limits</h2>
<p>Each legal limit comes from the regulatory text of its jurisdiction: the FDA's OTC sunscreen monograph (M020) and its final orders, Annex VI of the EU Cosmetics Regulation, and Australia's Permissible Ingredients Determination. Each limit on this site links to the exact document and version it was read from.</p>
<p>Some statuses depend on a date. When an FDA removal order takes effect, the status changes on the next weekly rebuild.</p></div>
<div><h2>Label counts</h2>
<p>Population: {E(pop["definition"])}. {pop["formulations"]} unique formulations, {pop["mineral_only"]} with only mineral actives. Labels that are identical in formula are counted once. DailyMed snapshot {E(pop["snapshot"])}.</p>
<p>DailyMed lists drug labels submitted to the FDA, including labels for products made in US facilities for other markets. A listing is not proof that a product is on US shelves today.</p>
<p><a href="{REPO}/blob/main/claims/{E(pop["review_file"])}">Review file</a> · <a href="{REPO}/blob/main/claims/registry_stats.py">Counting script</a> · <a href="{REPO}/blob/main/docs/SITE_DATA_CONTRACT.md">Publishing rules</a></p></div></section>
<section class="cols prose"><div><h2>What we will not publish</h2>
<p>A sentence about what an ingredient does, unless a source for that exact ingredient says it. A number that has not passed its check. A ranking or a recommendation of products.</p></div>
<div><h2>Corrections</h2><p>If you find an error, write to angela@arwhouse.com with the page and the source. Fixes go into the data first, then into every page on the next rebuild.</p></div></section>
<section><h2>Sources</h2><ul class="srclist">{srch}</ul></section>"""
    path = f"{BASE}/methodology"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": "Method — ARW House Evidence", "url": SITE + path,
           "dateModified": d["built_on"], "author": person(), "publisher": org(), "citation": list(srcs)}]
    return path, shell(path, "Method — how every number is made · ARW House Evidence",
                       "How ARW House builds its baby sunscreen evidence pages: regulatory sources, DailyMed label counts, and publishing rules.",
                       body, ld, "Method")


# ---------------------------------------------------------------- build
def check(pages, d, notes):
    errs = []
    for n in notes:
        if not (n.get("source") or {}).get("url"):
            errs.append(f"note {n.get('id')}: no source url")
    for f in d["findings"]:
        if f["finding"] not in FINDING_TITLES:
            errs.append(f"finding {f['finding']}: no title in FINDING_TITLES")
    n_limits = sum(len(i["limits"]) for i in d["ingredients"])
    for path, h in pages.items():
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text)).lower()
        ld = " ".join(re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)).lower()
        for p in FORBIDDEN:
            if p in text or p in ld:
                errs.append(f"{path}: forbidden phrase {p!r}")
        if 'href=""' in h:
            errs.append(f"{path}: empty link")
    idx = pages[BASE]
    chips = idx.count('class="chip"')
    if chips < n_limits:
        errs.append(f"index: {chips} source chips for {n_limits} limits")
    return errs


def main():
    d = json.load(open(EVIDENCE, encoding="utf-8"))
    notes = json.load(open(NOTES, encoding="utf-8"))["notes"]
    pages = {BASE: page_index(d, notes)}
    ings = d["ingredients"]
    for k, i in enumerate(ings):
        p, h = page_ingredient(d, i, ings[k - 1] if k else None, ings[k + 1] if k + 1 < len(ings) else None, notes)
        pages[p] = h
    for f in d["findings"]:
        p, h = page_finding(d, f)
        pages[p] = h
    p, h = page_method(d, notes)
    pages[p] = h
    errs = check(pages, d, notes)
    if errs:
        print("RENDER CHECK FAILED:\n  " + "\n  ".join(errs))
        if "--check" in sys.argv:
            sys.exit(1)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)  # stale pages (a withdrawn finding) must disappear
    for path, h in pages.items():
        rel = path[len(BASE):].strip("/")
        fp = os.path.join(OUT, (rel + ".html") if rel else "index.html")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(h)
    shutil.copyfile(EVIDENCE, os.path.join(OUT, "data.json"))
    urls = "".join(f"<url><loc>{SITE}{p}</loc><lastmod>{d['built_on']}</lastmod></url>" for p in pages)
    open(os.path.join(OUT, "sitemap.xml"), "w").write(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    print(f"rendered {len(pages)} pages into site/evidence/ ({'checks passed' if not errs else 'WITH ERRORS'})")


if __name__ == "__main__":
    main()
